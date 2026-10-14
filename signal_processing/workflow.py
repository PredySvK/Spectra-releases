# =====================================================================
# FILE: signal_processing/workflow.py
# =====================================================================
"""
The block-workflow engine: what a processing block is, the register of the ones
that exist, and the functions that validate and run a *graph* of them
(ARCHITECTURE_DECISIONS 1.6, Epic P phase 7A).

Pure and synchronous. numpy in, numpy out; no I/O, no Qt, no AppContext -- the
same rules as the rest of signal_processing/, so a graph can be tested with
analytic blocks and no disk. The runner that reads real measurements off disk,
resolves each input block to loaded blocks and drives this over a QtJobRunner sits
above, in gui/ (1.6, decision 2): an input block is resolved by the runner, never
here, because a block that reads a file would drag I/O into this layer.

The invariant that matters most (1.12): a block is an *adapter* over a function
in result_blocks.py, called with the same core/dsp_configs.py dataclass the
interactive docks use. It is never a second implementation of a spectrum. Two
DSP paths drifting apart by half a percent over six months is the worst bug this
tool can have.

A new block is one row in BLOCKS plus one thin adapter -- the same "data, not a
subclass tree" shape core/block_kinds.py uses for result kinds. The input model
is named ports rather than a needs_tacho flag: a tacho is not another block's
output, it is a raw channel of the input measurement, and modelling it as a port
is what the DAG here and a later canvas (phase 8) build on. A linear chain is
the degenerate case of the graph.

**Lineage (the finding that reshaped the model, plan 2026-09-02).** A block's
identity used to be its own params alone. In a graph that is ambiguous:
`spectrum(2048)` and `lowpass(500) -> spectrum(2048)` would hash the same and a
cache lookup would return the wrong numbers. So `lineage_hash` fingerprints the
whole subgraph *above* a block, and `result_params_from_block` folds it in. It
must stay empty when a block is fed only by input blocks, or every result set
saved before this change becomes a cache miss -- a test pins that.

All internal documentation strings and variable labels are standardly written
in English.
"""
import hashlib
import json
from dataclasses import MISSING, asdict, dataclass, fields, replace
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Set, Tuple, Union

from core.block_kinds import KIND_OVERALL_LEVEL, KIND_TIME_RESPONSE, spec_for as kind_spec_for
from core.data_block import NVHDataBlock
from core.dsp_configs import (
    DSP_ALGORITHM_VERSIONS, OrderTrackingConfig, OverallLevelConfig, SpectrogramConfig,
    SpectrumConfig,
)
from core.jobs import CancelToken
from core.workflow_graph import (
    INPUT_BLOCK_TYPE, InputSpec, PortBinding, SaveSpec, Workflow, WorkflowWire, WorkflowBlock,
    with_wire, with_block,
)
from signal_processing.result_blocks import (
    compute_order_cuts, compute_overall_level, compute_spectrogram, compute_spectrum,
    with_dc_removed,
)

BlockResult = Union[NVHDataBlock, List[NVHDataBlock]]
BlockFn = Callable[
    [NVHDataBlock, Mapping[str, NVHDataBlock], Mapping[str, Any], MutableMapping[str, Any]],
    BlockResult,
]

# `WorkflowWire.to_port` value that means "the block's primary input". Kept as a
# named constant so the empty-string convention is not spread as a literal.
PRIMARY_PORT = ""

# The input block id `workflow_from_configs` builds. A hand-authored graph (phase
# 7C) may name its input block anything; the ribbon fast path uses this one.
INPUT_BLOCK_ID = "input"


@dataclass(frozen=True)
class Port:
    """One block input and its accepted kinds or measurement source."""
    name: str
    accepts: Tuple[str, ...]
    optional: bool = False
    from_measurement: bool = False


@dataclass(frozen=True)
class BlockSpec:
    """
    What a block type is: its inputs, the kind it emits, the adapter that runs
    it, and the config dataclass its params mirror.

    `inputs[0]` is the primary port -- the runner wires it to the wire feeding
    the block's primary input (or, for a block fed by an input block, to the input
    measurement). Any further port is fed from an wire to that named port or, for
    a raw channel of the measurement, a `PortBinding` on the block.

    `multi_output` marks a block that emits a list (order tracking: one block
    per order). Nothing consumes a list, so such a block may not have an outgoing
    wire.

    `display_only_params` names fields of `config_cls` that change how a result
    is drawn but not what it contains -- a spectrogram's colour scale. They are
    stripped when a block is built, because a block's params become the result
    set's identity (`result_params_from_block` -> `params_hash`): leaving one in
    would make flipping a combo box in the ribbon compute a second, identical
    result set and turn the first into a cache miss. The list lives on the kind
    (`core.block_kinds.KindSpec`) so the cache's `shape_signature` and this
    authoring side read one register, not two that can drift (audit 02 / 7.5).
    """
    inputs: Tuple[Port, ...]
    produces: str
    fn: BlockFn
    config_cls: type
    multi_output: bool = False

    @property
    def display_only_params(self) -> Tuple[str, ...]:
        return kind_spec_for(self.produces).display_only_params

    @property
    def primary(self) -> Port:
        return self.inputs[0]

    @property
    def extra_ports(self) -> Tuple[Port, ...]:
        return self.inputs[1:]


@dataclass(frozen=True)
class NoConfig:
    """Params placeholder for a block that takes none (remove_dc)."""


# -- adapters --------------------------------------------------------------
# Each one unpacks the flat params dict onto its dataclass and calls the
# existing result_blocks function. Nothing here reimplements DSP.
#
# `scratch` is the per-measurement memo the runner hands in (see run_graph). An
# adapter that derives something from the *bound* channels rather than from its
# own primary input may keep it there; everything else ignores the argument.

def _remove_dc(primary: NVHDataBlock, bound: Mapping[str, NVHDataBlock],
               params: Mapping[str, Any], scratch: MutableMapping[str, Any]) -> NVHDataBlock:
    return with_dc_removed(primary)


def _spectrum(primary: NVHDataBlock, bound: Mapping[str, NVHDataBlock],
              params: Mapping[str, Any], scratch: MutableMapping[str, Any]) -> NVHDataBlock:
    return compute_spectrum(primary, SpectrumConfig(**params))


def _spectrogram(primary: NVHDataBlock, bound: Mapping[str, NVHDataBlock],
                 params: Mapping[str, Any], scratch: MutableMapping[str, Any]) -> NVHDataBlock:
    return compute_spectrogram(primary, bound.get("tacho"), SpectrogramConfig(**params),
                               scratch=scratch)


def _order_tracking(primary: NVHDataBlock, bound: Mapping[str, NVHDataBlock],
                    params: Mapping[str, Any],
                    scratch: MutableMapping[str, Any]) -> List[NVHDataBlock]:
    return compute_order_cuts(primary, bound["tacho"], OrderTrackingConfig(**params),
                              scratch=scratch)


def _overall_level(primary: NVHDataBlock, bound: Mapping[str, NVHDataBlock],
                   params: Mapping[str, Any], scratch: MutableMapping[str, Any]) -> NVHDataBlock:
    return compute_overall_level(primary, bound.get("tacho"), OverallLevelConfig(**params),
                                 scratch=scratch)


_TIME = (KIND_TIME_RESPONSE,)

BLOCKS: Mapping[str, BlockSpec] = {
    "remove_dc": BlockSpec(
        inputs=(Port("in", _TIME),), produces=KIND_TIME_RESPONSE,
        fn=_remove_dc, config_cls=NoConfig,
    ),
    "spectrum": BlockSpec(
        inputs=(Port("in", _TIME),), produces="spectrum",
        fn=_spectrum, config_cls=SpectrumConfig,
    ),
    "spectrogram": BlockSpec(
        inputs=(Port("in", _TIME), Port("tacho", _TIME, optional=True, from_measurement=True)),
        produces="spectrogram", fn=_spectrogram, config_cls=SpectrogramConfig,
    ),
    "order_tracking": BlockSpec(
        inputs=(Port("in", _TIME), Port("tacho", _TIME, from_measurement=True)),
        produces="order_cut", fn=_order_tracking, config_cls=OrderTrackingConfig,
        multi_output=True,
    ),
    "overall_level": BlockSpec(
        inputs=(Port("in", _TIME), Port("tacho", _TIME, optional=True, from_measurement=True)),
        produces=KIND_OVERALL_LEVEL, fn=_overall_level, config_cls=OverallLevelConfig,
    ),
}


def spec_for(block_type: str) -> BlockSpec:
    """The BlockSpec for `block_type`, or ValueError naming what is registered."""
    try:
        return BLOCKS[block_type]
    except KeyError:
        raise ValueError(
            f"Unknown block type '{block_type}'. Registered: {', '.join(sorted(BLOCKS))}. "
            f"A new block is one entry in signal_processing.workflow.BLOCKS plus one adapter."
        ) from None


def new_workflow_block(block_type: str, block_id: str,
                   params: Optional[Mapping[str, Any]] = None) -> WorkflowBlock:
    """
    A workflow block ready to drop into a graph (phase 7C "+ Add Block"): empty
    params -- the adapter fills them from the `config_cls` defaults, so adding a
    Spectrum block gives the standard FFT settings with no ribbon involved --
    the current `algorithm_version` stamped, and every non-primary port
    auto-bound to a same-named channel. The same block shape
    `workflow_from_configs` builds per step, minus the caller-supplied config.
    """
    spec = spec_for(block_type)
    bindings = {port.name: PortBinding(channel_type=port.name) for port in spec.extra_ports}
    return WorkflowBlock(
        block_id=block_id, block_type=block_type,
        params=resolve_block_params(block_type, params or {}), bindings=bindings,
        algorithm_version=authoring_version(block_type),
    )


def resolve_block_params(block_type: str, params: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep computation params only, without filling defaults or changing values."""
    display_only = spec_for(block_type).display_only_params
    return {key: value for key, value in params.items() if key not in display_only}


def build_workflow_with_block(workflow: Workflow, block_type: str,
                              source_id: Optional[str] = None) -> Tuple[Workflow, str]:
    """Append a block, wiring its primary port only to a compatible single output.

    Missing or unknown sources leave the block unconnected. Input blocks always
    start unconnected and select the whole pool. Returns the new workflow and
    the added block's id.
    """
    existing = set(workflow.block_ids)
    block_id = block_type
    index = 2
    while block_id in existing:
        block_id = f"{block_type}_{index}"
        index += 1
    if block_type == INPUT_BLOCK_TYPE:
        return with_block(workflow, WorkflowBlock(
            block_id, INPUT_BLOCK_TYPE, input=InputSpec(whole_pool=True),
        )), block_id
    workflow = with_block(workflow, new_workflow_block(block_type, block_id))
    if (source_id is not None and source_id in existing
            and not resolve_wire_refusal(workflow, source_id, block_id, spec_for(block_type).primary.name)):
        workflow = with_wire(workflow, WorkflowWire(source_id, block_id))
    return workflow, block_id


def authoring_version(block_type: str) -> Optional[int]:
    """
    The algorithm version to stamp on a block of this type when a workflow is
    authored -- looked up per result kind from `DSP_ALGORITHM_VERSIONS`. Every
    kind a block can produce has an entry today; a block whose kind has none
    stamps nothing.
    """
    return DSP_ALGORITHM_VERSIONS.get(spec_for(block_type).produces)


# -- graph shape ---------------------------------------------------------------

def resolve_wire_port(workflow: Workflow, wire: WorkflowWire) -> str:
    """The name of the port `wire` feeds. A stored wire names the primary port
    either "" (`PRIMARY_PORT`) or by its name; nothing outside this module needs
    to know that."""
    if wire.to_port != PRIMARY_PORT:
        return wire.to_port
    spec = BLOCKS.get(workflow.block(wire.to_block).block_type)
    return spec.primary.name if spec is not None else wire.to_port


def _stored_port(workflow: Workflow, block_id: str, port_name: str) -> str:
    """How a wire into `port_name` is stored: the primary port as `PRIMARY_PORT`."""
    spec = BLOCKS.get(workflow.block(block_id).block_type)
    return PRIMARY_PORT if spec is not None and port_name == spec.primary.name else port_name


def build_workflow_without_wire(workflow: Workflow, block_id: str, port_name: str) -> Workflow:
    """Drop whatever wire feeds `port_name` of `block_id`; unchanged (the same
    object) when nothing does."""
    wires = tuple(wire for wire in workflow.wires if wire.to_block != block_id
                  or resolve_wire_port(workflow, wire) != port_name)
    return workflow if len(wires) == len(workflow.wires) else replace(workflow, wires=wires)


def build_workflow_with_wire(workflow: Workflow, source_id: str, block_id: str,
                             port_name: str) -> Workflow:
    """Wire `source_id` into `port_name` of `block_id`, replacing what fed it.
    Unchecked -- ask `resolve_wire_refusal` first."""
    wire = WorkflowWire(source_id, block_id, _stored_port(workflow, block_id, port_name))
    return with_wire(build_workflow_without_wire(workflow, block_id, port_name), wire)


def _incoming_on_port(workflow: Workflow, block_id: str, port: str) -> Optional[WorkflowWire]:
    """The one wire feeding `port` of `block_id`, or None. `validate_graph`
    guarantees at most one; unvalidated, the first wins."""
    for wire in workflow.incoming(block_id):
        if resolve_wire_port(workflow, wire) == port:
            return wire
    return None


def topological_order(workflow: Workflow) -> List[str]:
    """
    Block ids in an order where every block comes after everything that feeds it.

    Raises ValueError naming a block on the cycle if the graph is not acyclic --
    a graph editor can wire a loop, and running one would spin forever.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: Dict[str, int] = {block_id: WHITE for block_id in workflow.block_ids}
    order: List[str] = []

    def visit(block_id: str) -> None:
        colour[block_id] = GRAY
        for wire in workflow.outgoing(block_id):
            nxt = wire.to_block
            if colour[nxt] == GRAY:
                raise ValueError(f"Workflow has a cycle through block '{nxt}'.")
            if colour[nxt] == WHITE:
                visit(nxt)
        colour[block_id] = BLACK
        order.append(block_id)

    for block_id in workflow.block_ids:
        if colour[block_id] == WHITE:
            visit(block_id)
    order.reverse()
    return order


def terminal_block_ids(workflow: Workflow) -> Tuple[str, ...]:
    """
    Non-input blocks with no outgoing wire. The runner persists `save_block_ids`,
    not these (7B); `terminal_block_ids` stays for `default_result_set_label` and
    the ribbon duplicate check, which reason about the single-block fast path
    where the sole terminal is the sole save block.
    """
    return tuple(
        workflow_block.block_id for workflow_block in workflow.blocks
        if not workflow_block.is_input and not workflow.outgoing(workflow_block.block_id)
    )


def save_block_ids(workflow: Workflow) -> Tuple[str, ...]:
    """
    The blocks whose output is written to disk -- those carrying a `SaveSpec`
    (decision 4). A branching graph can mark several; the ribbon fast path marks
    exactly one (its terminal, stamped by `workflow_from_configs`). Saving is
    opt-in per block, so a graph with none marked writes nothing, and the runner
    refuses it rather than guessing.
    """
    return tuple(workflow_block.block_id for workflow_block in workflow.blocks if workflow_block.save is not None)


def sole_input_block_id(workflow: Workflow) -> str:
    """The single input block's id, for the runner's one-input fast path. Raises
    if the graph has none or several -- 7A does not run a multi-input graph."""
    inputs = [workflow_block.block_id for workflow_block in workflow.blocks if workflow_block.is_input]
    if len(inputs) != 1:
        raise ValueError(
            f"Expected exactly one input block, found {len(inputs)}: {', '.join(inputs) or '(none)'}."
        )
    return inputs[0]


def sole_terminal_block(workflow: Workflow) -> WorkflowBlock:
    """The single terminal block, for the runner's one-output fast path (7A)."""
    terminals = terminal_block_ids(workflow)
    if len(terminals) != 1:
        raise ValueError(
            f"Expected exactly one terminal block, found {len(terminals)}: "
            f"{', '.join(terminals) or '(none)'}."
        )
    return workflow.block(terminals[0])


def needed_block_ids(workflow: Workflow, roots: Optional[Set[str]] = None) -> Set[str]:
    """
    The blocks a run actually has to compute, plus everything upstream of those.

    `roots` overrides the default outputs -- the runner passes a save block's id
    fewer than `save_block_ids(workflow)` when a save block's ancestry needs a
    channel type this measurement does not have (a file with no tacho feeding a
    branch that saves an order cut): the blocked block is left out of `roots`
    rather than raising, so a sibling branch that never touches that channel
    still runs (#331). `roots=None` keeps the default: the blocks marked to
    save, or the terminal blocks when none are (the 7A ribbon fast path). Either
    way a branch that leads only to a dead, unsaved terminal is not run.
    """
    if roots is None:
        roots = {workflow_block.block_id for workflow_block in workflow.blocks if workflow_block.save is not None}
        if not roots:
            roots = set(terminal_block_ids(workflow))

    needed: Set[str] = set()
    stack = list(roots)
    while stack:
        block_id = stack.pop()
        if block_id in needed:
            continue
        needed.add(block_id)
        for wire in workflow.incoming(block_id):
            stack.append(wire.from_block)
    return needed


# -- validation --------------------------------------------------------------

def validate_graph(workflow: Workflow) -> None:
    """
    Raises ValueError unless the graph type-checks end to end -- rejected before
    a batch runs over forty files, the way Testlab refuses an incompatible
    connection rather than failing mid-run.

    Checks: at least one block and at least one input block; the graph is acyclic;
    no port is wired twice; an input block has no incoming wire and no `SaveSpec`;
    every non-input block type is registered; each block's primary port is fed;
    every mandatory extra port is fed by a wire or a binding, and no binding names
    a port the block does not have; a port is not both wired and bound; every wire
    passes `resolve_wire_refusal`; a multi-output block has no outgoing wire.
    """
    if workflow.blocks and not any(block.is_input for block in workflow.blocks):
        raise ValueError("A workflow needs at least one input block.")
    errors = resolve_block_errors(workflow)
    if errors:
        raise ValueError(next(iter(errors.values())))


def resolve_block_errors(workflow: Workflow) -> Dict[str, str]:
    """
    Every block's first `validate_graph` error, keyed by block id in the order
    `validate_graph` reports them -- so the canvas can outline each faulty block,
    not just the first. Graph-wide failures (no block, a cycle) belong to no single
    block and still raise ValueError. A missing input block is `validate_graph`'s
    to refuse: a chain without one still has blocks worth naming (the unwired ones).
    """
    if not workflow.blocks:
        raise ValueError("A workflow needs at least one block.")

    topological_order(workflow)   # raises on a cycle

    errors: Dict[str, str] = {}
    wired: Set[Tuple[str, str]] = set()
    for wire in workflow.wires:
        key = (wire.to_block, resolve_wire_port(workflow, wire))
        if key in wired:
            errors.setdefault(
                wire.to_block, f"Block '{wire.to_block}' has its '{key[1]}' port wired more than once."
            )
        wired.add(key)

    for workflow_block in workflow.blocks:
        try:
            _validate_block(workflow, workflow_block)
        except ValueError as exc:
            errors.setdefault(workflow_block.block_id, str(exc))
    return errors


def _validate_block(workflow: Workflow, workflow_block: WorkflowBlock) -> None:
    """Type-check one block's inputs. Split out of `validate_graph` only for
    readability -- the graph-wide checks (cycle, double-wired port) stay there."""
    incoming = workflow.incoming(workflow_block.block_id)

    if workflow_block.is_input:
        if incoming:
            raise ValueError(f"Input block '{workflow_block.block_id}' cannot have an incoming wire.")
        if workflow_block.save is not None:
            # An input block stands for the raw measurement, not a computed
            # result. Letting it carry a SaveSpec would reach spec_for("input")
            # in the runner and surface as a baffling "Unknown block type
            # 'input'" after the drafts are already open -- catch it here.
            raise ValueError(
                f"Input block '{workflow_block.block_id}' cannot be marked to save -- tick "
                f"'Save this block's output' on a block instead."
            )
        return

    spec = spec_for(workflow_block.block_type)
    port_names = {port.name for port in spec.inputs}

    if _incoming_on_port(workflow, workflow_block.block_id, spec.primary.name) is None:
        raise ValueError(
            f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') has nothing wired to its "
            f"primary input."
        )
    for name in workflow_block.bindings:
        if name == spec.primary.name:
            # A binding here would be silently ignored at run time -- run_graph
            # resolves bindings on `spec.extra_ports` only -- while the runner's
            # _required_channel_types still counted its type as mandatory, so
            # every file lacking that channel failed for a graph that never
            # needed it (audit 02, finding S1/1.8).
            raise ValueError(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') binds its primary port "
                f"'{name}' to a channel. The primary input is fed by a wire -- wire it "
                f"from another block instead."
            )
        if name not in port_names:
            raise ValueError(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') binds a port '{name}' it "
                f"does not have. Its ports: {', '.join(sorted(port_names))}."
            )

    for port in spec.extra_ports:
        port_wire = _incoming_on_port(workflow, workflow_block.block_id, port.name)
        has_binding = port.name in workflow_block.bindings
        if port_wire is not None and has_binding:
            raise ValueError(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') has its '{port.name}' port "
                f"both wired and bound to a channel -- pick one."
            )
        if port_wire is None and not has_binding and not port.optional:
            raise ValueError(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') needs its '{port.name}' port "
                f"bound to a channel (e.g. PortBinding(channel_type='{port.name}'))."
            )
    for wire in incoming:
        refusal = resolve_wire_refusal(workflow, wire.from_block, workflow_block.block_id,
                                       resolve_wire_port(workflow, wire))
        if refusal:
            raise ValueError(refusal)
    if workflow.outgoing(workflow_block.block_id):
        refusal = _resolve_multi_output_refusal(workflow_block)
        if refusal:
            raise ValueError(refusal)


def _resolve_multi_output_refusal(workflow_block: WorkflowBlock) -> str:
    if not workflow_block.is_input and spec_for(workflow_block.block_type).multi_output:
        return (f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') emits one block "
                f"per order; nothing can consume that, so it cannot have an outgoing wire.")
    return ""


def resolve_wire_refusal(workflow: Workflow, source_id: str, block_id: str, port_name: str) -> str:
    """
    Why a wire from `source_id` into `port_name` of `block_id` is not allowed,
    or "" when it is. The one wire rule: graph validation, wiring a newly added
    block and the canvas wire gesture all ask it.

    Checked as if the wire were added: it must not close a cycle. Whether the
    port already holds a wire is not this rule's business -- a gesture replaces
    it, validation reports it.
    """
    if source_id not in workflow.block_ids or block_id not in workflow.block_ids:
        return "Wire endpoint no longer exists."
    target = workflow.block(block_id)
    if target.is_input:
        return f"Input block '{block_id}' cannot have an incoming wire."
    source = workflow.block(source_id)
    try:
        spec = spec_for(target.block_type)
        refusal = _resolve_multi_output_refusal(source)
    except ValueError as exc:
        return str(exc)
    label = f"Block '{block_id}' ('{target.block_type}')"
    port = next((port for port in spec.inputs if port.name == port_name), None)
    if port is None:
        return (f"{label} has a wire to a port '{port_name}' it does not have. "
                f"Its ports: {', '.join(sorted(p.name for p in spec.inputs))}.")
    if port.from_measurement:
        # #596: a measurement port takes its channel from a binding, not a wire (yet).
        return (f"{label} takes its '{port_name}' port from the measurement -- "
                f"choose its channel in block Properties.")
    if refusal:
        return refusal
    kind = KIND_TIME_RESPONSE if source.is_input else spec_for(source.block_type).produces
    if kind not in port.accepts:
        port_label = "primary input" if port == spec.primary else f"'{port_name}' port"
        return (f"{label} accepts {' or '.join(port.accepts)} on its {port_label}, "
                f"but '{source_id}' produces '{kind}'.")
    if block_id in needed_block_ids(workflow, {source_id}):
        return f"Workflow has a cycle through block '{block_id}'."
    return ""


def check_versions(workflow: Workflow) -> List[str]:
    """
    Human-readable warnings where a block's recorded `algorithm_version` differs
    from the one in force now. Never recomputes silently (1.12 pitfall 5) -- the
    caller decides what to do with these.
    """
    warnings: List[str] = []
    for workflow_block in workflow.blocks:
        if workflow_block.is_input:
            continue
        current = authoring_version(workflow_block.block_type)
        if current is None:
            continue
        if workflow_block.algorithm_version is None:
            warnings.append(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}'): workflow records no algorithm "
                f"version; current is {current}."
            )
        elif workflow_block.algorithm_version != current:
            warnings.append(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}'): workflow was authored with "
                f"algorithm version {workflow_block.algorithm_version}, current is {current} -- "
                f"results will differ."
            )
    return warnings


# -- running ----------------------------------------------------------------

def _resolve_extra_ports(workflow: Workflow, workflow_block: WorkflowBlock, spec: BlockSpec,
                         single: Mapping[str, NVHDataBlock],
                         bound_channels: Mapping[str, NVHDataBlock]) -> Dict[str, NVHDataBlock]:
    """The non-primary ports of `block`, each fed from its incoming wire or its
    `PortBinding`. An optional port with neither is left out; a mandatory one
    raises. Split out of `run_graph` for readability only."""
    bound: Dict[str, NVHDataBlock] = {}
    for port in spec.extra_ports:
        port_wire = _incoming_on_port(workflow, workflow_block.block_id, port.name)
        if port_wire is not None:
            bound[port.name] = single[port_wire.from_block]
            continue
        binding = workflow_block.bindings.get(port.name)
        if binding is None:
            if port.optional:
                continue
            raise ValueError(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') needs its '{port.name}' port bound."
            )
        channel = bound_channels.get(binding.channel_type)
        if channel is None:
            if port.optional:
                continue
            raise ValueError(
                f"Block '{workflow_block.block_id}' ('{workflow_block.block_type}') needs a '{binding.channel_type}' "
                f"channel, none was provided for this measurement."
            )
        bound[port.name] = channel
    return bound


def run_graph(workflow: Workflow, inputs: Mapping[str, NVHDataBlock],
              bound_channels: Optional[Mapping[str, NVHDataBlock]] = None,
              cancel: Optional[CancelToken] = None,
              scratch: Optional[MutableMapping[str, Any]] = None,
              roots: Optional[Set[str]] = None,
              ) -> Dict[str, List[NVHDataBlock]]:
    """
    Run `workflow` over one set of loaded input blocks. Assumes `validate_graph`
    has already passed.

    `inputs` maps each input block's id to the block that stands for it -- one
    channel of one measurement, resolved by the runner (decision 2). This layer
    never reads a file. `bound_channels` maps a channel type ("tacho") to the
    block for it, resolved once per measurement by the caller.

    `roots` overrides which save/terminal blocks this call computes -- see
    `needed_block_ids`. The caller uses it to leave out a branch whose mandatory
    bound channel this measurement does not have, instead of this call raising
    and losing every branch's output for the file (#331).

    `scratch` is a mutable bag with the same lifetime as `bound_channels`: one
    measurement, reused across that measurement's channels. It exists because a
    graph is run once per (file, channel), so anything derived purely from the
    *bound* channels would otherwise be re-derived for every channel of the file
    -- order tracking's and the spectrogram's `TrackingPlan` is placed from the
    tacho and the sweep settings and never from the vibration channel, and
    rebuilding it per channel measured 0.09 s of waste per channel on the real
    75 s run-up. Both blocks key their plan by tracking mode as well as sweep
    settings, so an order cut and an rpm-tracked spectrogram at the same step
    share one plan while a time-tracked one at the same step keeps its own
    (ADR §1.58 point 6). The caller owns the bag, so this stays deterministic
    and thread-safe: no module-level cache, and each worker's measurement gets
    its own. Omitted (tests, a headless entry point) it degrades to a
    fresh empty bag per call, i.e. no reuse.

    Returns `{block_id: [blocks]}` for every non-input block that had to run: the
    terminal blocks, the blocks marked to save, and everything between. One block
    for a spectrum or spectrogram, N for order cuts. A branch nobody consumes is
    not computed.
    """
    bound_channels = bound_channels or {}
    scratch = {} if scratch is None else scratch
    needed = needed_block_ids(workflow, roots)

    single: Dict[str, NVHDataBlock] = {}         # single-output block, by block id
    produced: Dict[str, List[NVHDataBlock]] = {}

    for block_id in topological_order(workflow):
        if block_id not in needed:
            continue
        workflow_block = workflow.block(block_id)

        if workflow_block.is_input:
            block = inputs.get(block_id)
            if block is None:
                raise ValueError(
                    f"Input block '{block_id}' was given no loaded measurement block."
                )
            single[block_id] = block
            continue

        if cancel is not None:
            cancel.raise_if_cancelled()

        spec = spec_for(workflow_block.block_type)

        primary_wire = _incoming_on_port(workflow, block_id, spec.primary.name)
        if primary_wire is None or primary_wire.from_block not in single:
            raise ValueError(
                f"Block '{block_id}' ('{workflow_block.block_type}') has no usable primary input; "
                f"validate_graph should have refused this workflow."
            )
        primary_block = single[primary_wire.from_block]

        bound = _resolve_extra_ports(workflow, workflow_block, spec, single, bound_channels)

        result = spec.fn(primary_block, bound, dict(workflow_block.params), scratch)

        if isinstance(result, list):
            if not spec.multi_output:
                raise ValueError(
                    f"Block '{block_id}' ('{workflow_block.block_type}') produced a list but is not "
                    f"multi_output; validate_graph should have refused this workflow."
                )
            produced[block_id] = list(result)
        else:
            single[block_id] = result
            produced[block_id] = [result]

    return {block_id: blocks for block_id, blocks in produced.items()}


# -- identity / lineage -----------------------------------------------------

def _config_defaults(config_cls: type) -> Dict[str, Any]:
    """Every field of a block's config dataclass at its default value."""
    out: Dict[str, Any] = {}
    for f in fields(config_cls):
        if f.default is not MISSING:
            out[f.name] = f.default
        elif f.default_factory is not MISSING:  # type: ignore[misc]
            out[f.name] = f.default_factory()  # type: ignore[misc]
    return out


def identity_params(workflow_block: WorkflowBlock) -> Dict[str, Any]:
    """
    A block's params as they count for identity: display-only fields dropped,
    every remaining field pinned to an explicit value, the algorithm version
    stamped. The same rule `result_params_from_block` uses, minus the lineage key
    it adds on top.

    Missing keys are backfilled from the `config_cls` defaults so a block that
    was dropped but never "Apply"-ed (empty `params`, audit 02 finding 2.11) and
    one the ribbon wrote in full (`asdict(config)`) hash identically -- otherwise
    the same computation authored two ways is two result sets, neither a cache
    hit for the other.
    """
    spec = spec_for(workflow_block.block_type)
    params = resolve_block_params(workflow_block.block_type, {
        **_config_defaults(spec.config_cls), **workflow_block.params,
    })
    version = workflow_block.algorithm_version
    if version is None:
        # A block authored before its kind was versioned, or before this backfill
        # existed: stamp the kind's current version so it hashes the same as a
        # freshly authored one rather than becoming its own result set.
        version = authoring_version(workflow_block.block_type)
    params["algorithm_version"] = version
    return params


def _identity_port(workflow: Workflow, wire: WorkflowWire) -> str:
    """The port as identity sees it: `PRIMARY_PORT` for the primary port however
    the wire names it, so already-saved result sets keep their hash."""
    return _stored_port(workflow, wire.to_block, resolve_wire_port(workflow, wire))


def _ancestor_repr(workflow: Workflow, block_id: str, seen: Set[str]) -> Any:
    """
    A canonical, block-id-independent description of the subgraph rooted at
    `block_id`, seen from below. Input blocks collapse to a marker -- their
    `MeasurementSelection` name must not enter the fingerprint (running the same
    DSP over a different folder is the same result set: the duplicate dialog
    still has to appear).
    """
    workflow_block = workflow.block(block_id)
    if workflow_block.is_input:
        return {"input": True}
    if block_id in seen:                      # defensive: validate_graph rejects cycles
        return {"cycle": block_id}
    seen = seen | {block_id}
    return {
        "block": workflow_block.block_type,
        "params": identity_params(workflow_block),
        "bindings": sorted((port, binding.channel_type)
                           for port, binding in workflow_block.bindings.items()),
        "inputs": sorted(
            [_identity_port(workflow, wire), _ancestor_repr(workflow, wire.from_block, seen)]
            for wire in workflow.incoming(block_id)
        ),
    }


def lineage_hash(workflow: Workflow, block_id: str) -> str:
    """
    A fingerprint of the whole subgraph *above* `block_id` (its own params
    excluded). Empty string when every incoming wire comes straight from an
    input block: a one-block graph then has the exact identity today's single
    step has, so no already-saved result set turns into a cache miss.
    """
    incoming = workflow.incoming(block_id)
    if incoming and all(workflow.block(wire.from_block).is_input for wire in incoming):
        return ""
    if not incoming:
        return ""
    structure = sorted(
        [_identity_port(workflow, wire), _ancestor_repr(workflow, wire.from_block, {block_id})]
        for wire in incoming
    )
    canonical = json.dumps(structure, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


# -- building from ribbon configs -----------------------------------------------

def workflow_from_configs(name: str, steps: List[Tuple[str, Any]], *,
                          selection_name: str = "",
                          save: Optional[SaveSpec] = None) -> Workflow:
    """
    Build a linear workflow -- `input -> block -> block -> ...` -- from
    `(block_type, config)` pairs, stamping each block with the current
    `algorithm_version`, dropping the block's `display_only_params`, and
    auto-adding a same-named binding for every non-primary port.

    The last block is marked to save: `save` when the caller passes a `SaveSpec`
    (the ribbon fast path, carrying its channel scope), otherwise a default
    all-channels one. `workflow_from_configs` only ever builds a graph that is
    meant to run and persist, so "save = a block carries a SaveSpec" stays the
    single rule with no implicit fallback in the runner (decision 4 / plan
    2026-09-02 answer B).

    This is the one place a workflow is built from ribbon configs -- the ribbon's
    quick "Compute Result Set..." path is a throwaway two-block graph built here,
    not a second model (plan 2026-09-02). The step picker (phase 7C) will call it
    too, so version stamping and binding cannot drift between the two.

    Optional ports are bound too, not only mandatory ones. A spectrogram's tacho
    is optional because a time-mode waterfall does not need one -- but an
    rpm-tracked one does, and an unbound port would never even be looked for.
    The runner tells the two cases apart: a bound optional channel is used when
    the measurement has it and skipped when it does not.

    `selection_name` is written onto the input block so a workflow that gets
    saved (7B/7C) records what it ran over. The ribbon fast path leaves it blank
    and passes the selection to the runner separately, as it does today.
    """
    blocks: List[WorkflowBlock] = [WorkflowBlock(
        INPUT_BLOCK_ID, INPUT_BLOCK_TYPE, input=InputSpec(selection_name=selection_name),
    )]
    wires: List[WorkflowWire] = []

    upstream = INPUT_BLOCK_ID
    used_ids: List[str] = []
    for index, (block_type, config) in enumerate(steps):
        takes_params = config is not None and not isinstance(config, NoConfig)
        params = asdict(config) if takes_params else {}
        block_id = block_type if block_type not in used_ids and block_type != INPUT_BLOCK_ID \
            else f"{block_type}_{index}"
        used_ids.append(block_id)
        is_last = index == len(steps) - 1
        blocks.append(replace(
            new_workflow_block(block_type, block_id, params),
            save=(save if save is not None else SaveSpec()) if is_last else None,
        ))
        wires.append(WorkflowWire(upstream, block_id))
        upstream = block_id

    return Workflow(name=name, blocks=tuple(blocks), wires=tuple(wires))
