"""Background worker payloads for channels dropped onto live analysis docks."""

import dataclasses
from typing import Any, Dict, Optional

from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTRUM
from core.channel_drop import TAB_CACHE_KEY
from io_modules.data_accessor import DataAccessor
from orchestration.live_compute._cache_hit import build_curve_subject
from orchestration.live_compute._file_tracking import FileTracking
from orchestration.live_compute._live_result import (
    LiveFailure, LiveRequest, run_live_compute,
)
from orchestration.live_compute._restore_config import RestoreConfig, build_restore_config_line
from orchestration.tab_cache import resolve_tab_cache_read_path


@dataclasses.dataclass(frozen=True)
class DropRestore:
    """
    What the restored overlays of one drop task bring along:
    `project_path` finds the Tab cache file each descriptor names
    (`TAB_CACHE_KEY`), read before anything is computed; `resolved` is the
    saved recipe the task's config came from, said in one line per channel
    -- only when that channel is computed after all. `subject` names the
    analysis in that line ("Spectrum").
    """
    project_path: Optional[str] = None
    subject: str = ""
    resolved: Optional[RestoreConfig] = None

    def request_fields(self, desc, channel_name: str) -> Dict[str, Any]:
        """The `LiveRequest` fields of one restored descriptor."""
        notices = ()
        if self.resolved is not None:
            notices = (build_restore_config_line(build_curve_subject(self.subject, channel_name), self.resolved),)
        return {
            "tab_cache_path": resolve_tab_cache_read_path(self.project_path, desc.get(TAB_CACHE_KEY)),
            "compute_notices": notices,
        }


def _restore_fields(restore: Optional[DropRestore], desc, channel_name: str) -> Dict[str, Any]:
    return restore.request_fields(desc, channel_name) if restore is not None else {}


def read_simple_drops(prepared, spectrum_config, finder=None, progress_fn=None, *,
                      restore: Optional[DropRestore] = None):
    """
    Read dropped channels and, with a `spectrum_config`, make their spectra:
    one `run_live_compute` per channel, so a spectrum the result-set cache
    already holds reads nothing (`finder`, None to skip the cache), nor one a
    restored overlay finds in its Tab cache file (`restore`).

    Returns `(rendered, log_lines)`; a row is `(desc, data_block,
    spectrum_result)` -- `data_block` the raw channel read (None for a hit),
    `spectrum_result` the spectrum's `LiveResult`, None without a
    `spectrum_config`.
    """
    rendered, log_lines = [], []
    for position, (desc, mock_run, mock_meta) in enumerate(prepared):
        # Channels finished so far; the last is counted when the task returns.
        if progress_fn is not None and position:
            progress_fn(position, len(prepared))
        failure = None
        if spectrum_config is None:
            try:
                rendered.append((desc, DataAccessor.fetch_channel_data(mock_run, mock_meta), None))
            except Exception as error:
                failure = error
        else:
            result = run_live_compute(LiveRequest(
                run_index=mock_run, channel_meta=mock_meta, block_kind=KIND_SPECTRUM,
                config=spectrum_config,
                **_restore_fields(restore, desc, desc.get("channel_name", "")),
            ), finder)
            log_lines.extend(result.notices)
            if isinstance(result, LiveFailure):
                failure = result.message
            else:
                rendered.append((desc, result.vib_block, result))
        if failure is not None:
            log_lines.append(
                f"ERROR: Dropped channel processing failed for "
                f"{desc.get('channel_name', 'Unknown')}: {failure}"
            )
    return rendered, log_lines


def run_order_drops(prepared, finder, config, dock_tacho, dock_tacho_path,
                                  with_overall_level=False, progress_fn=None, *,
                                  restore: Optional[DropRestore] = None):
    """
    The order cuts of one dropped batch, one `run_live_compute` per channel.
    `with_overall_level` adds each channel's Overall Level and Residual
    curves -- and then nothing comes from the cache (ADR §1.141 point 10,
    decided inside `run_live_compute`).
    """
    return _run_live_drops(prepared, finder, config, KIND_ORDER_CUT, dock_tacho, dock_tacho_path,
                           progress_fn, with_overall_level=with_overall_level, restore=restore)


def run_overall_level_drops(prepared, finder, config, dock_tacho, dock_tacho_path,
                                      progress_fn=None, *, restore: Optional[DropRestore] = None):
    """The Overall Level of one dropped batch, one `run_live_compute` per channel."""
    if config.tracking_mode == "time":
        dock_tacho = None
    return _run_live_drops(prepared, finder, config, KIND_OVERALL_LEVEL, dock_tacho, dock_tacho_path,
                           progress_fn, restore=restore)


def _run_live_drops(prepared, finder, config, block_kind, dock_tacho, dock_tacho_path,
                    progress_fn, with_overall_level=False, restore: Optional[DropRestore] = None):
    """
    `(rendered, log_lines)`: a `(desc, channel_name, LiveResult)` row per
    channel that landed, a log line per one that failed -- a failing channel
    does not take its siblings down. `finder` is a
    `ProjectSession.cache_finder` callable, None to skip the cache; `restore`
    is what restored overlays read first (their Tab cache files).
    """
    rendered, log_lines = [], []
    tracking = FileTracking()
    tracking.seed_tacho(dock_tacho_path, dock_tacho)
    for position, (desc, ch_name, mock_run, mock_meta, tacho_meta) in enumerate(prepared):
        # Channels finished so far; the last is counted when the task returns.
        if progress_fn is not None and position:
            progress_fn(position, len(prepared))
        result = tracking.run(LiveRequest(
            run_index=mock_run, channel_meta=mock_meta, block_kind=block_kind, config=config,
            with_overall_level=with_overall_level, tacho_meta=tacho_meta,
            **_restore_fields(restore, desc, ch_name),
        ), finder)
        log_lines.extend(result.notices)
        if isinstance(result, LiveFailure):
            log_lines.append(f"ERROR: Dropped channel processing failed for {ch_name}: {result.message}")
            continue
        rendered.append((desc, ch_name, result))
    return rendered, log_lines
