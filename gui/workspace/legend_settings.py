# =====================================================================
# FILE: gui/workspace/legend_settings.py
# =====================================================================
"""
Legend Settings on GraphDock: "Legend Settings…" in the graph's right-click menu
and the gear at the legend (`LegendGear`) open the shared Cursor / Track cursor Settings window (`LEGEND_SETTINGS`) over
this graph's legend configuration (plot §1.296).

The configuration lives in the graph's curves state (`GraphCurves.set_legend_config`),
which names every curve by it -- the legend, the Cursor Box and Track table
"Curve" and the Band RMS readout all read that one Curve name. Auto apply
previews on this graph only; Cancel puts back what the graph had (shell §1.37).
A spectrogram is not a GraphDock, so it never offers the item.

A metadata part (Parameter set, a Raw or Excel field...) is read off the
graph's Curve metadata records, through the same project lookups the Cursor
uses (`resolve_curve_metadata_sources`), whole graph at once on each redraw.

The window's Default column is the legend every new graph starts with; OK keeps it
in the app context (`legend_default_config`), the graph itself is saved in its TabSpec.

Runs synchronously on the GUI thread: the window builds a few rows and
re-assembling the Curve names is in-memory text work, no disk.
"""

from typing import Any, Dict, List, Sequence

from core.legend_config import DEFAULT_LEGEND_FIELDS, LegendConfig
from gui.dialogs.field_priority_dialog import LEGEND_SETTINGS, FieldPriorityDialog
from orchestration.trace_filter import resolve_curve_metadata_sources
from gui.workspace.legend_gear import LegendGear
from view_models.curve_metadata import build_curve_metadata
from view_models.plot import Trace


class LegendSettingsMixin:
    """GraphDock's Legend Settings entry and window; expects `plot_widget`, `curves`, `app_context`."""

    def _init_legend_settings(self) -> None:
        menu = self.plot_widget.plotItem.vb.menu
        self.legend_settings_action = menu.addAction("Legend Settings…")
        self.legend_settings_action.triggered.connect(self.open_legend_settings)
        self.legend_gear = LegendGear(self.plot_widget, self.plot_widget.plotItem.legend, self.open_legend_settings)
        self.curves.set_curve_metadata_source(self._build_curve_metadata_records)
        # A new graph starts with the Default; a restored one is given its saved legend after (build_shell).
        default = getattr(self.app_context, "legend_default_config", None)
        if isinstance(default, LegendConfig):
            self.curves.set_legend_config(default)

    def _build_curve_metadata_records(self, traces: Sequence[Trace]) -> List[Dict[str, Any]]:
        sources = resolve_curve_metadata_sources(
            getattr(self.app_context, "project_session", None), getattr(self.app_context, "pool", None))
        if sources is None:
            return [{} for _ in traces]
        schema, identity_context = sources
        return build_curve_metadata(
            traces, identity_context.sources_by_path, identity_context.result_set_labels, schema)

    def open_legend_settings(self) -> None:
        """The window for this graph; OK keeps its choice, Cancel the one the graph had."""
        ctx = self.app_context
        pool = getattr(ctx, "pool", None)
        schema = pool.schema().master if pool is not None else {}
        before = self.curves.legend_config
        default = getattr(ctx, "legend_default_config", None)
        dialog = FieldPriorityDialog(
            schema, before, self, settings=getattr(ctx, "settings", None), spec=LEGEND_SETTINGS,
            on_live_change=lambda config, *_opacities: self.curves.set_legend_config(config),
            default_fields=default.fields if isinstance(default, LegendConfig) else DEFAULT_LEGEND_FIELDS)
        try:
            accepted = dialog.exec()
            self.curves.set_legend_config(dialog.result_config() if accepted else before)
            if accepted and hasattr(ctx, "set_legend_default_config"):
                ctx.set_legend_default_config(LegendConfig(dialog.result_default_fields()))
        finally:
            dialog.deleteLater()
