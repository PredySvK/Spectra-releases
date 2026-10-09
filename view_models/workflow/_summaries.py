# =====================================================================
# FILE: view_models/workflow/_summaries.py
# =====================================================================
"""
The two node-label text bodies `WorkflowView` renders next to a tree node
and in the right-panel summary box (issue #185): what an input node's
selection resolves to, and what a block node produces/binds/saves. Both take
their `Workflow`/`WorkflowNode`/`BlockSpec` arguments explicitly -- no
`self`, no Qt.
"""
from __future__ import annotations

from typing import Optional

from core.workflow_graph import InputSpec, Workflow, WorkflowNode
from signal_processing.workflow import BlockSpec, lineage_hash


def format_input_summary(spec: Optional[InputSpec]) -> str:
    if spec is not None and spec.whole_pool:
        return "whole pool"
    return (spec.selection_name if spec else "") or "none"


def format_node_summary(workflow: Workflow, node: WorkflowNode, spec: BlockSpec) -> str:
    lines = [f"Produces: {spec.produces}"]
    if spec.multi_output:
        lines.append("Emits one block per order (no outgoing edge allowed).")
    lines.append(f"Algorithm version: {node.algorithm_version}")
    if node.bindings:
        bound = ", ".join(f"{port}={b.channel_type}" for port, b in node.bindings.items())
        lines.append(f"Channel bindings: {bound}")
    if node.save is not None:
        scope = "all channels" if node.save.all_channels else (
            f"{len(node.save.channel_identities)} channel(s)")
        lines.append("")
        lines.append(f"Saved: yes  (label: {node.save.label or 'auto'}; {scope})")
    else:
        lines.append("")
        lines.append("Saved: no (intermediate result only)")
    lineage = lineage_hash(workflow, node.node_id)
    lines.append("")
    lines.append(f"Lineage hash: {lineage or '(none — fed straight from input)'}")
    return "\n".join(lines)
