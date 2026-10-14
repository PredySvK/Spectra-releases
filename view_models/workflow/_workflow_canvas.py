"""Plain workflow canvas data and deterministic left-to-right placement."""
from collections.abc import Callable
from dataclasses import dataclass, replace

from core.block_kinds import KIND_TIME_RESPONSE
from core.workflow_graph import Workflow, resolve_workflow_chains
from signal_processing.workflow import BLOCKS, resolve_wire_port, topological_order
from signal_processing.workflow_readiness import resolve_workflow_readiness


@dataclass(frozen=True)
class CanvasPort:
    name: str
    side: str
    kinds: tuple[str, ...]
    required: bool
    from_measurement: bool = False


@dataclass(frozen=True)
class CanvasBlock:
    block_id: str
    block_type: str
    label: str
    ports: tuple[CanvasPort, ...]
    chain_index: int
    x: float
    y: float
    width: float
    height: float
    save_label: str | None
    error_text: str = ""
    selection_label: str | None = None


@dataclass(frozen=True)
class CanvasWire:
    from_block: str
    from_port: str
    to_block: str
    to_port: str


@dataclass(frozen=True)
class WorkflowCanvas:
    blocks: tuple[CanvasBlock, ...] = ()
    wires: tuple[CanvasWire, ...] = ()
    error: str = ""


def _block_height(block_type: str) -> float:
    spec = BLOCKS.get(block_type)
    return max(110.0, 70.0 + 24.0 * (len(spec.inputs) if spec is not None else 0))


def build_canvas_layout(workflow: Workflow) -> dict[str, tuple[float, float]]:
    """Every block's position: pinned from `workflow.layout`, otherwise automatic.

    Chains are weakly connected components in authoring order, stacked
    vertically. Columns follow the longest upstream path; siblings occupy
    separate rows. Cyclic imported graphs fall back to authoring order.
    Keys come chain by chain, each chain in authoring order.
    """
    incoming: dict[str, list[str]] = {b: [] for b in workflow.block_ids}
    for wire in workflow.wires:
        incoming[wire.to_block].append(wire.from_block)
    try:
        order = topological_order(workflow)
    except ValueError:
        order = list(workflow.block_ids)
    columns: dict[str, int] = {}
    for block_id in order:
        columns[block_id] = max((columns.get(b, -1) + 1 for b in incoming[block_id]), default=0)
    positions: dict[str, tuple[float, float]] = {}
    chain_y = 0.0
    for chain in resolve_workflow_chains(workflow):
        members = set(chain.block_ids)
        rows: dict[int, int] = {}
        chain_height = 0.0
        for block in workflow.blocks:
            if block.block_id not in members:
                continue
            column = columns[block.block_id]
            row = rows.get(column, 0)
            rows[column] = row + 1
            chain_height = max(chain_height, row * 170.0 + _block_height(block.block_type))
            positions[block.block_id] = workflow.layout.get(
                block.block_id, (column * 300.0, chain_y + row * 170.0))
        chain_y += chain_height + 80.0
    return positions


def build_pinned_workflow(before: Workflow, edited: Workflow) -> Workflow:
    """`edited` with every surviving block kept where it was drawn in `before`.

    The one way a structural edit (add, delete, wire, unwire) stores positions,
    so remaining blocks never re-flow; new blocks stay automatic.
    """
    kept = set(edited.block_ids)
    return replace(edited, layout={block_id: position for block_id, position
                                   in build_canvas_layout(before).items() if block_id in kept})


def build_workflow_canvas(
    workflow: Workflow | None, find_selection: Callable[[str], object] | None = None,
) -> WorkflowCanvas:
    """Describe even incomplete/invalid workflows, without owning their state.

    Positions come from `build_canvas_layout`. A block's error text is the
    first reason `resolve_chain_readiness` ties to it, and `error` the first
    such reason overall; `find_selection` lets a vanished Input selection be outlined too.
    """
    if workflow is None:
        return WorkflowCanvas()
    readiness = resolve_workflow_readiness(workflow, find_selection)
    chains = {block_id: index for index, (chain, _) in enumerate(readiness)
              for block_id in chain.block_ids}
    by_id = {block.block_id: block for block in workflow.blocks}
    blocks = []
    for block_id, (x, y) in build_canvas_layout(workflow).items():
        block = by_id[block_id]
        spec = BLOCKS.get(block.block_type)
        ports = tuple(CanvasPort(
            p.name, "left", p.accepts, not p.optional,
            from_measurement=p.from_measurement,
        ) for p in spec.inputs) if spec is not None else ()
        kind = KIND_TIME_RESPONSE if block.is_input else spec.produces if spec else "unknown"
        ports += (CanvasPort("out", "right", (kind,), False),)
        blocks.append(CanvasBlock(
            block_id, block.block_type, block_id, ports, chains[block_id],
            x, y, 220.0, _block_height(block.block_type),
            (block.save.label or "Save result set") if block.save is not None else None,
            selection_label=(
                ("Whole Data Pool" if block.input.whole_pool
                 else block.input.selection_name or "No selection")
                if block.input is not None else "No selection"
            ) if block.is_input else None,
        ))
    wires = tuple(CanvasWire(w.from_block, "out", w.to_block, resolve_wire_port(workflow, w))
                  for w in workflow.wires)
    block_errors: dict[str, str] = {}
    error = ""
    for _, issues in readiness:
        for issue in issues:
            if issue.block_ids:
                error = error or issue.text
            for block_id in issue.block_ids:
                block_errors.setdefault(block_id, issue.text)
    blocks = [replace(block, error_text=block_errors.get(block.block_id, "")) for block in blocks]
    return WorkflowCanvas(tuple(blocks), wires, error)
