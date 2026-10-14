# =====================================================================
# FILE: core/workflow_graph.py
# =====================================================================
"""
`Workflow` -- a block diagram (a DAG) of processing blocks, runnable over a whole
dataset.

This replaces `core/recipe.py`. A recipe was an *ordered chain*: the wire between
two steps was their adjacency in a list. The target picture the user described --
Simulink / ANSYS Workbench: branching, per-block settings, per-block saving of
intermediate results -- is a graph, and a linear chain is only its degenerate
case. Keeping a chain type alongside a graph type would grow two code paths that
drift apart in half a year, which is exactly what merging "Calculate & Save Data"
in phase 7 removed. So there is one model, and the ribbon's quick "Compute Result
Set..." path is built as a throwaway two-block graph (`input -> block`), not a
second model.

Pure data: no I/O, no Qt, no numpy, JSON round-trippable, so a project can store
one (`.nvhproject`) and a workflow file can carry one later. Two halves live
outside this file:

- turning block types into DSP calls, plus the *type-checking of a wire* (does the
  source's kind fit the target port?) -- `signal_processing/workflow.py`, which
  needs `BLOCKS` and numpy but still no I/O. That is why `__post_init__` here only
  checks graph *self-consistency* (unique block ids, wires whose endpoints exist):
  the wire compatibility check needs `BLOCKS` and cannot live in core/.
- feeding the input blocks real measurements off disk -- the runner in `gui/`
  (1.6: reading files is `io_modules/`, so the runner stands *above*
  `signal_processing/` and hands it already-loaded blocks; decision 2).

Frozen the whole way down, the same as `core/measurement_selection.py`:
`__post_init__` wraps the mapping fields in `MappingProxyType` so a workflow
handed to a background job cannot be edited underneath it. A half-frozen object
is worse than a mutable one -- it invites the assumption it is safe.

All internal documentation strings and variable labels are standardly written
in English.
"""
from dataclasses import dataclass, field, replace
from math import isfinite
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from core.frozen import freeze_identities, freeze_range_map, freeze_str_map
from core.models import ChannelIdentity

# The reserved `block_type` of an input block. An input block is a block -- it takes
# part in topological order and carries a `SaveSpec` like any other -- but it has
# no adapter in `BLOCKS`; the runner resolves it to loaded measurement blocks
# (decision 2). Later (phase 7E) it will also stand for a finished `.h5` result
# set used as input.
INPUT_BLOCK_TYPE = "input"


@dataclass(frozen=True)
class PortBinding:
    """
    How a block's non-primary input port is fed.

    A block's primary port is wired to an incoming wire. A second port -- order
    tracking's tacho -- is not another block's output; it is a raw channel of the
    same measurement the graph is running over. The binding names which channel
    that is; the runner resolves it per file at run time (1.12).

    Unchanged from the old `core/recipe.py`.
    """
    channel_type: str

    def to_dict(self) -> Dict[str, Any]:
        return {"channel_type": self.channel_type}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortBinding":
        return cls(channel_type=str((data or {}).get("channel_type") or ""))


@dataclass(frozen=True)
class InputSpec:
    """
    What an input block reads. Either a named `MeasurementSelection` stored in the
    project (decision 2 -- the selection itself is not embedded, it is a
    project-owned decision in `ProjectSession` and the workflow references it by
    name), or `whole_pool=True`: every measurement currently in the Data Pool,
    all channels, growing as the pool grows. `whole_pool` is the zero-config
    default so a fresh workflow runs without first authoring a selection; a named
    selection is how you narrow to a subset. The two are mutually exclusive --
    `whole_pool` wins if both are set.
    """
    selection_name: str = ""
    whole_pool: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"selection_name": self.selection_name, "whole_pool": self.whole_pool}

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "InputSpec":
        data = data or {}
        return cls(
            selection_name=str(data.get("selection_name") or ""),
            whole_pool=bool(data.get("whole_pool", False)),
        )


@dataclass(frozen=True)
class SaveSpec:
    """
    Which channels and measurements of a marked block's output get written to its
    result set (decision 4, 1.6). Saving is opt-in per block: a block with no
    `SaveSpec` produces nothing on disk, only an in-memory block the graph feeds
    downstream.

    A *static* filter only -- by channel identity or channel type, and by
    metadata facet (the same vocabulary `MeasurementSelection` uses). Filtering
    by a *computed* metric ("save only channels peaking above X") is deliberately
    out of v1: result-set coverage would then depend on the data, so "do I
    already have this?" could not be decided from parameters alone, and `status`
    would need a third value beyond today's `complete` / `partial`.

    `all_channels` is its own field rather than "an empty set means all", the
    same distinction `MeasurementSelection` and `ResultSetRef` make: an empty set
    means *no* channels.

    `label` is what the result set written at this block is called on disk. Blank
    lets the runner derive one (the run's own name for a single-save graph, that
    name plus the block id when several blocks save): a branching graph writes one
    folder per marked block, so each needs its own name, and 7C's panel is where
    the user types it.
    """
    label: str = ""
    all_channels: bool = True
    channel_identities: Tuple[ChannelIdentity, ...] = ()
    channel_types: Tuple[str, ...] = ()
    metadata_values: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    ranges: Mapping[str, Tuple[Any, Any]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "all_channels", bool(self.all_channels))
        object.__setattr__(self, "channel_identities", freeze_identities(self.channel_identities))
        object.__setattr__(self, "channel_types", tuple(str(t) for t in self.channel_types))
        object.__setattr__(self, "metadata_values", freeze_str_map(self.metadata_values))
        object.__setattr__(self, "ranges", freeze_range_map(self.ranges))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "all_channels": self.all_channels,
            "channel_identities": [list(identity) for identity in self.channel_identities],
            "channel_types": list(self.channel_types),
            "metadata_values": {key: list(values) for key, values in self.metadata_values.items()},
            "ranges": {key: list(bounds) for key, bounds in self.ranges.items()},
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "SaveSpec":
        data = data or {}
        return cls(
            label=str(data.get("label") or ""),
            all_channels=bool(data.get("all_channels", True)),
            channel_identities=tuple(
                (identity[0], identity[1] if len(identity) > 1 else None)
                for identity in (data.get("channel_identities") or ())
            ),
            channel_types=tuple(data.get("channel_types") or ()),
            metadata_values=data.get("metadata_values") or {},
            ranges={
                key: tuple(bounds) for key, bounds in (data.get("ranges") or {}).items()
                if bounds is not None
            },
        )


@dataclass(frozen=True)
class WorkflowBlock:
    """
    One block of the graph.

    A *workflow block* has `block_type` keying into `signal_processing.workflow.BLOCKS`,
    a flat JSON-safe `params` mirror of that block's `core/dsp_configs.py`
    dataclass (the block carries its own copy so the engine never reads the ribbon
    -- 1.12 pitfall 1, and decision 1: from the moment a block is saved the ribbon
    is never consulted again), `bindings` for its non-primary ports, and an
    `algorithm_version` stamped at authoring time (a mismatch on a later run is a
    warning, not a silent recompute -- 1.12 pitfall 5).

    An *input block* has `block_type == INPUT_BLOCK_TYPE` and an `input` spec; its
    `params` / `bindings` are unused.

    `save` is opt-in per block (decision 4). `None` means this block's output is
    only an intermediate the graph passes downstream.
    """
    block_id: str
    block_type: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    bindings: Mapping[str, PortBinding] = field(default_factory=dict)
    algorithm_version: Optional[int] = None
    save: Optional[SaveSpec] = None
    input: Optional[InputSpec] = None

    def __post_init__(self):
        if not self.block_id:
            raise ValueError("A workflow block needs a non-empty id.")
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "bindings", MappingProxyType({
            str(name): binding for name, binding in dict(self.bindings).items()
        }))

    @property
    def is_input(self) -> bool:
        return self.block_type == INPUT_BLOCK_TYPE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.block_id,
            "block_type": self.block_type,
            "params": dict(self.params),
            "bindings": {name: binding.to_dict() for name, binding in self.bindings.items()},
            "algorithm_version": self.algorithm_version,
            "save": None if self.save is None else self.save.to_dict(),
            "input": None if self.input is None else self.input.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowBlock":
        data = data or {}
        version = data.get("algorithm_version")
        save = data.get("save")
        source = data.get("input")
        return cls(
            block_id=str(data.get("node_id") or ""),
            block_type=str(data.get("block_type") or ""),
            params=dict(data.get("params") or {}),
            bindings={
                str(name): PortBinding.from_dict(raw)
                for name, raw in (data.get("bindings") or {}).items()
            },
            algorithm_version=None if version is None else int(version),
            save=None if save is None else SaveSpec.from_dict(save),
            input=None if source is None else InputSpec.from_dict(source),
        )


@dataclass(frozen=True)
class WorkflowWire:
    """
    A wire from `from_block`'s output into `to_block`'s port `to_port` (empty means
    the primary port).

    There is no `from_port`: a `multi_output` block (order tracking emits one block
    per order) is not allowed an outgoing wire -- nothing can consume a list --
    so a wire always starts at a single-output block.
    """
    from_block: str
    to_block: str
    to_port: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"from_node": self.from_block, "to_node": self.to_block, "to_port": self.to_port}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowWire":
        data = data or {}
        return cls(
            from_block=str(data.get("from_node") or ""),
            to_block=str(data.get("to_node") or ""),
            to_port=str(data.get("to_port") or ""),
        )


@dataclass(frozen=True)
class Workflow:
    """
    A named block diagram. `blocks` order is authoring order only (for display) --
    the data flow is `wires`, never adjacency.

    `layout` stores optional canvas positions separately from processing blocks
    and result identity. Missing positions use the view-model's automatic placement.

    `__post_init__` checks only what can be checked without `BLOCKS`: block ids are
    unique, and every wire endpoint names a block that exists. Cycle detection,
    port type-checking and "every mandatory port is fed" are `validate_graph` in
    `signal_processing/workflow.py`.
    """
    name: str = ""
    blocks: Tuple[WorkflowBlock, ...] = ()
    wires: Tuple[WorkflowWire, ...] = ()
    layout: Mapping[str, Tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "wires", tuple(self.wires))

        seen: set = set()
        for workflow_block in self.blocks:
            if workflow_block.block_id in seen:
                raise ValueError(f"Duplicate workflow block id '{workflow_block.block_id}'.")
            seen.add(workflow_block.block_id)

        positions = {}
        for block_id, position in self.layout.items():
            if block_id not in seen:
                raise ValueError(f"Layout references unknown block '{block_id}'.")
            x, y = position
            x, y = float(x), float(y)
            if not isfinite(x) or not isfinite(y):
                raise ValueError("Layout positions must be finite.")
            positions[block_id] = (x, y)
        object.__setattr__(self, "layout", MappingProxyType(positions))

        for wire in self.wires:
            for endpoint, side in ((wire.from_block, "from"), (wire.to_block, "to")):
                if endpoint not in seen:
                    raise ValueError(
                        f"Wire {side} unknown block '{endpoint}'. "
                        f"Known blocks: {', '.join(sorted(seen)) or '(none)'}."
                    )

    @property
    def block_ids(self) -> Tuple[str, ...]:
        return tuple(workflow_block.block_id for workflow_block in self.blocks)

    def block(self, block_id: str) -> WorkflowBlock:
        for workflow_block in self.blocks:
            if workflow_block.block_id == block_id:
                return workflow_block
        raise KeyError(block_id)

    def incoming(self, block_id: str) -> Tuple[WorkflowWire, ...]:
        """Wires feeding `block_id`, in authoring order."""
        return tuple(wire for wire in self.wires if wire.to_block == block_id)

    def outgoing(self, block_id: str) -> Tuple[WorkflowWire, ...]:
        """Wires leaving `block_id`, in authoring order."""
        return tuple(wire for wire in self.wires if wire.from_block == block_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [workflow_block.to_dict() for workflow_block in self.blocks],
            "edges": [wire.to_dict() for wire in self.wires],
            **({"layout": {key: list(position) for key, position in self.layout.items()}}
               if self.layout else {}),
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Workflow":
        data = data or {}
        return cls(
            name=str(data.get("name") or ""),
            blocks=tuple(WorkflowBlock.from_dict(raw) for raw in (data.get("nodes") or ())),
            wires=tuple(WorkflowWire.from_dict(raw) for raw in (data.get("edges") or ())),
            layout=data.get("layout") or {},
        )


# -- immutable edit helpers ------------------------------------------------------
def resolve_workflow_chains(workflow: Workflow) -> Tuple[Workflow, ...]:
    """Derive connected parts, preserving authoring order and stored positions.

    Direction does not affect chain membership. A wire joining two Inputs makes
    one chain; whether it can run is the orchestration layer's decision.
    """
    neighbours = {block_id: set() for block_id in workflow.block_ids}
    for wire in workflow.wires:
        neighbours[wire.from_block].add(wire.to_block)
        neighbours[wire.to_block].add(wire.from_block)
    remaining = set(workflow.block_ids)
    groups = []
    for block_id in workflow.block_ids:
        if block_id not in remaining:
            continue
        members = set()
        pending = [block_id]
        while pending:
            current = pending.pop()
            if current in members:
                continue
            members.add(current)
            pending.extend(neighbours[current] - members)
        remaining.difference_update(members)
        groups.append(members)
    if len(groups) == 1:
        return (workflow,)
    chains = []
    for index, members in enumerate(groups, 1):
        blocks = tuple(block for block in workflow.blocks if block.block_id in members)
        inputs = ", ".join(block.block_id for block in blocks if block.is_input) or blocks[0].block_id
        chains.append(Workflow(
            name=f"{workflow.name} - Chain {index} ({inputs})",
            blocks=blocks,
            wires=tuple(wire for wire in workflow.wires if wire.from_block in members),
            layout={key: position for key, position in workflow.layout.items() if key in members},
        ))
    return tuple(chains)


# A Workflow is frozen the whole way down, so a graph editor (phase 7C tree,
# phase 8 canvas) makes changes by rebuilding: each helper returns a new Workflow.
# They stay here, on the pure-data model, because none needs `BLOCKS` -- adding a
# workflow block with its default bindings and version stamp does, and that one
# lives in `signal_processing/workflow.py` (`new_workflow_block`).


def new_workflow(name: str, *, input_block_id: str = "input") -> "Workflow":
    """A fresh graph: one input block defaulting to the whole Data Pool, no blocks
    yet. The user adds blocks afterwards and can narrow the input to a saved
    selection -- but a fresh workflow is runnable without authoring one first."""
    return Workflow(
        name=name,
        blocks=(WorkflowBlock(input_block_id, INPUT_BLOCK_TYPE, input=InputSpec(whole_pool=True)),),
        wires=(),
    )


def with_block(workflow: "Workflow", workflow_block: "WorkflowBlock") -> "Workflow":
    return replace(workflow, blocks=workflow.blocks + (workflow_block,))


def with_wire(workflow: "Workflow", wire: "WorkflowWire") -> "Workflow":
    return replace(workflow, wires=workflow.wires + (wire,))


def with_block_replaced(workflow: "Workflow", block_id: str, **changes: Any) -> "Workflow":
    """Return a copy of `workflow` with `dataclasses.replace(block, **changes)`
    applied to the block of that id (e.g. `params=...` or `input=...`)."""
    blocks = tuple(
        replace(workflow_block, **changes) if workflow_block.block_id == block_id else workflow_block
        for workflow_block in workflow.blocks
    )
    return replace(workflow, blocks=blocks)


def without_block(workflow: "Workflow", block_id: str) -> "Workflow":
    """Drop a block and every wire touching it."""
    return replace(
        workflow,
        blocks=tuple(n for n in workflow.blocks if n.block_id != block_id),
        wires=tuple(e for e in workflow.wires
                    if e.from_block != block_id and e.to_block != block_id),
        layout={key: position for key, position in workflow.layout.items() if key != block_id},
    )
