"""Qt-free state model for the Cursor (1D graph and spectrogram) and Highlight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple

from core.cursor_config import CursorConfig
from core.units import UnitPreferences
from view_models.plot import DrawnSpectrogram, Trace

from ._box import build_cursor_box_lines
from ._hit_test import AxisTransform, CursorPoint, resolve_cursor_point
from ._spectrogram import SpectrogramPoint, resolve_spectrogram_pixel

MetadataMap = Mapping[str, Tuple[str, str]]
MetadataReader = Callable[[Trace, Iterable[str]], MetadataMap]


@dataclass(frozen=True)
class CursorView:
    """What the GUI draws after a Cursor / Highlight transition."""

    box_visible: bool = False
    lines: Tuple[Tuple[str, str], ...] = ()
    move_box: bool = False
    crosshair: Optional[Tuple[float, float]] = None
    highlighted_trace: Optional[Trace] = None


def _resolve_metadata(
    trace: Trace,
    fields: Sequence[str],
    metadata: Optional[MetadataMap],
    metadata_reader: Optional[MetadataReader],
) -> MetadataMap:
    if metadata is not None:
        return metadata
    if metadata_reader is not None:
        return metadata_reader(trace, fields)
    return {}


def _match_trace(old_trace: Trace, traces: Sequence[Trace]) -> Optional[Trace]:
    for trace in traces:
        if trace is old_trace:
            return trace
    if old_trace.block is not None:
        for trace in traces:
            if trace.block is old_trace.block:
                return trace
        return None
    if old_trace.y_raw is not None:
        for trace in traces:
            if trace.y_raw is old_trace.y_raw:
                return trace
    return None


def _remap_axis(value: float, old_extent: Tuple[float, float], new_extent: Tuple[float, float]) -> float:
    if old_extent == new_extent:
        return value
    old_lo, old_hi = old_extent
    new_lo, new_hi = new_extent
    span = old_hi - old_lo
    if span == 0.0:
        return new_lo
    mapped = new_lo + (value - old_lo) * (new_hi - new_lo) / span
    return min(max(mapped, new_lo), new_hi)


class CursorState:
    """State of one dock's Cursor (1D graph or spectrogram) and Highlight."""

    def __init__(self) -> None:
        self._point: Optional[CursorPoint | SpectrogramPoint] = None
        self._drawn_spectrogram: Optional[DrawnSpectrogram] = None
        self._box_visible: bool = False
        self._lines: Tuple[Tuple[str, str], ...] = ()
        self._crosshair: Optional[Tuple[float, float]] = None
        self._highlighted_trace: Optional[Trace] = None

    @property
    def point(self) -> Optional[CursorPoint | SpectrogramPoint]:
        return self._point

    @property
    def box_visible(self) -> bool:
        return self._box_visible

    @property
    def lines(self) -> Tuple[Tuple[str, str], ...]:
        return self._lines

    @property
    def crosshair(self) -> Optional[Tuple[float, float]]:
        return self._crosshair

    @property
    def highlighted_trace(self) -> Optional[Trace]:
        return self._highlighted_trace

    def hover_graph(
        self,
        traces: Sequence[Trace],
        transforms: Mapping[str, AxisTransform],
        mouse_px: Optional[Tuple[float, float]],
        *,
        radius_px: float = 10.0,
        cursor_enabled: bool = True,
        pinned: bool = False,
        highlight_enabled: bool = False,
        button_pressed: bool = False,
        config: CursorConfig = CursorConfig(),
        x_unit: str = "",
        x_quantity: str = "",
        two_axes: bool = False,
        prefs: Optional[UnitPreferences] = None,
        metadata: Optional[MetadataMap] = None,
        metadata_reader: Optional[MetadataReader] = None,
    ) -> CursorView:
        """Evaluate one mouse move over a 1D graph for both Cursor and Highlight."""
        in_plot = (not button_pressed) and (mouse_px is not None) and bool(traces)
        point: Optional[CursorPoint] = None
        if in_plot and (cursor_enabled or highlight_enabled):
            point = resolve_cursor_point(traces, transforms, mouse_px, radius_px)

        self._highlighted_trace = point.trace if (highlight_enabled and in_plot and point is not None) else None

        if not cursor_enabled or not traces:
            return self.hide()

        if not in_plot or point is None:
            if not pinned:
                return self.hide()
            return self._view(move_box=False)

        resolved_meta = _resolve_metadata(point.trace, config.fields, metadata, metadata_reader)
        lines = tuple(build_cursor_box_lines(
            point, config, x_unit=x_unit, x_quantity=x_quantity,
            two_axes=two_axes, metadata=resolved_meta, prefs=prefs,
        ))
        self._point = point
        if not lines:
            if not pinned:
                return self.hide()
            return self._view(move_box=False)

        was_visible = self._box_visible
        self._lines = lines
        self._box_visible = True
        return self._view(move_box=not (pinned and was_visible))

    def refresh_graph(
        self,
        traces: Sequence[Trace],
        *,
        x_display: float = 1.0,
        cursor_enabled: bool = True,
        config: CursorConfig = CursorConfig(),
        x_unit: str = "",
        x_quantity: str = "",
        two_axes: bool = False,
        prefs: Optional[UnitPreferences] = None,
        metadata: Optional[MetadataMap] = None,
        metadata_reader: Optional[MetadataReader] = None,
    ) -> CursorView:
        """Recompute the captured 1D graph point against ``traces`` and ``x_display``."""
        self._highlighted_trace = None
        if not self._box_visible or not isinstance(self._point, CursorPoint) or not cursor_enabled:
            return self.hide()

        matched = _match_trace(self._point.trace, traces)
        idx = self._point.index
        if matched is None or not (0 <= idx < len(matched.x) and idx < len(matched.y)):
            return self.hide()

        point = CursorPoint(
            trace=matched,
            index=idx,
            x=float(matched.x[idx]) * x_display,
            y=float(matched.y[idx]),
            secondary=matched.axis == "secondary",
            distance_px=self._point.distance_px,
        )
        resolved_meta = _resolve_metadata(point.trace, config.fields, metadata, metadata_reader)
        lines = tuple(build_cursor_box_lines(
            point, config, x_unit=x_unit, x_quantity=x_quantity,
            two_axes=two_axes, metadata=resolved_meta, prefs=prefs,
        ))
        self._point = point
        self._lines = lines
        self._box_visible = bool(lines)
        return self._view(move_box=False)

    def hover_spectrogram(
        self,
        drawn: Optional[DrawnSpectrogram],
        pos: Optional[Tuple[float, float]],
        *,
        cursor_enabled: bool = True,
        pinned: bool = False,
        button_pressed: bool = False,
        config: CursorConfig = CursorConfig(),
        prefs: Optional[UnitPreferences] = None,
    ) -> CursorView:
        """Evaluate one mouse move over a spectrogram."""
        if not cursor_enabled or drawn is None:
            return self.hide()

        if button_pressed or pos is None:
            if not pinned:
                return self.hide()
            return self._view(move_box=False)

        point = resolve_spectrogram_pixel(drawn, x=pos[0], y=pos[1])
        if point is None:
            if not pinned:
                return self.hide()
            return self._view(move_box=False)

        self._point = point
        self._drawn_spectrogram = drawn
        self._crosshair = (point.x, point.y)
        lines = tuple(build_cursor_box_lines(point, config, prefs=prefs))
        if not lines:
            if not pinned:
                return self.hide()
            return self._view(move_box=False)

        was_visible = self._box_visible
        self._lines = lines
        self._box_visible = True
        return self._view(move_box=not (pinned and was_visible))

    def refresh_spectrogram(
        self,
        drawn: Optional[DrawnSpectrogram],
        *,
        cursor_enabled: bool = True,
        config: CursorConfig = CursorConfig(),
        prefs: Optional[UnitPreferences] = None,
    ) -> CursorView:
        """Recompute the captured spectrogram point and crosshair against ``drawn``."""
        if not self._box_visible or not isinstance(self._point, SpectrogramPoint) or not cursor_enabled or drawn is None:
            return self.hide()

        if self._drawn_spectrogram is not None:
            x = _remap_axis(self._point.x, self._drawn_spectrogram.x_extent, drawn.x_extent)
            y = _remap_axis(self._point.y, self._drawn_spectrogram.y_extent, drawn.y_extent)
        else:
            x, y = self._point.x, self._point.y

        point = resolve_spectrogram_pixel(drawn, x=x, y=y)
        if point is None:
            return self.hide()

        self._point = point
        self._drawn_spectrogram = drawn
        self._crosshair = (point.x, point.y)
        lines = tuple(build_cursor_box_lines(point, config, prefs=prefs))
        self._lines = lines
        self._box_visible = bool(lines)
        if not self._box_visible:
            self._crosshair = None
        return self._view(move_box=False)

    def leave(self, *, cursor_enabled: bool = True, pinned: bool = False) -> CursorView:
        """The mouse left the plot viewport."""
        self._highlighted_trace = None
        if not cursor_enabled or not pinned:
            return self.hide()
        return self._view(move_box=False)

    def hide(self) -> CursorView:
        """Hide the Cursor Box and crosshair (Cursor switched off or unpinned)."""
        self._point = None
        self._drawn_spectrogram = None
        self._box_visible = False
        self._lines = ()
        self._crosshair = None
        return self._view(move_box=False)

    def clear(self) -> CursorView:
        """Clear all cursor and highlight state (graph cleared or new spectrogram block)."""
        self._highlighted_trace = None
        return self.hide()

    def _view(self, *, move_box: bool) -> CursorView:
        return CursorView(
            box_visible=self._box_visible,
            lines=self._lines,
            move_box=move_box,
            crosshair=self._crosshair,
            highlighted_trace=self._highlighted_trace,
        )
