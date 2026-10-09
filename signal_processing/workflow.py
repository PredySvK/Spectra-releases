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
resolves each input node to loaded blocks and drives this over a QtJobRunner sits
above, in gui/ (1.6, decision 2): an input node is resolved by the runner, never
here, because a block that reads a file would drag I/O into this layer.

The invariant that matters most (1.12): a block is an *adapter* over a function
in result_blocks.py, called with the same core/dsp_configs.py dataclass the
interactive docks use. It is never a second implementation of a spectrum. Two
DSP paths drifting apart by half a percent over six months is the worst bug this
tool can have.

A new block is one row in BLOCKS plus one thin adapter -- the same "data, not a
subclass tree" shape core/block_kinds.py uses for result kinds. The input model
is named ports rather than a needs_tacho flag: a tacho is not another node's
output, it is a raw channel of the input measurement, and modelling it as a port
is what the DAG here and a later canvas (phase 8) build on. A linear chain is
the degenerate case of the graph.

**Lineage (the finding that reshaped the model, plan 2026-09-02).** A node's
identity used to be its own params alone. In a graph that is ambiguous:
`spectrum(2048)` and `lowpass(500) -> spectrum(2048)` would hash the same and a
cache lookup would return the wrong numbers. So `lineage_hash` fingerprints the
whole subgraph *above* a node, and `result_params_from_node` folds it in. It
must stay empty when a node is fed only by input nodes, or every result set
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
    INPUT_BLOCK_TYPE, InputSpec, PortBinding, SaveSpec, Workflow, WorkflowEdge, WorkflowNode,
    with_edge, with_node,
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

# `WorkflowEdge.to_port` value that means "the block's primary input". Kept as a
# named constant so the empty-string convention is not spread as a literal.
PRIMARY_PORT = ""

# The input node id `workflow_from_configs` builds. A hand-authored graph (phase
# 7C) may name its input node anything; the ribbon fast path uses this one.
INPUT_NODE_ID = "input"


@dataclass(frozen=True)
class Port:
    """One input of a block. `accepts` lists the block kinds that may feed it."""
    name: str
    accepts: Tuple[str, ...]
    optional: bool = False


@dataclass(frozen=True)
class BlockSpec:
    """
    What a block type is: its inputs, the kind it emits, the adapter that runs
    it, and the config dataclass its params mirror.

    `inputs[0]` is the primary port -- the runner wires it to the edge feeding
    the node's primary input (or, for a node fed by an input node, to the input
    measurement). Any further port is fed from an edge to that named port or, for
    a raw channel of the measurement, a `PortBinding` on the node.

    `multi_output` marks a block that emits a list (order tracking: one block
    per order). Nothing consumes a list, so such a node may not have an outgoing
    edge.

    `display_only_params` names fields of `config_cls` that change how a result
    is drawn but not what it contains -- a spectrogram's colour scale. They are
    stripped when a node is built, because a node's params become the result
    set's identity (`result_params_from_node` -> `params_hash`): leaving one in
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
        inputs=(Port("in", _TIME), Port("tacho", _TIME, optional=True)),
        produces="spectrogram", fn=_spectrogram, config_cls=SpectrogramConfig,
    ),
    "order_tracking": BlockSpec(
        inputs=(Port("in", _TIME), Port("tacho", _TIME)),
        produces="order_cut", fn=_order_tracking, config_cls=OrderTrackingConfig,
        multi_output=True,
    ),
    "overall_level": BlockSpec(
        inputs=(Port("in", _TIME), Port("tacho", _TIME, optional=True)),
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


def new_block_node(block_type: str, node_id: str,
                   params: Optional[Mapping[str, Any]] = None) -> WorkflowNode:
    """
    A block node ready to drop into a graph (phase 7C "+ Add Block"): empty
    params -- the adapter fills them from the `config_cls` defaults, so adding a
    Spectrum block gives the standard FFT settings with no ribbon involved --
    the current `algorithm_version` stamped, and every non-primary port
    auto-bound to a same-named channel. The same node shape
    `workflow_from_configs` builds per step, minus the caller-supplied config.
    """
    spec = spec_for(block_type)
    bindings = {port.name: PortBinding(channel_type=port.name) for port in spec.extra_ports}
    return WorkflowNode(
        node_id=node_id, block_type=block_type,
        params=resolve_block_params(block_type, params or {}), bindings=bindings,
        algorithm_version=authoring_version(block_type),
    )


def resolve_block_params(block_type: str, params: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep computation params only, without filling defaults or changing values."""
    display_only = spec_for(block_type).display_only_params
    return {key: value for key, value in params.items() if key not in display_only}


def build_workflow_with_block(workflow: Workflow, block_type: str,
                              source_id: Optional[str] = None) -> Tuple[Workflow, str]:
    """Append a node, wiring its primary port only to a compatible single output.

    Missing or unknown sources leave the node unconnected. Input nodes always
    start unconnected and select the whole pool. Returns the new workflow and
    the added node's id.
    """
    existing = set(workflow.node_ids)
    node_id = block_type
    index = 2
    while node_id in existing:
        node_id = f"{block_type}_{index}"
        index += 1
    if block_type == INPUT_BLOCK_TYPE:
        return with_node(workflow, WorkflowNode(
            node_id, INPUT_BLOCK_TYPE, input=InputSpec(whole_pool=True),
        )), node_id
    node = new_block_node(block_type, node_id)
    workflow = with_node(workflow, node)
    if source_id is not None and source_id in existing:
        try:
            _validate_port_source(workflow, source_id, node, spec_for(block_type).primary,
                                  KIND_TIME_RESPONSE)
        except ValueError:
            pass
        else:
            workflow = with_edge(workflow, WorkflowEdge(source_id, node_id))
    return workflow, node_id


def authoring_version(block_type: str) -> Optional[int]:
    """
    The algorithm version to stamp on a node of this type when a workflow is
    authored -- looked up per result kind from `DSP_ALGORITHM_VERSIONS`. Every
    kind a block can produce has an entry today; a block whose kind has none
    stamps nothing.
    """
    return DSP_ALGORITHM_VERSIONS.get(spec_for(block_type).produces)


# -- graph shape ---------------------------------------------------------------

def _incoming_on_port(workflow: Workflow, node_id: str, port: str) -> Optional[WorkflowEdge]:
    """The one edge feeding `port` of `node_id`, or None. `validate_graph`
    guarantees at most one; unvalidated, the first wins."""
    for edge in workflow.incoming(node_id):
        if edge.to_port == port:
            return edge
    return None


def topological_order(workflow: Workflow) -> List[str]:
    """
    Node ids in an order where every node comes after everything that feeds it.

    Raises ValueError naming a node on the cycle if the graph is not acyclic --
    a graph editor can wire a loop, and running one would spin forever.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: Dict[str, int] = {node_id: WHITE for node_id in workflow.node_ids}
    order: List[str] = []

    def visit(node_id: str) -> None:
        colour[node_id] = GRAY
        for edge in workflow.outgoing(node_id):
            nxt = edge.to_node
            if colour[nxt] == GRAY:
                raise ValueError(f"Workflow has a cycle through node '{nxt}'.")
            if colour[nxt] == WHITE:
                visit(nxt)
        colour[node_id] = BLACK
        order.append(node_id)

    for node_id in workflow.node_ids:
        if colour[node_id] == WHITE:
            visit(node_id)
    order.reverse()
    return order


def terminal_node_ids(workflow: Workflow) -> Tuple[str, ...]:
    """
    Non-input nodes with no outgoing edge. The runner persists `save_node_ids`,
    not these (7B); `terminal_node_ids` stays for `default_result_set_label` and
    the ribbon duplicate check, which reason about the single-node fast path
    where the sole terminal is the sole save node.
    """
    return tuple(
        node.node_id for node in workflow.nodes
        if not node.is_input and not workflow.outgoing(node.node_id)
    )


def save_node_ids(workflow: Workflow) -> Tuple[str, ...]:
    """
    The nodes whose output is written to disk -- those carrying a `SaveSpec`
    (decision 4). A branching graph can mark several; the ribbon fast path marks
    exactly one (its terminal, stamped by `workflow_from_configs`). Saving is
    opt-in per node, so a graph with none marked writes nothing, and the runner
    refuses it rather than guessing.
    """
    return tuple(node.node_id for node in workflow.nodes if node.save is not None)


def sole_input_node_id(workflow: Workflow) -> str:
    """The single input node's id, for the runner's one-input fast path. Raises
    if the graph has none or several -- 7A does not run a multi-input graph."""
    inputs = [node.node_id for node in workflow.nodes if node.is_input]
    if len(inputs) != 1:
        raise ValueError(
            f"Expected exactly one input node, found {len(inputs)}: {', '.join(inputs) or '(none)'}."
        )
    return inputs[0]


def sole_terminal_node(workflow: Workflow) -> WorkflowNode:
    """The single terminal node, for the runner's one-output fast path (7A)."""
    terminals = terminal_node_ids(workflow)
    if len(terminals) != 1:
        raise ValueError(
            f"Expected exactly one terminal node, found {len(terminals)}: "
            f"{', '.join(terminals) or '(none)'}."
        )
    return workflow.node(terminals[0])


def needed_node_ids(workflow: Workflow, roots: Optional[Set[str]] = None) -> Set[str]:
    """
    The nodes a run actually has to compute, plus everything upstream of those.

    `roots` overrides the default outputs -- the runner passes a save node's id
    fewer than `save_node_ids(workflow)` when a save node's ancestry needs a
    channel type this measurement does not have (a file with no tacho feeding a
    branch that saves an order cut): the blocked node is left out of `roots`
    rather than raising, so a sibling branch that never touches that channel
    still runs (#331). `roots=None` keeps the default: the nodes marked to
    save, or the terminal nodes when none are (the 7A ribbon fast path). Either
    way a branch that leads only to a dead, unsaved terminal is not run.
    """
    if roots is None:
        roots = {node.node_id for node in workflow.nodes if node.save is not None}
        if not roots:
            roots = set(terminal_node_ids(workflow))

    needed: Set[str] = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in needed:
            continue
        needed.add(node_id)
        for edge in workflow.incoming(node_id):
            stack.append(edge.from_node)
    return needed


# -- validation --------------------------------------------------------------

def validate_graph(workflow: Workflow, primary_kind: str = KIND_TIME_RESPONSE) -> None:
    """
    Raises ValueError unless the graph type-checks end to end -- rejected before
    a batch runs over forty files, the way Testlab refuses an incompatible
    connection rather than failing mid-run.

    Checks: at least one node and at least one input node; the graph is acyclic;
    no port is wired twice; an input node has no incoming edge and no `SaveSpec`;
    every non-input block type is registered; each node's primary port is fed and
    accepts what the source produces; every mandatory extra port is fed by an
    edge or a binding, and no edge/binding names a port the block does not have;
    a port is not both wired and bound; a multi-output node has no outgoing edge.
    """
    if not workflow.nodes:
        raise ValueError("A workflow needs at least one node.")
    if not any(node.is_input for node in workflow.nodes):
        raise ValueError("A workflow needs at least one input node.")

    topological_order(workflow)   # raises on a cycle

    wired: Set[Tuple[str, str]] = set()
    for edge in workflow.edges:
        key = (edge.to_node, edge.to_port)
        if key in wired:
            port_label = edge.to_port or "primary"
            raise ValueError(
                f"Node '{edge.to_node}' has its {port_label} port wired more than once."
            )
        wired.add(key)

    for node in workflow.nodes:
        _validate_node(workflow, node, primary_kind)


def _validate_node(workflow: Workflow, node: WorkflowNode, primary_kind: str) -> None:
    """Type-check one node's inputs. Split out of `validate_graph` only for
    readability -- the graph-wide checks (cycle, double-wired port) stay there."""
    incoming = workflow.incoming(node.node_id)

    if node.is_input:
        if incoming:
            raise ValueError(f"Input node '{node.node_id}' cannot have an incoming edge.")
        if node.save is not None:
            # An input node stands for the raw measurement, not a computed
            # result. Letting it carry a SaveSpec would reach spec_for("input")
            # in the runner and surface as a baffling "Unknown block type
            # 'input'" after the drafts are already open -- catch it here.
            raise ValueError(
                f"Input node '{node.node_id}' cannot be marked to save -- tick "
                f"'Save this node's output' on a block instead."
            )
        return

    spec = spec_for(node.block_type)
    port_names = {port.name for port in spec.inputs}

    primary_edge = _incoming_on_port(workflow, node.node_id, PRIMARY_PORT)
    if primary_edge is None:
        raise ValueError(
            f"Node '{node.node_id}' ('{node.block_type}') has nothing wired to its "
            f"primary input."
        )
    _validate_port_source(workflow, primary_edge.from_node, node, spec.primary, primary_kind)

    for edge in incoming:
        if edge.to_port and edge.to_port not in port_names:
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') has an edge to a port "
                f"'{edge.to_port}' it does not have. Its ports: {', '.join(sorted(port_names))}."
            )
    for name in node.bindings:
        if name == spec.primary.name:
            # A binding here would be silently ignored at run time -- run_graph
            # resolves bindings on `spec.extra_ports` only -- while the runner's
            # _required_channel_types still counted its type as mandatory, so
            # every file lacking that channel failed for a graph that never
            # needed it (audit 02, finding S1/1.8).
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') binds its primary port "
                f"'{name}' to a channel. The primary input is fed by an edge -- wire it "
                f"from another node instead."
            )
        if name not in port_names:
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') binds a port '{name}' it "
                f"does not have. Its ports: {', '.join(sorted(port_names))}."
            )

    for port in spec.extra_ports:
        port_edge = _incoming_on_port(workflow, node.node_id, port.name)
        has_binding = port.name in node.bindings
        if port_edge is not None and has_binding:
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') has its '{port.name}' port "
                f"both wired and bound to a channel -- pick one."
            )
        if port_edge is not None:
            _validate_port_source(workflow, port_edge.from_node, node, port, primary_kind)
        elif not has_binding and not port.optional:
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') needs its '{port.name}' port "
                f"bound to a channel (e.g. PortBinding(channel_type='{port.name}'))."
            )
    if workflow.outgoing(node.node_id):
        _validate_single_output(node)


def _validate_single_output(node: WorkflowNode) -> None:
    if not node.is_input and spec_for(node.block_type).multi_output:
        raise ValueError(
            f"Node '{node.node_id}' ('{node.block_type}') emits one block per order; "
            f"nothing can consume that, so it cannot have an outgoing edge."
        )


def _validate_port_source(workflow: Workflow, source_id: str, node: WorkflowNode,
                          port: Port, primary_kind: str) -> None:
    """The same connection rule for authoring and graph validation."""
    _validate_single_output(workflow.node(source_id))
    source_kind = _produced_kind(workflow, source_id, primary_kind)
    if source_kind not in port.accepts:
        port_label = ("primary input" if port == spec_for(node.block_type).primary
                      else f"'{port.name}' port")
        raise ValueError(
            f"Node '{node.node_id}' ('{node.block_type}') accepts "
            f"{' or '.join(port.accepts)} on its {port_label}, but "
            f"'{source_id}' produces '{source_kind}'."
        )


def _produced_kind(workflow: Workflow, node_id: str, primary_kind: str) -> str:
    """The block kind a node's output is. An input node stands for a loaded
    measurement, i.e. `primary_kind`."""
    node = workflow.node(node_id)
    return primary_kind if node.is_input else spec_for(node.block_type).produces


def check_versions(workflow: Workflow) -> List[str]:
    """
    Human-readable warnings where a node's recorded `algorithm_version` differs
    from the one in force now. Never recomputes silently (1.12 pitfall 5) -- the
    caller decides what to do with these.
    """
    warnings: List[str] = []
    for node in workflow.nodes:
        if node.is_input:
            continue
        current = authoring_version(node.block_type)
        if current is None:
            continue
        if node.algorithm_version is None:
            warnings.append(
                f"Node '{node.node_id}' ('{node.block_type}'): workflow records no algorithm "
                f"version; current is {current}."
            )
        elif node.algorithm_version != current:
            warnings.append(
                f"Node '{node.node_id}' ('{node.block_type}'): workflow was authored with "
                f"algorithm version {node.algorithm_version}, current is {current} -- "
                f"results will differ."
            )
    return warnings


# -- running ----------------------------------------------------------------

def _resolve_extra_ports(workflow: Workflow, node: WorkflowNode, spec: BlockSpec,
                         single: Mapping[str, NVHDataBlock],
                         bound_channels: Mapping[str, NVHDataBlock]) -> Dict[str, NVHDataBlock]:
    """The non-primary ports of `node`, each fed from its incoming edge or its
    `PortBinding`. An optional port with neither is left out; a mandatory one
    raises. Split out of `run_graph` for readability only."""
    bound: Dict[str, NVHDataBlock] = {}
    for port in spec.extra_ports:
        port_edge = _incoming_on_port(workflow, node.node_id, port.name)
        if port_edge is not None:
            bound[port.name] = single[port_edge.from_node]
            continue
        binding = node.bindings.get(port.name)
        if binding is None:
            if port.optional:
                continue
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') needs its '{port.name}' port bound."
            )
        channel = bound_channels.get(binding.channel_type)
        if channel is None:
            if port.optional:
                continue
            raise ValueError(
                f"Node '{node.node_id}' ('{node.block_type}') needs a '{binding.channel_type}' "
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

    `inputs` maps each input node's id to the block that stands for it -- one
    channel of one measurement, resolved by the runner (decision 2). This layer
    never reads a file. `bound_channels` maps a channel type ("tacho") to the
    block for it, resolved once per measurement by the caller.

    `roots` overrides which save/terminal nodes this call computes -- see
    `needed_node_ids`. The caller uses it to leave out a branch whose mandatory
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

    Returns `{node_id: [blocks]}` for every non-input node that had to run: the
    terminal nodes, the nodes marked to save, and everything between. One block
    for a spectrum or spectrogram, N for order cuts. A branch nobody consumes is
    not computed.
    """
    bound_channels = bound_channels or {}
    scratch = {} if scratch is None else scratch
    needed = needed_node_ids(workflow, roots)

    single: Dict[str, NVHDataBlock] = {}         # single-output block, by node id
    produced: Dict[str, List[NVHDataBlock]] = {}

    for node_id in topological_order(workflow):
        if node_id not in needed:
            continue
        node = workflow.node(node_id)

        if node.is_input:
            block = inputs.get(node_id)
            if block is None:
                raise ValueError(
                    f"Input node '{node_id}' was given no loaded measurement block."
                )
            single[node_id] = block
            continue

        if cancel is not None:
            cancel.raise_if_cancelled()

        spec = spec_for(node.block_type)

        primary_edge = _incoming_on_port(workflow, node_id, PRIMARY_PORT)
        if primary_edge is None or primary_edge.from_node not in single:
            raise ValueError(
                f"Node '{node_id}' ('{node.block_type}') has no usable primary input; "
                f"validate_graph should have refused this workflow."
            )
        primary_block = single[primary_edge.from_node]

        bound = _resolve_extra_ports(workflow, node, spec, single, bound_channels)

        result = spec.fn(primary_block, bound, dict(node.params), scratch)

        if isinstance(result, list):
            if not spec.multi_output:
                raise ValueError(
                    f"Node '{node_id}' ('{node.block_type}') produced a list but is not "
                    f"multi_output; validate_graph should have refused this workflow."
                )
            produced[node_id] = list(result)
        else:
            single[node_id] = result
            produced[node_id] = [result]

    return {node_id: blocks for node_id, blocks in produced.items()}


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


def identity_params(node: WorkflowNode) -> Dict[str, Any]:
    """
    A node's params as they count for identity: display-only fields dropped,
    every remaining field pinned to an explicit value, the algorithm version
    stamped. The same rule `result_params_from_node` uses, minus the lineage key
    it adds on top.

    Missing keys are backfilled from the `config_cls` defaults so a block that
    was dropped but never "Apply"-ed (empty `params`, audit 02 finding 2.11) and
    one the ribbon wrote in full (`asdict(config)`) hash identically -- otherwise
    the same computation authored two ways is two result sets, neither a cache
    hit for the other.
    """
    spec = spec_for(node.block_type)
    params = resolve_block_params(node.block_type, {
        **_config_defaults(spec.config_cls), **node.params,
    })
    version = node.algorithm_version
    if version is None:
        # A node authored before its kind was versioned, or before this backfill
        # existed: stamp the kind's current version so it hashes the same as a
        # freshly authored one rather than becoming its own result set.
        version = authoring_version(node.block_type)
    params["algorithm_version"] = version
    return params


def _ancestor_repr(workflow: Workflow, node_id: str, seen: Set[str]) -> Any:
    """
    A canonical, node-id-independent description of the subgraph rooted at
    `node_id`, seen from below. Input nodes collapse to a marker -- their
    `MeasurementSelection` name must not enter the fingerprint (running the same
    DSP over a different folder is the same result set: the duplicate dialog
    still has to appear).
    """
    node = workflow.node(node_id)
    if node.is_input:
        return {"input": True}
    if node_id in seen:                      # defensive: validate_graph rejects cycles
        return {"cycle": node_id}
    seen = seen | {node_id}
    return {
        "block": node.block_type,
        "params": identity_params(node),
        "bindings": sorted((port, binding.channel_type)
                           for port, binding in node.bindings.items()),
        "inputs": sorted(
            [edge.to_port, _ancestor_repr(workflow, edge.from_node, seen)]
            for edge in workflow.incoming(node_id)
        ),
    }


def lineage_hash(workflow: Workflow, node_id: str) -> str:
    """
    A fingerprint of the whole subgraph *above* `node_id` (its own params
    excluded). Empty string when every incoming edge comes straight from an
    input node: a one-block graph then has the exact identity today's single
    step has, so no already-saved result set turns into a cache miss.
    """
    incoming = workflow.incoming(node_id)
    if incoming and all(workflow.node(edge.from_node).is_input for edge in incoming):
        return ""
    if not incoming:
        return ""
    structure = sorted(
        [edge.to_port, _ancestor_repr(workflow, edge.from_node, {node_id})]
        for edge in incoming
    )
    canonical = json.dumps(structure, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


# -- building from ribbon configs -----------------------------------------------

def workflow_from_configs(name: str, steps: List[Tuple[str, Any]], *,
                          selection_name: str = "",
                          save: Optional[SaveSpec] = None) -> Workflow:
    """
    Build a linear workflow -- `input -> block -> block -> ...` -- from
    `(block_type, config)` pairs, stamping each node with the current
    `algorithm_version`, dropping the block's `display_only_params`, and
    auto-adding a same-named binding for every non-primary port.

    The last node is marked to save: `save` when the caller passes a `SaveSpec`
    (the ribbon fast path, carrying its channel scope), otherwise a default
    all-channels one. `workflow_from_configs` only ever builds a graph that is
    meant to run and persist, so "save = a node carries a SaveSpec" stays the
    single rule with no implicit fallback in the runner (decision 4 / plan
    2026-09-02 answer B).

    This is the one place a workflow is built from ribbon configs -- the ribbon's
    quick "Compute Result Set..." path is a throwaway two-node graph built here,
    not a second model (plan 2026-09-02). The step picker (phase 7C) will call it
    too, so version stamping and binding cannot drift between the two.

    Optional ports are bound too, not only mandatory ones. A spectrogram's tacho
    is optional because a time-mode waterfall does not need one -- but an
    rpm-tracked one does, and an unbound port would never even be looked for.
    The runner tells the two cases apart: a bound optional channel is used when
    the measurement has it and skipped when it does not.

    `selection_name` is written onto the input node so a workflow that gets
    saved (7B/7C) records what it ran over. The ribbon fast path leaves it blank
    and passes the selection to the runner separately, as it does today.
    """
    nodes: List[WorkflowNode] = [WorkflowNode(
        INPUT_NODE_ID, INPUT_BLOCK_TYPE, input=InputSpec(selection_name=selection_name),
    )]
    edges: List[WorkflowEdge] = []

    upstream = INPUT_NODE_ID
    used_ids: List[str] = []
    for index, (block_type, config) in enumerate(steps):
        takes_params = config is not None and not isinstance(config, NoConfig)
        params = asdict(config) if takes_params else {}
        node_id = block_type if block_type not in used_ids and block_type != INPUT_NODE_ID \
            else f"{block_type}_{index}"
        used_ids.append(node_id)
        is_last = index == len(steps) - 1
        nodes.append(replace(
            new_block_node(block_type, node_id, params),
            save=(save if save is not None else SaveSpec()) if is_last else None,
        ))
        edges.append(WorkflowEdge(upstream, node_id))
        upstream = node_id

    return Workflow(name=name, nodes=tuple(nodes), edges=tuple(edges))
