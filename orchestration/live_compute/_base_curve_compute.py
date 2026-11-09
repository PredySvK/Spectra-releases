"""The one owner of a tab's Base curve compute: start, landing, failure."""

from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from core.block_kinds import KIND_ORDER_CUT, resolve_clipped_f_stop
from core.channel_drop import TAB_CACHE_KEY
from core.models import READING_IMPORTED_RESULT, resolve_channel_reading
from io_modules.data_accessor import DataAccessor
from orchestration.live_compute._cache_hit import build_cache_hit_line, build_curve_subject
from orchestration.live_compute._compute_origin import (
    FAILURE_CLOSE_TAB,
    FAILURE_MARK_FAILED,
    FAILURE_MARK_MISSING,
    PHASE_COMPUTE,
    PHASE_READ,
    ComputeOrigin,
    plan_compute_failure,
)
from orchestration.live_compute._live_result import (
    LiveFailure,
    LiveRequest,
    LiveResult,
    run_live_compute,
)
from orchestration.live_compute._restore_config import (
    RestoreConfig,
    build_restore_config_line,
    resolve_restore_config,
)
from orchestration.tab_cache import (
    TabCacheCurve,
    build_tab_cache_hit_line,
    resolve_tab_cache_read_path,
)
from selection.channel_identity import build_channel_key
from session.data_pool import DeadLink
from signal_processing.result_blocks import UnevenRpmAxisError
from view_models.analysis_kinds import (
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_TIME,
    resolve_analysis_kind,
)


class BaseCurveTarget(Protocol):
    """What `BaseCurveCompute` needs from one open tab.

    The GUI implements it over a dock; a test implements it with a fake. The
    methods only do what they say to the tab: when and in what order is the
    compute's.
    """

    analysis_kind: str
    run_index: Any
    channel_meta: Any
    tacho_block: Any

    def show_status(self, text: str) -> None:
        """Puts `text` where the graph's title is."""

    def hold_read_channels(self, vib_block, tacho_block) -> None:
        """Keeps the raw channels the compute read, None for one it did not."""

    def draw(self, blocks: Sequence[Any]) -> None:
        """Draws the Base curve's blocks; may raise `UnevenRpmAxisError`."""

    def clear_compute_failed(self) -> None:
        """The tab loses the warning of an earlier failed compute, if it has one."""

    def take_pending_restore(self) -> Any:
        """What the tab gets back now its Base curve landed (`PendingRestore`)."""

    def abort_restore(self) -> None:
        """Nothing pending is given back by a later Base curve."""

    def load_result_sets(self, result_set_ids: Sequence[str]) -> None: ...

    def drop_overlays(self, overlays: Sequence[Mapping[str, Any]], *, from_refresh: bool) -> None:
        """Re-drops curves the graph already had."""

    def refresh_tab_label(self) -> None: ...

    def restored_spec(self) -> Any:
        """The saved `TabSpec` this tab was rebuilt from, None for any other."""

    def close(self) -> None:
        """The tab goes, without this counting as a Work change."""

    def show_dead_link(self, dead_link: DeadLink) -> None:
        """The tab becomes the "Missing" placeholder of `dead_link`."""

    def mark_compute_failed(self) -> None:
        """The tab stays live and carries the warning of a failed compute."""

    def base_recipe(self) -> Optional[Mapping[str, Any]]:
        """The Curve recipe the Base curve was computed with, None while it has none."""

    def dropped_curves(self, channel_key) -> List[Any]:
        """The curves dropped on this tab from that channel, an Adopted curve too."""


def _build_band_clamp_line(blocks) -> Optional[str]:
    """One log line when the requested F max was clipped to the file's Nyquist
   ."""
    clipped = resolve_clipped_f_stop(blocks[0])
    if clipped is None:
        return None
    requested, effective = clipped
    return (f"WORKSPACE: Overall Level F max clipped from {requested:g} Hz "
            f"to {effective:g} Hz (file's Nyquist).")


# What one Analysis kind logs once its Base curve has landed -- a row here, not a
# branch in `land`.
_LANDING_LINES: Dict[str, Callable[[Any], Optional[str]]] = {
    ANALYSIS_OVERALL_LEVEL: _build_band_clamp_line,
}


class BaseCurveCompute:
    """
    The whole life of one compute of a tab's Base curve, for every Analysis
    kind, on the GUI thread: `start` runs it on a dock task, what comes back
    goes through `land` or `fail`. A tab is addressed by its dock id, so a
    result that arrives after its tab closed goes nowhere (`find_target` answers
    None). `ComputeOrigin` -- why the compute in flight was started -- lives
    here and is only read when it fails.
    """

    def __init__(self, *,
                 find_target: Callable[[str], Optional[BaseCurveTarget]],
                 run_task: Callable[..., None],
                 ribbon_config: Callable[[str], Any],
                 cache_finder: Callable[[], Optional[Callable]],
                 with_order_overall_level: Callable[[], bool],
                 project_path: Callable[[], Optional[str]],
                 tab_cache_files: Any,
                 tracking_scratch: Any,
                 log: Callable[[str], None]):
        self._find_target = find_target
        self._run_task = run_task
        self._ribbon_config = ribbon_config
        self._cache_finder = cache_finder
        self._with_order_overall_level = with_order_overall_level
        self._project_path = project_path
        self._tab_cache_files = tab_cache_files
        self._tracking_scratch = tracking_scratch
        self._log = log
        self._origins: Dict[str, ComputeOrigin] = {}
        self._failure_watchers: List[Callable[[str], None]] = []

    # ---- start ----------------------------------------------------------
    def start(self, dock_id: str, *, origin: ComputeOrigin, vib_block=None) -> None:
        """
        Starts (or restarts) the compute of the tab's Base curve. A time tab or
        an Imported result is only read; it lands and fails like a computed
        curve. `vib_block` is the channel already read for a drop, so the
        compute does not read it again.
        """
        target = self._find_target(dock_id)
        if target is None:
            return
        if _is_only_read(target):
            self._start_read(dock_id, target, origin)
        else:
            self._start_compute(dock_id, target, origin, vib_block)

    def _start_read(self, dock_id: str, target: BaseCurveTarget, origin: ComputeOrigin) -> None:
        target.show_status("⏳ Loading...")
        self._origins[dock_id] = origin
        self._run_task(
            dock_id, DataAccessor.fetch_channel_data, target.run_index, target.channel_meta,
            on_success=lambda data_block: self.land(dock_id, LiveResult(blocks=(data_block,))),
            on_error=lambda message: self.fail(dock_id, message, phase=PHASE_READ),
        )

    def _start_compute(self, dock_id: str, target: BaseCurveTarget, origin: ComputeOrigin, vib_block) -> None:
        """The one background task -- cache lookup, read and DSP (ADR §1.84,
        §1.167) -- on the dock's `compute` slot, so a newer request or a closed
        dock drops it."""
        analysis_kind = resolve_analysis_kind(target.analysis_kind)
        config = self._ribbon_config(analysis_kind.name)
        tab_cache_path, compute_notices = None, ()
        if origin is ComputeOrigin.RESTORE:
            config, restore_line = self._restore_config(target)
            compute_notices = (restore_line,)
            tab_cache_path = resolve_tab_cache_read_path(
                self._project_path(), self._tab_cache_files.name(TabCacheCurve(dock_id)))

        target.show_status(analysis_kind.refresh_title if origin is ComputeOrigin.REFRESH else "⏳ Loading...")
        self._origins[dock_id] = origin
        request = LiveRequest(
            run_index=target.run_index,
            channel_meta=target.channel_meta,
            block_kind=analysis_kind.block_kind,
            config=config,
            # A refresh reuses the tacho the dock already holds; an open reads the file's.
            tacho_block=target.tacho_block if origin is ComputeOrigin.REFRESH else None,
            with_overall_level=analysis_kind.block_kind == KIND_ORDER_CUT and self._with_order_overall_level(),
            vib_block=vib_block,
            tab_cache_path=tab_cache_path,
            compute_notices=compute_notices,
        )
        self._run_task(
            dock_id, run_live_compute, request, self._cache_finder(), self._tracking_scratch,
            on_success=lambda result: self._land_computed(dock_id, result, origin),
            on_error=lambda message: self.fail(dock_id, message, phase=PHASE_READ),
        )

    def resolve_restore_config(self, analysis_kind: str, recipe) -> RestoreConfig:
        """
        The config a restored curve on a tab of `analysis_kind` computes with:
        its Curve recipe; the ribbon's config of that kind fills in only the
        display fields and an order tab's order list (ADR §1.178, §1.204 point
        5). The Base curve and every restored dropped channel resolve it here.
        """
        return resolve_restore_config(recipe, self._ribbon_config(analysis_kind))

    def _restore_config(self, target: BaseCurveTarget) -> Tuple[Any, str]:
        """A restored tab computes with its Base curve's saved Curve recipe -- or
        the ribbon, when the project saved none -- and one log line says which
       ; it is logged only if the curve is computed,
        not read from the Tab cache. Returns `(config, line)`."""
        spec = target.restored_spec()
        base = next((t for t in spec.traces if t.is_base), None) if spec is not None else None
        resolved = self.resolve_restore_config(target.analysis_kind, base.compute_spec if base is not None else None)
        return resolved.config, build_restore_config_line(_curve_subject(target), resolved)

    # ---- landing --------------------------------------------------------
    def land(self, dock_id: str, result) -> bool:
        """
        The one place a Base curve lands, for every kind: the tab takes the raw
        channels the compute read, the blocks are drawn, the kind's own line is
        logged and whatever the tab still has pending comes back. A `LiveFailure`
        goes to `fail` instead. True when the curve landed.
        """
        target = self._find_target(dock_id)
        if target is None:
            return False
        if isinstance(result, LiveFailure):
            for line in result.notices:
                self._log(line)
            self.fail(dock_id, result.message, phase=result.phase)
            return False
        if not result.blocks:
            self.fail(dock_id, "The computation produced no curve to draw.")
            return False

        for line in result.notices:
            self._log(line)
        target.hold_read_channels(result.vib_block, result.tacho_block)
        if result.from_cache:
            self._log(build_cache_hit_line(
                _curve_subject(target), result.result_set_label,
                what=resolve_analysis_kind(target.analysis_kind).cache_hit_settings))
        if result.from_tab_cache:
            self._log(build_tab_cache_hit_line(_curve_subject(target)))

        try:
            target.draw(result.blocks)
        except UnevenRpmAxisError as error:
            self.fail(dock_id, str(error))
            return False

        self._origins.pop(dock_id, None)
        target.clear_compute_failed()
        landing_line = _LANDING_LINES.get(target.analysis_kind)
        if landing_line is not None:
            line = landing_line(result.blocks)
            if line is not None:
                self._log(line)
        self._give_back_pending(target)
        return True

    def _give_back_pending(self, target: BaseCurveTarget) -> None:
        """
        What the tab still has pending as its Base curve landed: the overlays and
        result sets a Refresh captured, or a reopened tab's saved ones. A fresh
        open has nothing and is left alone; a Refresh with nothing to re-drop only
        has its Tab label catch up.

        Result sets first: queueing their read marks them pending, which is what
        a re-dropped channel reads its Parameter Set from.
        """
        restore = target.take_pending_restore()
        if restore.result_set_ids:
            target.load_result_sets(restore.result_set_ids)
        if restore.overlays:
            target.drop_overlays(restore.overlays, from_refresh=restore.from_refresh)
        elif restore.from_refresh:
            target.refresh_tab_label()

    def _land_computed(self, dock_id: str, result, origin: ComputeOrigin) -> None:
        """A computed tab's Base curve lands like every other one; then, when it
        came from a measurement, it is kept in the Tab cache. Being the path of a
        computed tab decides which tabs go there: a time tab or an Imported result
        is only read and never reaches it."""
        if not self.land(dock_id, result) or result.from_tab_cache:
            return
        target = self._find_target(dock_id)
        if target is None:
            return
        curve = TabCacheCurve(dock_id)
        self._tab_cache_files.keep(
            curve,
            channel_name=target.channel_meta.name if target.channel_meta is not None else "",
            blocks=result.blocks,
            recipe=target.base_recipe(),
            saved_name=self._tab_cache_files.name(curve) if origin is ComputeOrigin.RESTORE else None)

    def keep_dropped_channel(self, dock_id: str, descriptor, result) -> None:
        """
        A channel dropped on the tab and computed from its measurement -- a
        result-set hit too, so the tab outlives that set -- goes into the Tab cache
        like the Base curve; a restored one shown from its file keeps that file's
        name. A curve from a loaded result set never comes here and
        keeps being read from its set. A channel has one file, so a later drop that
        only added orders writes all the channel's curves to it, or reopening would
        lose the earlier ones.
        """
        target = self._find_target(dock_id)
        if target is None:
            return
        channel_key = build_channel_key(descriptor["file_path"], descriptor["channel_index"])
        curve = TabCacheCurve(dock_id, channel_key)
        dropped = target.dropped_curves(channel_key)
        self._tab_cache_files.keep(
            curve,
            channel_name=descriptor.get("channel_name", ""),
            blocks=[trace.block for trace in dropped if trace.block is not None] or result.blocks,
            recipe=dropped[0].compute_spec if dropped else None,
            from_tab_cache=result.from_tab_cache,
            saved_name=descriptor.get(TAB_CACHE_KEY) or self._tab_cache_files.name(curve))

    # ---- failure --------------------------------------------------------
    def fail(self, dock_id: str, message: str, *, phase: str = PHASE_COMPUTE) -> None:
        """
        The one step for a compute that will not land, for every kind: logs why,
        then does what `plan_compute_failure` says for how the compute was started
        and which `phase` failed.
        """
        for watcher in self._failure_watchers:
            watcher(message)
        target = self._find_target(dock_id)
        if target is None:
            self._log(f"ERROR [{dock_id}]: {message}")
            return

        origin = self._origins.pop(dock_id, None)
        self._log(f"ERROR: IO block read exception: {message}" if phase == PHASE_READ else f"ERROR: {message}")

        action = plan_compute_failure(origin, phase)
        restored = target.restored_spec()
        if action == FAILURE_CLOSE_TAB:
            target.close()
        elif action == FAILURE_MARK_MISSING and restored is not None:
            self._mark_unreadable(target, restored)
        elif action == FAILURE_MARK_FAILED and restored is not None:
            self._mark_failed(target, restored)
        else:
            # The recompute will not land: a pending restore left in place
            # would be re-dropped by the next unrelated Base curve (audit 02,
            # finding S3/3.9).
            target.abort_restore()
            target.show_status("Computation failed - see System Log")

    def _mark_unreadable(self, target: BaseCurveTarget, restored) -> None:
        """A restored tab whose file could not be read: the same "Missing"
        placeholder a `DeadLink` gets (#385). The pool snapshot still lists a file
        whose drive is not mounted this session, so the tab resolved live and only
        its read can tell. Dropping it would let the next Save write `open_tabs`
        without it, and it would never come back once the drive does."""
        base = restored.traces[0]
        target.show_status("Source file could not be read - see System Log")
        target.show_dead_link(DeadLink(base.source_id, base.channel_name, reason="file_unreadable"))
        self._log(f"WARNING: could not restore '{base.channel_name}' (file_unreadable).")

    def _mark_failed(self, target: BaseCurveTarget, restored) -> None:
        """A restored tab whose file read but whose compute failed (an empty
        Overall Level band, say). The file is fine, so this is no dead link: the tab
        stays live with its channel, Save keeps it with its saved overlays and
        result sets, and a Refresh with other settings lands it -- its pending
        restore is kept for that."""
        base = restored.traces[0]
        target.show_status("Computation failed - see System Log")
        target.mark_compute_failed()
        self._log(f"WARNING: could not restore '{base.channel_name}' (compute failed) -- "
                  f"change the settings and Refresh.")

    def watch_failures(self, watcher: Callable[[str], None]) -> Callable[[], None]:
        """`watcher` hears the message of every failed compute from now on, until
        the returned callable is called (a Benchmark counts them, ADR §1.167: a
        live compute returns its failure, so its job ends DONE)."""
        self._failure_watchers.append(watcher)
        return lambda: self._failure_watchers.remove(watcher)

    # ---- state ----------------------------------------------------------
    def origin_in_flight(self, dock_id: str) -> Optional[ComputeOrigin]:
        """Why the compute in flight for the tab was started; None when none is."""
        return self._origins.get(dock_id)

    def forget(self, dock_id: str) -> None:
        """The tab closed: what it had in flight has nowhere to land."""
        self._origins.pop(dock_id, None)


def _curve_subject(target: BaseCurveTarget) -> str:
    channel_name = target.channel_meta.name if target.channel_meta is not None else ""
    return build_curve_subject(resolve_analysis_kind(target.analysis_kind).display_name, channel_name)


def _is_only_read(target: BaseCurveTarget) -> bool:
    return target.analysis_kind == ANALYSIS_TIME or (
        target.channel_meta is not None
        and resolve_channel_reading(target.channel_meta) == READING_IMPORTED_RESULT)
