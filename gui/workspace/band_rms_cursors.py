# =====================================================================
# FILE: gui/workspace/band_rms_cursors.py
# =====================================================================
"""
Band RMS cursors for GraphDock's frequency-domain plots.

A draggable band over a spectrum that reports Band RMS (CONTEXT.md) within
its span -- the single figure Testlab users read first, and until this
existed, computable (signal_processing.dsp.spectral.compute_overall_level,
now signal_processing.dsp.levels.compute_band_rms) but unreachable from the
UI.

Mixed into GraphDock rather than built as a separate collaborator: this code
reaches directly into the dock's own plot_widget and its already-rendered
curve data, all owned by GraphDock's drawing code. Wrapping that in a
collaborator interface would cost more than it buys.

The feature's state -- whether the band is on, the (lo, hi) span the user
dragged, and the window corrections the calculation needs -- lives on
model.band_rms_cursors[0] (ARCHITECTURE_DECISIONS §1.7, R2, §1.62). This mixin reads and
writes that BandRmsCursor; set_band_rms_cursors flips its enabled flag, a drag
writes band back. The pyqtgraph widgets it builds from that state
(_band_rms_region, _band_rms_label) are renderer-side and owned here, declared
in _init_band_rms_cursors. The curve it measures is curves.base_trace.
"""

from typing import Optional

import numpy as np
import pyqtgraph as pg

from core.units import check_units_compatibility, convert_numeric_array
from view_models.plot import BandRmsCursor, base_display_unit
from signal_processing.dsp.levels import compute_band_rms


class BandRmsCursorsMixin:
    """Draggable Band RMS band + readout, mixed into GraphDock."""

    def _init_band_rms_cursors(self) -> None:
        """Called from GraphDock.__init__ -- see module docstring for why this
        piece of state is initialized here rather than alongside the rest of
        the dock's attributes."""
        self._band_rms_region: Optional[pg.LinearRegionItem] = None
        self._band_rms_label: Optional[pg.TextItem] = None

    def _band_rms_cursor(self) -> Optional[BandRmsCursor]:
        """The Band RMS cursor on the current model, or None when the dock
        holds nothing it could measure (a time plot has no Band RMS cursors)."""
        model = self.curves.model
        if model is None or not model.band_rms_cursors:
            return None
        return model.band_rms_cursors[0]

    def supports_band_rms(self) -> bool:
        """True once a spectrum is plotted; Band RMS is meaningless otherwise."""
        return self._band_rms_cursor() is not None and self.curves.base_trace is not None

    def set_band_rms_cursors(self, enabled: bool) -> bool:
        """
        Shows or hides the draggable band that reports Band RMS.

        Returns whether the cursors ended up visible, which is False when the
        dock holds nothing they could measure.
        """
        cursor = self._band_rms_cursor()
        if cursor is not None:
            cursor.enabled = bool(enabled)
        self._refresh_band_rms_cursors()
        return self._band_rms_region is not None

    def _base_display_unit(self) -> str:
        """
        The plain physical unit behind a spectral label -- resolves a 'dB'
        axis unit back to a source unit this dock actually has, then defers
        the RMS/PEAK/() stripping rule to view_models.plot.base_display_unit
        (ADR §1.7).
        """
        base = self.curves.base_trace
        unit = (base.unit if base is not None else "").strip()
        if unit == "dB":
            if base.source_unit and base.source_unit != "dB":
                unit = base.source_unit
            elif base.block is not None:
                unit = base.block.value_unit

        return base_display_unit(unit)

    def _remove_band_rms_cursors(self):
        if self._band_rms_region is not None:
            try:
                self._band_rms_region.sigRegionChanged.disconnect(self._update_band_rms)
            except (RuntimeError, TypeError):
                pass
            self.plot_widget.removeItem(self._band_rms_region)
            self._band_rms_region = None

        if self._band_rms_label is not None:
            self._band_rms_label.setParentItem(None)
            scene = self.plot_widget.plotItem.scene()
            if scene is not None:
                scene.removeItem(self._band_rms_label)
            self._band_rms_label = None

    def _refresh_band_rms_cursors(self):
        self._remove_band_rms_cursors()

        cursor = self._band_rms_cursor()
        if cursor is None or not cursor.enabled or not self.supports_band_rms():
            return

        frequencies = self.curves.base_trace.x
        if frequencies is None or len(frequencies) < 2:
            return

        low, high = float(frequencies[0]), float(frequencies[-1])
        span = high - low

        # Restore the span the user last dragged (persisted on the model), clamped
        # to the current spectrum's extent; otherwise open on a default window.
        if cursor.band is not None:
            lo, hi = (float(edge) for edge in cursor.band)
            initial = (max(low, min(lo, high)), min(high, max(hi, low)))
        else:
            initial = (low + 0.10 * span, low + 0.35 * span)

        # The band is kept in Hz; only the region on screen follows the global
        # X axis unit (issue #459), so the span survives switching it.
        scale = self._x_axis.scale
        self._band_rms_region = pg.LinearRegionItem(
            values=(initial[0] * scale, initial[1] * scale),
            brush=pg.mkBrush(90, 160, 220, 40),
            hoverBrush=pg.mkBrush(90, 160, 220, 70),
        )
        self._band_rms_region.setBounds([low * scale, high * scale])
        # Behind the traces, so dragging the band never hides the data it measures.
        self._band_rms_region.setZValue(-10)
        self.plot_widget.addItem(self._band_rms_region)

        # Parented to the ViewBox, so setPos is in pixels and the readout stays
        # put while the user pans and zooms underneath it.
        self._band_rms_label = pg.TextItem(
            anchor=(0, 0), color="#e8edf2", fill=pg.mkBrush(18, 24, 31, 210)
        )
        self._band_rms_label.setParentItem(self.plot_widget.plotItem.vb)
        self._band_rms_label.setPos(12, 10)

        self._band_rms_region.sigRegionChanged.connect(self._update_band_rms)
        self._update_band_rms()

    def _update_band_rms(self):
        if self._band_rms_region is None or self._band_rms_label is None:
            return

        shown_start, shown_stop = (float(edge) for edge in self._band_rms_region.getRegion())
        f_start, f_stop = shown_start / self._x_axis.scale, shown_stop / self._x_axis.scale

        cursor = self._band_rms_cursor()
        # Write the dragged span back so it survives a re-render (unit change,
        # async re-delivery).
        if cursor is not None:
            cursor.band = (f_start, f_stop)

        base_tr = self.curves.base_trace
        canon_block = base_tr.block if base_tr else None
        unit = self._base_display_unit()

        if canon_block is None or not getattr(canon_block, "is_canonical", False):
            self._band_rms_label.setText("Band RMS unavailable")
            return

        try:
            raw_level = compute_band_rms(
                frequencies=base_tr.x,
                p_canon=canon_block.values,
                f_start=f_start,
                f_stop=f_stop,
            )
            if unit and canon_block.value_unit and check_units_compatibility(canon_block.value_unit, unit):
                converted = convert_numeric_array(
                    np.array([raw_level]), from_unit=canon_block.value_unit, to_unit=unit
                )
                level = float(converted[0])
            else:
                level = raw_level
        except Exception as exc:
            self._band_rms_label.setText(f"Band RMS unavailable\n{exc}")
            return

        self._band_rms_label.setText(
            f"Band RMS  {level:.4g} {unit} RMS\n"
            f"{shown_start:,.1f} – {shown_stop:,.1f} {self._x_axis.unit}"
        )
