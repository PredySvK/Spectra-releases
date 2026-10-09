"""
The one owner of which curves a single graph holds (CONTEXT.md "Graph curves").

A ``GraphCurves`` keeps the ``PlotModel`` a dock draws, the Trace filter mask
and the visibility decision taken through it, how many overlays are drawn,
which result sets were loaded onto the
graph, the mask key the Filters panel last applied, and the restore still
pending until the next base curve lands (a Refresh, or a tab reopened from a
saved project). Every change goes
through one of its operations and ends in exactly one ``on_change`` call, so a
dock draws what changed and never edits the curves itself.

Settings (unit preferences, spectrum format, amplitude mode, dB) arrive as
one ``DisplaySettings``: which settings object belongs to which analysis kind is a GUI
question, and a plain test needs no fake settings to call an operation.

``model`` is handed out for reading without a copy -- the arrays behind it are
large. Only this class writes to it.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import types
from typing import Any, Callable, Dict, FrozenSet, Iterable, Iterator, List, Optional, Sequence, Tuple, Union
import weakref

import numpy as np

from core.block_kinds import KIND_ORDER_CUT, KIND_TIME_RESPONSE
from core.units import UnitPreferences, strip_amplitude_suffix
from selection.channel_identity import build_channel_key

from ._display_settings import DisplaySettings
from ._graph_colours import HeldPens
from ._plot_model import PlotModel, Trace
from ._display_rebuild import (
    rebuild_amplitude_mode_display,
    rebuild_spectrum_with_display_settings,
    rebuild_with_domain,
    rebuild_with_units,
)
from ._plot_model_builder import (
    _base_trace_index,
    build_base_model,
    build_order_cuts_model,
    build_scaled_overlay_trace,
    traces_kept_after_unload,
)
from ._visible_traces import (
    AcceptOutcome,
    Mask,
    VisibleTraces,
    resolve_visible_traces,
)


@dataclass(frozen=True)
class CurvesReplaced:
    """The curve list or its visibility changed as a whole -- redraw everything.

    ``first_curve`` is True when the graph went from holding no model at all to
    holding one, the moment a Local Filter card's Channel facet first has
    something to default onto. ``curves_added`` is True when a
    ``coalesce_changes`` block ends holding more curves than it started with."""

    first_curve: bool = False
    curves_added: bool = False


@dataclass(frozen=True)
class CurveAppended:
    """One curve was added without resolving the rest again.

    ``outcome`` says what the incremental path decided: draw just this curve,
    skip it (the mask hid it while others still show), or -- when a full pass
    is needed to explain why something is hidden -- the visibility was already
    re-resolved and everything must be redrawn."""

    trace: Trace
    outcome: AcceptOutcome


@dataclass(frozen=True)
class CurvesCleared:
    """The graph holds no curves any more."""


CurvesChange = Union[CurvesReplaced, CurveAppended, CurvesCleared]


def build_trace_descriptor(trace: Trace) -> Dict[str, Any]:
    """The drag/persistence descriptor of one curve: what the graph shows it
    as and where it came from."""
    if trace.is_base:
        label = trace.channel_name
    else:
        label = f"[{trace.file_name}] {trace.channel_name}".strip()
    return {
        "is_base": trace.is_base,
        "label": label,
        "unit": trace.unit,
        "meta_ref": trace.meta_ref,
        "result_set_id": trace.result_set_id,
    }


def _build_channel_drop_descriptor(trace: Trace) -> Dict[str, Any]:
    """The channel-drop payload (a Data Pool drag's shape) that reads the
    channel behind ``trace`` again.

    Unit and name are the channel's own, never the curve's display ones: a
    re-drop hands ``unit`` to the reader as the unit of the raw samples, so a
    g channel shown in m/s^2 would otherwise come back 9.81x too small, and
    the legend "[file] channel" would gain a second file prefix (#377).
    """
    meta = trace.meta_ref or {}
    block = trace.data_block if trace.data_block is not None else trace.block
    if block is None:
        channel_name = trace.channel_name
        unit = strip_amplitude_suffix(trace.source_unit)
    else:
        source = getattr(block, "source", None)
        channel_name = getattr(source, "channel_name", "") or trace.channel_name
        # A time record carries the channel unit as read; every block derived
        # from it only adds a " RMS" / "(...)^2" spelling around it.
        unit = (block.value_unit if getattr(block, "kind", None) == KIND_TIME_RESPONSE
                else strip_amplitude_suffix(block.value_unit))
    return {
        "file_path": str(meta.get("file_path", "")),
        "file_name": str(meta.get("file_name", "")),
        "channel_index": int(meta.get("channel_index", 0)),
        "channel_name": str(channel_name),
        "channel_type": str(meta.get("channel_type", "general_dynamic")),
        "unit": str(unit),
    }


@dataclass(frozen=True)
class ResultSetLanding:
    """What a landed result-set read leaves to draw: ``to_draw`` curves, and
    how many held live curves the set ``adopted`` instead (#116)."""

    to_draw: List[Dict[str, Any]]
    adopted: int


@dataclass(frozen=True)
class PendingRestore:
    """What a graph gets back once its next base curve lands.

    Three states, told apart by name rather than by whether something is set:

    * ``NOTHING_PENDING`` -- a fresh open. The graph and its title are left alone.
    * ``from_refresh`` with no ``overlays`` -- a Refresh that had no overlay
      to re-drop: the tab title catches up.
    * ``overlays`` / ``result_set_ids`` -- re-drop these channel drop
      descriptors and load these result sets again, whether a Refresh or a
      reopened tab asked for them. Either can be set without the other.
    """

    overlays: Tuple[Dict[str, Any], ...] = ()
    result_set_ids: Tuple[str, ...] = ()
    from_refresh: bool = False


NOTHING_PENDING = PendingRestore()


def _overlay_key(descriptor: Dict[str, Any]) -> tuple:
    # The same identity a channel drop dedupes on (orchestration's drop_key).
    return build_channel_key(descriptor.get("file_path", ""), descriptor.get("channel_index", 0))


def _same_drawing(before: Optional[VisibleTraces], after: VisibleTraces) -> bool:
    """Whether two visibility decisions put the same picture on screen: the
    same curves in the same order, hidden for the same reason and counts."""
    return (
        before is not None
        and len(before.draw) == len(after.draw)
        and all(old is new for old, new in zip(before.draw, after.draw))
        and (before.hidden_reason, before.total, before.mask_passed, before.third_axis_dropped)
        == (after.hidden_reason, after.total, after.mask_passed, after.third_axis_dropped)
    )


def _weak_listener(callback: Optional[Callable[..., Any]]) -> Optional[Callable[..., Any]]:
    """Wraps a bound-method listener weakly so passing it does not form a circular reference."""
    if isinstance(callback, types.MethodType):
        method = weakref.WeakMethod(callback)

        def call(*args: Any, **kwargs: Any) -> Any:
            bound = method()
            return bound(*args, **kwargs) if bound is not None else None
        return call
    return callback


@dataclass
class _Batch:
    """What an open ``coalesce_changes`` block has gathered so far.

    ``pens`` are the held curves' pens, kept across the block's appends so a
    set of N curves picks its pens in O(N), not O(N^2) (#442); any other
    write drops them."""

    held_before: int
    changed: bool = False
    first_curve: bool = False
    pens: Optional[HeldPens] = None


class GraphCurves:
    """Which curves one graph holds, and every change to them."""

    def __init__(self, on_change: Optional[Callable[[CurvesChange], None]] = None) -> None:
        self._on_change = _weak_listener(on_change)
        self._model: Optional[PlotModel] = None
        self._mask: Mask = None
        self._visible: Optional[VisibleTraces] = None
        self._overlay_count: int = 0
        self._holds_result_content: bool = False
        self._loaded_result_set_ids: FrozenSet[str] = frozenset()
        self._pending_result_set_ids: FrozenSet[str] = frozenset()
        self._applied_mask_key: Optional[tuple] = None
        self._awaited_restore: PendingRestore = NOTHING_PENDING
        self._batch: Optional[_Batch] = None

    # ------------------------------------------------------------------ reads

    @property
    def model(self) -> Optional[PlotModel]:
        """The snapshot a dock draws. Read-only by contract, not by copy."""
        return self._model

    @property
    def is_empty(self) -> bool:
        return self._model is None or not self._model.traces

    @property
    def trace_filter(self) -> Mask:
        return self._mask

    @property
    def applied_mask_key(self) -> Optional[tuple]:
        """The staleness key the Filters panel last applied ``trace_filter``
        under, set together with it by ``set_trace_filter``."""
        return self._applied_mask_key

    @property
    def visible(self) -> Optional[VisibleTraces]:
        """The visibility decision behind what is drawn, or None before any."""
        return self._visible

    @property
    def overlay_count(self) -> int:
        """How many overlay curves are drawn."""
        return self._overlay_count

    @property
    def holds_result_content(self) -> bool:
        """Whether a result set was ever loaded onto this graph. Stays True
        after every one of them is unloaded again."""
        return self._holds_result_content

    @property
    def loaded_result_set_ids(self) -> FrozenSet[str]:
        return self._loaded_result_set_ids

    @property
    def pending_result_set_ids(self) -> FrozenSet[str]:
        """Result sets whose read has been queued but has not landed yet."""
        return self._pending_result_set_ids

    @property
    def loaded_or_pending_result_set_ids(self) -> FrozenSet[str]:
        """Loaded ids plus ones still queued -- what a second tick, or the
        Result Pool checkbox, must treat as already accounted for."""
        return self._loaded_result_set_ids | self._pending_result_set_ids

    def visible_traces(self) -> List[Trace]:
        """The curves drawn right now, through the Trace filter mask."""
        return list(self._visible.draw) if self._visible is not None else []

    def all_traces(self) -> List[Trace]:
        """Every curve that could be drawn if the Trace filter let all of them
        through -- the X-domain fit and the third-axis drop still apply."""
        if self._model is None:
            return []
        return list(resolve_visible_traces(self._model, None, self._model.x_domain).draw)

    @property
    def base_trace(self) -> Optional[Trace]:
        """The base curve (the one flagged ``is_base``), or None when empty."""
        if self.is_empty:
            return None
        return self._model.traces[_base_trace_index(self._model)]

    def descriptors(self) -> List[Dict[str, Any]]:
        """``build_trace_descriptor`` for every curve held, hidden ones included."""
        if self._model is None:
            return []
        return [build_trace_descriptor(t) for t in self._model.traces]

    def overlay_traces(self) -> List[Trace]:
        """Every overlay curve that can be dropped again, once per channel.

        The base curve is left out -- the graph recomputes it itself -- and so
        is every other curve of the base channel: an "orders" graph draws one
        curve per extracted order, and only order 1 is flagged is_base (#379).
        Overlays are deduplicated by the same (file_path, channel_index): one
        re-drop already asks for every configured order. An h5 result-set
        curve has no file_path/channel_index to re-drop; it comes back by its
        id (``PendingRestore.result_set_ids``, §1.31) instead."""
        if self._model is None:
            return []
        # A base curve with no file_path (raw arrays, or one read off a result
        # set) names no channel, so it cannot claim an overlay that also lacks
        # one. A live base curve adopted into a result set still has its.
        seen = {
            _overlay_key(trace.meta_ref) for trace in self._model.traces
            if trace.is_base and trace.meta_ref and trace.meta_ref.get("file_path")
        }
        overlays = []
        for trace in self._model.traces:
            if trace.is_base or trace.result_set_id or not trace.meta_ref:
                continue
            key = _overlay_key(trace.meta_ref)
            if key in seen:
                continue
            seen.add(key)
            overlays.append(trace)
        return overlays

    def overlay_drop_descriptors(self) -> List[Dict[str, Any]]:
        """The channel-drop payload of every ``overlay_traces`` curve, so a
        re-drop puts it back the way the user did."""
        return [_build_channel_drop_descriptor(trace) for trace in self.overlay_traces()]

    def channel_drop_descriptors(self) -> List[Dict[str, Any]]:
        """The channel-drop payload of every curve held that has a source
        channel, base included -- what a drag out of the graph carries."""
        if self._model is None:
            return []
        return [_build_channel_drop_descriptor(t) for t in self._model.traces if t.meta_ref]

    # -------------------------------------------------------- pending restore

    def begin_refresh(self) -> None:
        """A Refresh is in flight: when its base curve lands, whatever overlays
        and result sets are on screen then come back
        (``capture_overlays_before_reset``).
        Nothing is captured now -- a channel dropped during the flight would
        miss it and vanish (#285). A saved restore still pending is kept."""
        self._awaited_restore = replace(self._awaited_restore, from_refresh=True)

    def expect_saved_restore(
        self, *, overlays: Iterable[Dict[str, Any]], result_set_ids: Iterable[str],
    ) -> None:
        """A tab reopened from a saved project gets ``overlays`` re-dropped and
        ``result_set_ids`` loaded once its base curve lands."""
        self._awaited_restore = replace(
            self._awaited_restore,
            overlays=tuple(overlays),
            result_set_ids=tuple(result_set_ids),
        )

    def capture_overlays_before_reset(self) -> None:
        """Add the overlays held right now, and the result sets loaded, to the
        pending restore, just before a landing base curve resets the graph to
        itself alone.

        A no-op when nothing is pending (a fresh open keeps nothing). Merged by
        channel rather than replaced, so a saved restore's overlays and the
        ones on screen both come back, once. An overlay removed during a
        Refresh is not held any more and so is not captured.

        The loaded result sets stop counting as loaded here: the reset takes
        their curves off the graph, and a set still counted would be skipped
        by the very load that brings it back (#427)."""
        if self._awaited_restore == NOTHING_PENDING:
            return
        merged = list(self._awaited_restore.overlays)
        seen = {_overlay_key(d) for d in merged}
        for descriptor in self.overlay_drop_descriptors():
            if _overlay_key(descriptor) not in seen:
                seen.add(_overlay_key(descriptor))
                merged.append(descriptor)
        awaited_ids = self._awaited_restore.result_set_ids
        result_set_ids = awaited_ids + tuple(sorted(self._loaded_result_set_ids - set(awaited_ids)))
        self._loaded_result_set_ids = frozenset()
        self._awaited_restore = replace(
            self._awaited_restore, overlays=tuple(merged), result_set_ids=result_set_ids,
        )

    def take_pending_restore(self) -> PendingRestore:
        """What to give back now that the base curve landed; nothing is pending
        afterwards."""
        restore, self._awaited_restore = self._awaited_restore, NOTHING_PENDING
        return restore

    def abort_restore(self) -> None:
        """The recompute will not land: forget the pending restore, or the next
        unrelated base curve would re-drop it (audit 02, S3/3.9)."""
        self._awaited_restore = NOTHING_PENDING

    # ----------------------------------------------------------------- writes

    def replace(self, model: PlotModel) -> None:
        """Hold ``model`` instead of whatever was there."""
        first_curve = self.is_empty
        self._model = model
        self._resolve()
        self._notify(CurvesReplaced(first_curve=first_curve))

    def show_blocks(
        self,
        blocks: Sequence[Any],
        settings: DisplaySettings = DisplaySettings(),
    ) -> None:
        """Show ``blocks`` as the graph's new base, dropping every curve held.

        The first block's kind decides how the graph is built: a spectrum, the
        cuts of one order-tracking run, an Overall Level curve, or otherwise a
        time record, in ``settings``; every further block is an overlay. The
        overlays on screen and the result sets loaded are captured first
        (``capture_overlays_before_reset``), so a pending Refresh or saved
        restore gets them back once this lands."""
        self.capture_overlays_before_reset()
        first = blocks[0]
        if getattr(first, "kind", None) == KIND_ORDER_CUT:
            # Any other kind riding along (the Overall Level and Residual curves, ADR §1.141) is an
            # overlay built by its own kind's rule.
            is_cut = [getattr(b, "kind", None) == KIND_ORDER_CUT for b in blocks]
            cuts = [b for b, cut in zip(blocks, is_cut) if cut]
            self.replace(build_order_cuts_model(cuts, settings.prefs, amplitude_mode=settings.amplitude_mode))
            for block in (b for b, cut in zip(blocks, is_cut) if not cut):
                self.add_curve(block=block, settings=settings)
            return
        self.replace(build_base_model(
            first, settings,
            x=first.primary_axis.values.astype(np.float64),
            y=first.values.astype(np.float64),
            source_label=first.name,
            incoming_unit=first.value_unit,
            source_meta=first.display_meta(),
        ))
        for block in blocks[1:]:
            self.add_curve(block=block, settings=settings)

    def add_curve(
        self,
        *,
        x: Optional[np.ndarray] = None,
        y: Optional[np.ndarray] = None,
        source_label: str = "",
        incoming_unit: str = "",
        source_meta: Optional[Dict[str, Any]] = None,
        compute_spec: Optional[Dict[str, Any]] = None,
        x_quantity: str = "",
        result_set_id: str = "",
        block: Optional[Any] = None,
        settings: DisplaySettings = DisplaySettings(),
        title: Optional[str] = None,
    ) -> Trace:
        """Add one curve to the graph, deciding itself whether it becomes the
        base curve or an overlay (CONTEXT.md "Graph curves", #272, #276).

        When empty, creates the base curve and a fresh PlotModel, notifying
        CurvesReplaced(first_curve=True) so the dock sets up axes and grid.
        When not empty, appends an overlay curve with carousel pen and
        secondary axis routing, notifying CurveAppended.
        """
        if block is not None:
            x = block.primary_axis.values if x is None else x
            y = block.values if y is None else y
            incoming_unit = incoming_unit or block.value_unit
            source_meta = block.display_meta() if source_meta is None else source_meta
            source_label = source_label or block.name
        curve = dict(x=x, y=y, source_label=source_label, incoming_unit=incoming_unit,
                     source_meta=source_meta, compute_spec=compute_spec, x_quantity=x_quantity)

        if self.is_empty:
            model = build_base_model(block, settings, result_set_id=result_set_id, title=title, **curve)
            self.replace(model)
            return model.traces[0]

        return self._add_overlay(
            **curve,
            prefs=settings.prefs,
            result_set_id=result_set_id,
            block=block,
            spectrum_format=settings.spectrum_format,
            spectrum_amplitude_mode=settings.spectrum_amplitude_mode,
            spectrum_decibel_scale=settings.decibel_scale,
            amplitude_mode=settings.amplitude_mode,
        )

    @contextmanager
    def coalesce_changes(self) -> Iterator[None]:
        """Every change made inside the block reaches ``on_change`` as one, at
        the end: ``CurvesReplaced`` (``first_curve`` kept if any change had it),
        or ``CurvesCleared`` when no model is left. A result set of thousands of
        curves is drawn once instead of once per curve (#440). Nested blocks
        fold into the outermost one."""
        if self._batch is not None:
            yield
            return
        batch = self._batch = _Batch(held_before=self._held_count())
        try:
            yield
        finally:
            self._batch = None
            if batch.changed:
                if self._model is None:
                    self._notify(CurvesCleared())
                else:
                    self._resolve()
                    self._notify(CurvesReplaced(
                        first_curve=batch.first_curve,
                        curves_added=self._held_count() > batch.held_before,
                    ))

    def clear(self) -> None:
        """Drop every curve. The mask, the applied mask key and the result-set
        bookkeeping outlive it -- they describe the graph, not its curves."""
        self._model = None
        self._visible = None
        self._overlay_count = 0
        self._notify(CurvesCleared())

    def set_trace_filter(self, mask: Mask, *, key: Optional[tuple] = None) -> None:
        """Draw through ``mask`` (None = no mask), applied under ``key``. The
        curves themselves stay. A mask that leaves the same curves drawn is
        not reported: the picture would be redrawn identically (#505)."""
        self._mask = mask
        self._applied_mask_key = key
        if self._model is None:
            return
        before = self._visible
        self._resolve()
        if _same_drawing(before, self._visible):
            return
        self._notify(CurvesReplaced())

    def _add_overlay(self, **overlay: Any) -> Trace:
        """Build one overlay curve and append it, checked against what is
        already drawn instead of re-resolving the whole list.

        ``overlay`` is ``build_scaled_overlay_trace``'s keyword arguments minus
        the model and the overlay index, which come from here. The curve is
        held even when hidden: hiding is a property of the view. Inside a
        ``coalesce_changes`` block it is only appended -- the block's end
        resolves what is drawn once for the whole batch."""
        batch = self._batch
        pens = batch.pens if batch is not None and batch.pens is not None else self._collect_pens()

        trace = build_scaled_overlay_trace(
            self._model, overlay_index=pens.free_index(), **overlay,
        )
        self._model.traces.append(trace)

        if batch is not None:
            if trace.pen is not None:
                pens.hold(trace.pen.color, trace.pen.style)
            batch.pens = pens
            batch.changed = True
            return trace

        outcome = self._visible.accepts(trace, self._mask, self._model.x_domain)
        if outcome is AcceptOutcome.NEEDS_RENDER:
            self._resolve()
        elif outcome is AcceptOutcome.DRAWN:
            self._overlay_count += 1
        self._notify(CurveAppended(trace=trace, outcome=outcome))
        return trace

    def rebuild_units(self, prefs: UnitPreferences) -> None:
        """Every curve again in the display units of ``prefs``, from its raw data."""
        if self._model is not None:
            self.replace(rebuild_with_units(self._model, prefs))

    def rebuild_domain(self, to_quantity: str) -> None:
        """Every curve again against the X quantity ``to_quantity``, projected
        from its raw X; one that cannot be projected is held but not drawn."""
        if self._model is not None:
            self.replace(rebuild_with_domain(self._model, to_quantity))

    def rebuild_spectrum_display(self, settings: DisplaySettings) -> None:
        """Every spectrum curve again in a Format x Amplitude, from canonical power."""
        if self._model is not None:
            self.replace(rebuild_spectrum_with_display_settings(
                self._model,
                spectrum_format=settings.spectrum_format,
                amplitude_mode=settings.spectrum_amplitude_mode,
                decibel_scale=settings.decibel_scale,
                prefs=settings.prefs,
            ))

    def rebuild_amplitude_display(self, settings: DisplaySettings) -> None:
        """Every order cut / Overall Level curve again in an amplitude mode."""
        if self._model is not None:
            self.replace(rebuild_amplitude_mode_display(
                self._model, amplitude_mode=settings.amplitude_mode, prefs=settings.prefs,
            ))

    def remove_overlays(self, matches: Callable[[Trace], bool]) -> None:
        """Drop every held overlay curve ``matches`` accepts, keeping the base
        curve and everything else untouched -- a no-op redraw when nothing
        matches. The caller re-adds the dropped curves through whatever gets
        them a real recompute (``add_curve`` or a channel-drop path); this
        only ever removes."""
        if self._model is None:
            return
        kept = [t for t in self._model.traces if t.is_base or not matches(t)]
        if len(kept) == len(self._model.traces):
            return
        self._model.traces = kept
        self._resolve()
        self._notify(CurvesReplaced())

    def request_result_sets(self, ids: Iterable[str]) -> None:
        """A read of ``ids`` has been queued: they count as accounted for
        (loaded_or_pending_result_set_ids) until ``land_result_set`` or
        ``abandon_result_sets`` -- so a second tick while the first is still
        queued submits nothing new, and an untick before it lands can still
        cancel it. The graph owns the whole lifecycle request -> land /
        abandon -> unload (ADR §1.104)."""
        self._holds_result_content = True
        self._pending_result_set_ids = self._pending_result_set_ids | frozenset(ids)

    def land_result_set(
        self,
        ref_id: str,
        curves: List[Dict[str, Any]],
        split_held: Callable[[List[Dict[str, Any]], List[Trace]], Tuple[List[Trace], List[Dict[str, Any]]]],
    ) -> Optional["ResultSetLanding"]:
        """The read of ``ref_id`` delivered ``curves``. None when it is no longer
        pending (unticked, or the graph's content cleared, before it landed:
        the user's later decision wins). Otherwise the set is stamped loaded and
        no longer pending, a held live curve it also carries joins it (#116,
        ``split_held`` -> (already_shown, to_draw)), and the caller draws
        ``to_draw``.

        Stamped *before* returning, hence before any curve is drawn: a draw
        repaints the Result Pool checkbox synchronously, and it must already
        read the set as loaded or the tick flips back off."""
        if ref_id not in self._pending_result_set_ids:
            return None
        self._loaded_result_set_ids = self._loaded_result_set_ids | {ref_id}
        self._pending_result_set_ids = self._pending_result_set_ids - {ref_id}
        held = self._model.traces if self._model is not None else []
        already_shown, to_draw = [], list(curves)
        if any(not trace.result_set_id for trace in held):
            already_shown, to_draw = split_held(to_draw, held)
        self._adopt_into_result_set(already_shown, ref_id)
        return ResultSetLanding(to_draw=list(to_draw), adopted=len(already_shown))

    def abandon_result_sets(self, ids: Iterable[str]) -> None:
        """Queued reads of ``ids`` failed or were cancelled."""
        self._pending_result_set_ids = self._pending_result_set_ids - set(ids)

    def unload_result_sets(self, ref_ids: Iterable[str]) -> bool:
        """Forget ``ref_ids`` (loaded and queued) and drop every curve read
        from them (Trace.result_set_id) -- the base curve too, since a loaded
        curve can become the base one; the first curve left takes its place.
        True when that leaves the graph without a curve: the curves are left
        as they were and the caller empties the canvas rather than rendering
        a model with none."""
        ids = set(ref_ids)
        self._loaded_result_set_ids = self._loaded_result_set_ids - ids
        self._pending_result_set_ids = self._pending_result_set_ids - ids
        if self._model is None:
            return False
        kept = traces_kept_after_unload(self._model.traces, ids)
        if len(kept) == len(self._model.traces):
            return False
        if not kept:
            return True
        if not any(t.is_base for t in kept):
            kept = [replace(kept[0], is_base=True, axis="primary"), *kept[1:]]
        self._model.traces = kept
        self._resolve()
        self._notify(CurvesReplaced())
        return False

    def mark_holds_result_content(self) -> None:
        """Marks this graph as a result-content dock without touching which
        sets are loaded or pending -- for the call that queues zero new reads
        (everything asked for is already loaded or pending) but must still
        flip channel_drop's multi-source treatment on (ARCHITECTURE_DECISIONS
        §1.30/§1.31)."""
        self._holds_result_content = True

    def _adopt_into_result_set(self, traces: Iterable[Trace], result_set_id: str) -> None:
        """Count the held curves ``traces`` as read from ``result_set_id``
        from now on, their data and pens untouched -- for curves computed
        live that a result set being loaded holds too (#116). They then leave
        the graph with that set (``unload_result_sets``) like any curve read
        from it. A no-op when none of ``traces`` is held."""
        if self._model is None:
            return
        adopted = {id(trace) for trace in traces}
        kept = [
            replace(held, result_set_id=result_set_id) if id(held) in adopted else held
            for held in self._model.traces
        ]
        if all(new is old for new, old in zip(kept, self._model.traces)):
            return
        self._model.traces = kept
        self._resolve()
        self._notify(CurvesReplaced())

    # --------------------------------------------------------------- internal

    def _held_count(self) -> int:
        return len(self._model.traces) if self._model is not None else 0

    def _collect_pens(self) -> HeldPens:
        """The pens of every held curve, from a full scan."""
        pens = HeldPens()
        for t in self._model.traces:
            if t.pen is not None:
                pens.hold(t.pen.color, t.pen.style)
        return pens

    def _resolve(self) -> None:
        self._visible = resolve_visible_traces(self._model, self._mask, self._model.x_domain)
        self._overlay_count = sum(1 for t in self._visible.draw if not t.is_base)

    def _notify(self, change: CurvesChange) -> None:
        batch = self._batch
        if batch is not None:
            batch.changed = True
            batch.first_curve |= isinstance(change, CurvesReplaced) and change.first_curve
            batch.pens = None  # a write other than _add_overlay's append
            return
        if self._on_change is not None:
            self._on_change(change)
