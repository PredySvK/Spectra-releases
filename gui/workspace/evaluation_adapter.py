# =====================================================================
# FILE: gui/workspace/evaluation_adapter.py
# =====================================================================
"""
Turns a graph dock's visible curves into the traces + lookup dicts
view_models.evaluation.curve_identities_for_traces needs -- the dock adapter
ADR §1.64 point 3 asks for. Reads only a dock's public surface
(`visible_traces()`), never a private attribute.

Lives in gui/ (it reads a dock and an AppContext, both Qt-adjacent) even
though it imports no Qt itself; the curve collection it hands off to is pure
(issue #184 -- see view_models.evaluation for the dock-free half).
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity
from orchestration.trace_filter import build_identity_context
from view_models.evaluation import curve_identities_for_traces, synthetic_trace_for_block


def _spectrogram_block_for_dock(dock: Any) -> Optional[NVHDataBlock]:
    """`dock.canonical_block()` if the dock exposes one (SpectrogramDock,
    ADR §1.64 point 3), else None -- duck-typed rather than an isinstance
    check so this stays free of a gui.workspace.spectrogram_dock import."""
    getter = getattr(dock, "canonical_block", None)
    if not callable(getter):
        return None
    return getter()


def curves_for_evaluation(
    dock: Any, app_context: Any, respect_trace_filter: bool = True,
) -> List[Tuple[NVHDataBlock, CurveIdentity]]:
    """The Evaluation card's one path from a focused dock to Evaluation
    input. Returns every visible curve that carries a block, regardless of
    its kind -- runner.evaluate is what decides which of them the chosen
    Evaluation actually accepts, so a dock with no supported curves still
    comes back as an empty table rather than an empty list here.

    `respect_trace_filter` picks which of the dock's own two visibility
    methods to read: `visible_traces()` (Trace filter mask applied, the
    default) or `all_traces()` (mask skipped, X-domain fit and third-axis
    drop still applied) -- the "Respect Trace filter" toggle, issue #136.
    Ignored for a dock whose content is one block (a spectrogram has no
    per-trace mask to respect -- the Filter routing skips it too).
    """
    spectrogram_block = _spectrogram_block_for_dock(dock)
    if spectrogram_block is not None:
        traces = [synthetic_trace_for_block(spectrogram_block)]
    else:
        traces_source = dock.visible_traces if respect_trace_filter else dock.all_traces
        traces = [trace for trace in traces_source() if trace.block is not None]
    if not traces:
        return []

    identity_context = build_identity_context(getattr(app_context, "project_session", None))
    return curve_identities_for_traces(
        traces, identity_context.sources_by_path, identity_context.result_set_labels, identity_context.schema)
