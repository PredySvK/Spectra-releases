"""Background worker payloads for channels dropped onto live analysis docks."""

import time

from core.block_kinds import KIND_OVERALL_LEVEL, PARAM_ORDER
from io_modules.data_accessor import DataAccessor
from orchestration.live_compute._file_tracking import FileTracking
from orchestration.live_compute._order_cut_cache import (
    find_cached_order_cuts, rebuild_cached_order_blocks,
)
from signal_processing.result_blocks import (
    compute_order_cuts,
    compute_overall_level,
    compute_spectrum,
    build_overall_level_missing_line,
)


def read_simple_drops(prepared, spectrum_config, progress_fn=None):
    """Read dropped channels and, when requested, compute their spectra."""
    rendered, log_lines = [], []
    for position, (desc, mock_run, mock_meta) in enumerate(prepared):
        # Channels finished so far; the last is counted when the task returns.
        if progress_fn is not None and position:
            progress_fn(position, len(prepared))
        try:
            io_start = time.perf_counter()
            data_block = DataAccessor.fetch_channel_data(mock_run, mock_meta)
            io_time = time.perf_counter() - io_start

            spectrum_block, dsp_time = None, 0.0
            if spectrum_config is not None:
                dsp_start = time.perf_counter()
                spectrum_block = compute_spectrum(data_block, spectrum_config)
                dsp_time = time.perf_counter() - dsp_start

            rendered.append((desc, data_block, spectrum_block, io_time, dsp_time))
        except Exception as error:
            log_lines.append(
                f"ERROR: Dropped channel processing failed for "
                f"{desc.get('channel_name', 'Unknown')}: {error}"
            )
    return rendered, log_lines


def lookup_or_compute_order_drops(
    prepared, project_session, config, config_dict, dock_tacho, dock_tacho_path,
    use_cache: bool = True, with_overall_level: bool = False, progress_fn=None,
):
    """Load cached order cuts or read and compute them for one dropped batch.

    `with_overall_level` computes every channel with its Overall Level and
    Residual curves, never from the cache (ADR §1.141 point 10); each block
    rides as one more row."""
    rendered, log_lines = [], []
    tracking = FileTracking()
    tracking.seed_tacho(dock_tacho_path, dock_tacho)
    for position, (desc, ch_name, mock_run, mock_meta, tacho_meta) in enumerate(prepared):
        # Channels finished so far; the last is counted when the task returns.
        if progress_fn is not None and position:
            progress_fn(position, len(prepared))
        try:
            cached = None
            if use_cache and not with_overall_level and project_session is not None:
                cached = find_cached_order_cuts(
                    project_session.find_cached_result_background, desc["file_path"], ch_name,
                    mock_meta, config_dict, config.orders_to_extract,
                )
            if cached is not None:
                live_blocks = rebuild_cached_order_blocks(cached)
                rpm_axis = live_blocks[0].primary_axis.values
                unit = live_blocks[0].value_unit
                order_rows = [
                    (order, rpm_axis, block.values, unit, block)
                    for order, block in zip(config.orders_to_extract, live_blocks)
                ]
                metadata = DataAccessor.build_display_meta(mock_run, mock_meta)
                rendered.append((
                    desc, ch_name, cached.result_set_label, order_rows, metadata, None, None,
                ))
                continue

            io_start = time.perf_counter()
            data_block = DataAccessor.fetch_channel_data(mock_run, mock_meta)
            run_tacho = tracking.tacho_for(desc["file_path"], mock_run, tacho_meta)
            io_time = time.perf_counter() - io_start

            dsp_start = time.perf_counter()
            order_blocks = compute_order_cuts(
                data_block, run_tacho, config,
                scratch=tracking.scratch_for(desc["file_path"]),
                with_overall_level=with_overall_level,
            )
            dsp_time = time.perf_counter() - dsp_start
            missing = build_overall_level_missing_line(order_blocks) if with_overall_level else None
            if missing:
                log_lines.append(missing)

            # The Overall Level and Residual rows carry no order number: their key is None.
            order_rows = [
                (result_block.provenance.params.get(PARAM_ORDER), result_block.primary_axis.values,
                 result_block.values, result_block.value_unit, result_block)
                for result_block in order_blocks
            ]
            rendered.append((
                desc, ch_name, None, order_rows, data_block.display_meta(), io_time, dsp_time,
            ))
        except Exception as error:
            log_lines.append(f"ERROR: Dropped channel processing failed for {ch_name}: {error}")
    return rendered, log_lines


def build_overall_level_drop_payloads(
    prepared, use_cache, finder, config, config_dict, against_time, dock_tacho, dock_tacho_path,
    progress_fn=None,
):
    """Load cached Overall Level blocks or compute them for one dropped batch."""
    rendered, log_lines = [], []
    tracking = FileTracking()
    tracking.seed_tacho(dock_tacho_path, dock_tacho)
    for position, (desc, ch_name, mock_run, mock_meta, tacho_meta) in enumerate(prepared):
        if progress_fn is not None and position:
            progress_fn(position, len(prepared))
        try:
            if use_cache and finder is not None:
                cached_block = finder(
                    desc["file_path"], ch_name, KIND_OVERALL_LEVEL, config_dict,
                    channel_index=getattr(mock_meta, "index", None),
                )
                if cached_block is not None:
                    label = cached_block.metadata.get("result_set_label", "")
                    rendered.append((desc, ch_name, label, cached_block, None, None))
                    continue

            io_start = time.perf_counter()
            data_block = DataAccessor.fetch_channel_data(mock_run, mock_meta)
            run_tacho = None
            if not against_time:
                run_tacho = tracking.tacho_for(desc["file_path"], mock_run, tacho_meta)
            io_time = time.perf_counter() - io_start

            dsp_start = time.perf_counter()
            result_block = compute_overall_level(
                data_block, run_tacho, config,
                scratch=tracking.scratch_for(desc["file_path"]),
            )
            dsp_time = time.perf_counter() - dsp_start

            rendered.append((desc, ch_name, None, result_block, io_time, dsp_time))
        except Exception as error:
            log_lines.append(f"ERROR: Dropped channel processing failed for {ch_name}: {error}")
    return rendered, log_lines
