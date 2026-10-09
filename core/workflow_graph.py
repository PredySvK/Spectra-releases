# =====================================================================
# FILE: core/workflow_graph.py
# =====================================================================
"""
`Workflow` -- a block diagram (a DAG) of processing nodes, runnable over a whole
dataset (ARCHITECTURE_DECISIONS 1.6, Epic P).

This replaces `core/recipe.py`. A recipe was an *ordered chain*: the wire between
two steps was their adjacency in a list. The target picture the user described --
Simulink / ANSYS Workbench: branching, per-node settings, per-node saving of
intermediate results -- is a graph, and a linear chain is only its degenerate
case. Keeping a chain type alongside a graph type would grow two code paths that
drift apart in half a year, which is exactly what merging "Calculate & Save Data"
in phase 7 removed. So there is one model, and the ribbon's quick "Compute Result
Set..." path is built as a throwaway two-node graph (`input -> block`), not a
second model.

Pure data: no I/O, no Qt, no numpy, JSON round-trippable, so a project can store
one (`.nvhproject`) and a workflow file can carry one later. Two halves live
outside this file:

- turning node types into DSP calls, plus the *type-checking of a wire* (does the
  source's kind fit the target port?) -- `signal_processing/workflow.py`, which
  needs `BLOCKS` and numpy but still no I/O. That is why `__post_init__` here only
  checks graph *self-consistency* (unique node ids, edges whose endpoints exist):
  the wire compatibility check needs `BLOCKS` and cannot live in core/.
- feeding the input nodes real measurements off disk -- the runner in `gui/`
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
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from core.frozen import freeze_identities, freeze_range_map, freeze_str_map
from core.models import ChannelIdentity

# The reserved `block_type` of an input node. An input node is a node -- it takes
# part in topological order and carries a `SaveSpec` like any other -- but it has
# no adapter in `BLOCKS`; the runner resolves it to loaded measurement blocks
# (decision 2). Later (phase 7E) it will also stand for a finished `.h5` result
# set used as input.
INPUT_BLOCK_TYPE = "input"


@dataclass(frozen=True)
class PortBinding:
    """
    How a block's non-primary input port is fed.

    A block's primary port is wired to an incoming edge. A second port -- order
    tracking's tacho -- is not another node's output; it is a raw channel of the
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
    What an input node reads. Either a named `MeasurementSelection` stored in the
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
    Which channels and measurements of a marked node's output get written to its
    result set (decision 4, 1.6). Saving is opt-in per node: a node with no
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

    `label` is what the result set written at this node is called on disk. Blank
    lets the runner derive one (the run's own name for a single-save graph, that
    name plus the node id when several nodes save): a branching graph writes one
    folder per marked node, so each needs its own name, and 7C's panel is where
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
class WorkflowNode:
    """
    One node of the graph.

    A *block node* has `block_type` keying into `signal_processing.workflow.BLOCKS`,
    a flat JSON-safe `params` mirror of that block's `core/dsp_configs.py`
    dataclass (the node carries its own copy so the engine never reads the ribbon
    -- 1.12 pitfall 1, and decision 1: from the moment a node is saved the ribbon
    is never consulted again), `bindings` for its non-primary ports, and an
    `algorithm_version` stamped at authoring time (a mismatch on a later run is a
    warning, not a silent recompute -- 1.12 pitfall 5).

    An *input node* has `block_type == INPUT_BLOCK_TYPE` and an `input` spec; its
    `params` / `bindings` are unused.

    `save` is opt-in per node (decision 4). `None` means this node's output is
    only an intermediate the graph passes downstream.
    """
    node_id: str
    block_type: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    bindings: Mapping[str, PortBinding] = field(default_factory=dict)
    algorithm_version: Optional[int] = None
    save: Optional[SaveSpec] = None
    input: Optional[InputSpec] = None

    def __post_init__(self):
        if not self.node_id:
            raise ValueError("A workflow node needs a non-empty id.")
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "bindings", MappingProxyType({
            str(name): binding for name, binding in dict(self.bindings).items()
        }))

    @property
    def is_input(self) -> bool:
        return self.block_type == INPUT_BLOCK_TYPE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "block_type": self.block_type,
            "params": dict(self.params),
            "bindings": {name: binding.to_dict() for name, binding in self.bindings.items()},
            "algorithm_version": self.algorithm_version,
            "save": None if self.save is None else self.save.to_dict(),
            "input": None if self.input is None else self.input.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowNode":
        data = data or {}
        version = data.get("algorithm_version")
        save = data.get("save")
        source = data.get("input")
        return cls(
            node_id=str(data.get("node_id") or ""),
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
class WorkflowEdge:
    """
    A wire from `from_node`'s output into `to_node`'s port `to_port` (empty means
    the primary port).

    There is no `from_port`: a `multi_output` node (order tracking emits one block
    per order) is not allowed an outgoing edge -- nothing can consume a list --
    so an edge always starts at a single-output node.
    """
    from_node: str
    to_node: str
    to_port: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"from_node": self.from_node, "to_node": self.to_node, "to_port": self.to_port}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowEdge":
        data = data or {}
        return cls(
            from_node=str(data.get("from_node") or ""),
            to_node=str(data.get("to_node") or ""),
            to_port=str(data.get("to_port") or ""),
        )


@dataclass(frozen=True)
class Workflow:
    """
    A named block diagram. `nodes` order is authoring order only (for display) --
    the data flow is `edges`, never adjacency.

    `__post_init__` checks only what can be checked without `BLOCKS`: node ids are
    unique, and every edge endpoint names a node that exists. Cycle detection,
    port type-checking and "every mandatory port is fed" are `validate_graph` in
    `signal_processing/workflow.py`.
    """
    name: str = ""
    nodes: Tuple[WorkflowNode, ...] = ()
    edges: Tuple[WorkflowEdge, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))

        seen: set = set()
        for node in self.nodes:
            if node.node_id in seen:
                raise ValueError(f"Duplicate workflow node id '{node.node_id}'.")
            seen.add(node.node_id)

        for edge in self.edges:
            for endpoint, side in ((edge.from_node, "from"), (edge.to_node, "to")):
                if endpoint not in seen:
                    raise ValueError(
                        f"Edge {side} unknown node '{endpoint}'. "
                        f"Known nodes: {', '.join(sorted(seen)) or '(none)'}."
                    )

    @property
    def node_ids(self) -> Tuple[str, ...]:
        return tuple(node.node_id for node in self.nodes)

    def node(self, node_id: str) -> WorkflowNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    def incoming(self, node_id: str) -> Tuple[WorkflowEdge, ...]:
        """Edges feeding `node_id`, in authoring order."""
        return tuple(edge for edge in self.edges if edge.to_node == node_id)

    def outgoing(self, node_id: str) -> Tuple[WorkflowEdge, ...]:
        """Edges leaving `node_id`, in authoring order."""
        return tuple(edge for edge in self.edges if edge.from_node == node_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Workflow":
        data = data or {}
        return cls(
            name=str(data.get("name") or ""),
            nodes=tuple(WorkflowNode.from_dict(raw) for raw in (data.get("nodes") or ())),
            edges=tuple(WorkflowEdge.from_dict(raw) for raw in (data.get("edges") or ())),
        )


# -- immutable edit helpers ------------------------------------------------------
# A Workflow is frozen the whole way down, so a graph editor (phase 7C tree,
# phase 8 canvas) makes changes by rebuilding: each helper returns a new Workflow.
# They stay here, on the pure-data model, because none needs `BLOCKS` -- adding a
# *block* node with its default bindings and version stamp does, and that one
# lives in `signal_processing/workflow.py` (`new_block_node`).


def new_workflow(name: str, *, input_node_id: str = "input") -> "Workflow":
    """A fresh graph: one input node defaulting to the whole Data Pool, no blocks
    yet. The user adds blocks afterwards and can narrow the input to a saved
    selection -- but a fresh workflow is runnable without authoring one first."""
    return Workflow(
        name=name,
        nodes=(WorkflowNode(input_node_id, INPUT_BLOCK_TYPE, input=InputSpec(whole_pool=True)),),
        edges=(),
    )


def with_node(workflow: "Workflow", node: "WorkflowNode") -> "Workflow":
    return Workflow(name=workflow.name, nodes=workflow.nodes + (node,), edges=workflow.edges)


def with_edge(workflow: "Workflow", edge: "WorkflowEdge") -> "Workflow":
    return Workflow(name=workflow.name, nodes=workflow.nodes, edges=workflow.edges + (edge,))


def with_node_replaced(workflow: "Workflow", node_id: str, **changes: Any) -> "Workflow":
    """Return a copy of `workflow` with `dataclasses.replace(node, **changes)`
    applied to the node of that id (e.g. `params=...` or `input=...`)."""
    nodes = tuple(
        replace(node, **changes) if node.node_id == node_id else node
        for node in workflow.nodes
    )
    return Workflow(name=workflow.name, nodes=nodes, edges=workflow.edges)


def without_node(workflow: "Workflow", node_id: str) -> "Workflow":
    """Drop a node and every edge touching it."""
    return Workflow(
        name=workflow.name,
        nodes=tuple(n for n in workflow.nodes if n.node_id != node_id),
        edges=tuple(e for e in workflow.edges
                    if e.from_node != node_id and e.to_node != node_id),
    )
