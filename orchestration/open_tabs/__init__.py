"""
Open-tabs orchestration: a graph's overlays between a live dock and a saved tab.

`build_overlay_trace_specs` turns the overlays a `GraphCurves` holds into the
`TraceSpec` identity a saved `TabSpec` carries -- the same
`(source_id, channel_name)` a base curve is saved under. `build_drop_descriptor`
turns an overlay the Data Pool resolved on reopen back into the channel-drop
payload a live drag produces, so a restore re-drops through the one drop path.
`build_base_trace_spec` does the same for the base curve of a graph opened with
several channels at once, which has no run of its own to name it.

`build_tab_spec` turns a dock's captured data into the `TabSpec` a Save writes
(dead-link and not-yet-landed restored tabs included).

What does not belong here: parsing and resolving saved tabs (`session.open_tabs`),
the pending restore itself (`view_models.plot.GraphCurves`), and building docks
or dispatching the re-drop (`gui/`).
"""

from orchestration.open_tabs._overlay_identity import (
    build_base_trace_spec,
    build_drop_descriptor,
    build_overlay_trace_specs,
)
from orchestration.open_tabs._tab_snapshot import build_tab_spec

__all__ = [
    "build_base_trace_spec",
    "build_drop_descriptor",
    "build_overlay_trace_specs",
    "build_tab_spec",
]
