# =====================================================================
# FILE: signal_processing/result_blocks.py
# =====================================================================
"""
Single synchronous path for turning a loaded time-domain block into a spectrum,
spectrogram, order cut, or Overall Level.

The asynchronous callers (a live view's `run_live_compute`, FileProcessingWorker)
run these functions on worker threads so the UI does not block; neither they nor
the batch save controller duplicate the parameter extraction, units, or
construction logic here.

Every function here accepts NVHDataBlock and returns NVHDataBlock (or a list of
them). None of them knows about UI state, QWidget, or the project session.

History: before this file existed, compute_spectrogram,
compute_single_sided_spectrum and compute_order_cuts_from_raw were always
called with loose numpy arrays. Three separate places each extracted the arrays
from the block, converted the tacho, looked up fs, and reassembled the result
block with handwritten metadata; every new kind of processing had to be taught
to all three.
"""

import threading
from dataclasses import asdict, replace
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple, Union

import numpy as np

from core.benchmark import benchmark_step
from core.block_kinds import (
    INVALID_SAMPLE_KEYS, KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM,
    KIND_SPECTRUM, META_EMPTY_STEPS, META_FRAMES, META_INVALID_SAMPLES, META_SKIPPED_FRAMES,
    META_STEPS, PARAM_ORDERS,
)
from core.curve_recipe import (
    PARAM_CURVE_RECIPE, build_curve_recipe, build_order_cut_curve_recipe, build_order_residual_curve_recipe,
)
from core.data_block import NVHDataBlock, Provenance, SpectralProcessing
from core.dsp_configs import (
    SpectrumConfig, SpectrogramConfig, OrderTrackingConfig, OverallLevelConfig,
    VALID_TRACKING_MODES, normalize_dsp_choice, resolve_tracking_sweep, resolve_tracking_sweep_fields,
)
from core.tacho_cleaning import TachoCleaning
from core.unit_label import build_unit_label
from core.units import convert_numeric_array, format_order_unit
from signal_processing.dsp.levels import compute_tracked_overall_level
from signal_processing.dsp.spectrum import compute_averaged_spectrum
from signal_processing.dsp.order_cut import (
    compute_tracked_order_cuts, compute_tracked_order_cuts_with_overall_level,
)
from signal_processing.dsp.tracking import (
    TrackingPlan, build_tracking_plan, clean_rpm_profile, require_tracking_triggers,
)
from signal_processing.dsp.spectrogram import compute_tracked_spectrogram_with_window
from signal_processing.dsp.dc_offset import remove_dc_offset
from signal_processing.dsp.steps.frame_cutting import resolve_invalid_tracking_steps


# A wrong metadata dt and the actual time-array spacing rarely disagree by a
# hair -- it's either the same recording (float noise, well under 1%) or a
# genuinely different one (an export/relabelling bug, off by a lot). 1% keeps
# the check tight without tripping on ordinary floating-point jitter.
_SAMPLE_RATE_MISMATCH_TOLERANCE = 0.01


def resolve_sampling_frequency(block: NVHDataBlock) -> float:
    """
    Strictly resolves the sampling frequency, preferring metadata over the time
    array. Raises rather than guessing: a wrong sample rate silently scales
    every frequency axis derived from it, so a caller that cannot determine it
    must stop rather than substitute a default.

    Also cross-checks metadata dt against the time array's own spacing when
    both are available -- a metadata dt that is merely wrong (not missing)
    would otherwise be trusted blindly and produce a plausible-looking but
    incorrect frequency axis.
    """
    dt = block.acquisition.dt

    dt_from_x = None
    time_values = block.primary_axis.values
    if len(time_values) > 1:
        dt_from_x = float(np.median(np.diff(time_values)))

    if dt <= 0.0:
        if dt_from_x is not None and dt_from_x > 0.0:
            dt = dt_from_x
        else:
            raise ValueError(
                f"CRITICAL: Cannot determine sampling rate for '{block.name}'. "
                f"Metadata missing and time array is invalid."
            )
    elif dt_from_x is not None and dt_from_x > 0.0:
        relative_diff = abs(dt - dt_from_x) / dt
        if relative_diff > _SAMPLE_RATE_MISMATCH_TOLERANCE:
            raise ValueError(
                f"CRITICAL: Sample rate mismatch for '{block.name}': metadata says "
                f"dt={dt:.6g}s ({1.0 / dt:.1f} Hz) but the time array spacing is "
                f"dt={dt_from_x:.6g}s ({1.0 / dt_from_x:.1f} Hz) -- off by "
                f"{relative_diff * 100:.1f}%."
            )

    if dt <= 0.0:
        raise ValueError(f"CRITICAL: Calculated time increment (dt) for '{block.name}' is zero or negative.")

    return 1.0 / dt


def _share_sampling_rate(fs_a: float, fs_b: float) -> bool:
    """Whether two rates count as one within the tolerance a real file's header can be off by."""
    return abs(fs_a - fs_b) / max(fs_a, fs_b) <= _SAMPLE_RATE_MISMATCH_TOLERANCE


def _require_same_start(vib_block: NVHDataBlock, tacho_block: NVHDataBlock, fs: float) -> None:
    """Raises unless both channels' first samples lie within half a sample of the channel's `fs`."""
    vib_times, tacho_times = vib_block.primary_axis.values, tacho_block.primary_axis.values
    if len(vib_times) and len(tacho_times):
        vib_start, tacho_start = float(vib_times[0]), float(tacho_times[0])
        if abs(vib_start - tacho_start) > 0.5 / fs:
            raise ValueError(
                f"Vibration/tacho start time mismatch: '{vib_block.name}' starts at "
                f"{vib_start:.6g}s, '{tacho_block.name}' at {tacho_start:.6g}s. Both channels "
                f"must start at the same instant to share a timebase."
            )


def require_matching_sample_grid(vib_block: NVHDataBlock, tacho_block: NVHDataBlock, fs: float) -> None:
    """
    Raises unless vibration and tacho of one sampling rate cover the same sample
    instants: the same sample count and the same first time stamp (within half a
    sample).

    A tracking plan places its triggers at tacho sample indices and applies
    them to the vibration unchanged, so an equal sample rate is not enough --
    a tacho that is longer, shorter or starts later yields a curve read at the
    wrong speed with nothing raised. Such channels are refused, not trimmed.
    """
    n_vib, n_tacho = len(vib_block.values), len(tacho_block.values)
    if n_vib != n_tacho:
        raise ValueError(
            f"Vibration/tacho length mismatch: '{vib_block.name}' has {n_vib} samples, "
            f"'{tacho_block.name}' has {n_tacho}. Both channels must share the same "
            f"sample count to align trigger indices."
        )
    _require_same_start(vib_block, tacho_block, fs)


def _interpolate_tacho(vib_block: NVHDataBlock, tacho_block: NVHDataBlock, fs: float,
                       tacho_fs: float, tacho_rpm: np.ndarray) -> np.ndarray:
    """
    Tacho interpolation: the speed at each sample instant of the channel, linear
    between the tacho's samples, so everything downstream sees one rpm per sample.
    `tacho_rpm` is already through Tacho cleaning, so finite.

    The start is checked first, or the message would blame the rate. Past the
    tacho's last sample its value holds for one tacho step, the usual end of a
    recording; a channel running on beyond that is refused rather than silently cut.
    A faster tacho is averaged over one step of the channel on the way, or its noise
    would alias into slow swings of the speed (`_average_tacho`).
    """
    vib_times, tacho_times = vib_block.primary_axis.values, tacho_block.primary_axis.values
    if not len(vib_times) or not len(tacho_times):
        raise ValueError(
            f"Cannot interpolate tacho '{tacho_block.name}' onto '{vib_block.name}': "
            f"they have {len(tacho_times)} and {len(vib_times)} samples."
        )
    _require_same_start(vib_block, tacho_block, fs)

    vib_end, tacho_end = float(vib_times[-1]), float(tacho_times[-1])
    # The factor only forgives a float's last digits on a channel exactly one step past.
    if vib_end - tacho_end > (1.0 + 1e-9) / tacho_fs:
        raise ValueError(
            f"Tacho does not cover the channel: '{tacho_block.name}' ends at {tacho_end:.6g}s, "
            f"'{vib_block.name}' at {vib_end:.6g}s."
        )
    if tacho_fs > fs:
        return _average_tacho(vib_times, tacho_times, tacho_rpm, fs)
    return np.interp(vib_times, tacho_times, tacho_rpm)


def _average_tacho(vib_times: np.ndarray, tacho_times: np.ndarray, tacho_rpm: np.ndarray,
                   fs: float) -> np.ndarray:
    """
    The mean speed over one step of the channel, centred on each of its instants.

    A window of exactly one step cancels whatever would fold down to a slow swing,
    the frequencies next to a multiple of `fs`. Hence the difference of the running
    integral rather than a count of tacho samples: a count would miss that width at
    a fractional ratio, and at a ratio under 1.5 would not average at all. A window
    is clipped at the ends of the tacho; past its end the last value holds.
    """
    areas = 0.5 * (tacho_rpm[1:] + tacho_rpm[:-1]) * np.diff(tacho_times)
    integral = np.concatenate(([0.0], np.cumsum(areas)))

    window_start = np.clip(vib_times - 0.5 / fs, tacho_times[0], tacho_times[-1])
    window_end = np.clip(vib_times + 0.5 / fs, tacho_times[0], tacho_times[-1])
    width = window_end - window_start
    inside = width > 0.0
    averaged = np.full(len(vib_times), float(tacho_rpm[-1]))
    averaged[inside] = (np.interp(window_end[inside], tacho_times, integral)
                        - np.interp(window_start[inside], tacho_times, integral)) / width[inside]
    return averaged


_TACHO_KEY = ("tacho_rpm",)


def _channel_grid(fs: float, n_samples: int, start_time: float) -> Tuple[float, int, float]:
    """What in `scratch` tells one channel's sample instants from another's."""
    return float(fs), n_samples, start_time


def _cleaned_tacho(scratch: Optional[MutableMapping[str, Any]], tacho_rpm: np.ndarray, tacho_fs: float,
                   tacho_cleaning: TachoCleaning) -> np.ndarray:
    """The tacho through Tacho cleaning on its own rate, once per bag and cleaning (read-only)."""
    key = _TACHO_KEY + (tacho_cleaning,)
    cleaned = scratch.get(key) if scratch is not None else None
    if cleaned is None:
        cleaned = clean_rpm_profile(tacho_rpm, tacho_fs, tacho_cleaning)
        cleaned.setflags(write=False)
        if scratch is not None:
            scratch[key] = cleaned
    return cleaned


def resolve_and_convert_tacho(vib_block: NVHDataBlock, tacho_block: NVHDataBlock,
                              scratch: Optional[MutableMapping[str, Any]] = None, *,
                              tacho_cleaning: TachoCleaning) -> tuple:
    """
    The vibration sampling frequency, and the speed the triggers are placed on:
    the tacho converted to rpm, through Tacho cleaning with `tacho_cleaning` on
    its own rate, then with one value per sample of the channel.
    The order matters: the Hampel filter judges the samples as they were
    recorded, before an interpolation spreads one bad sample over many. A tacho
    of the channel's rate (within the tolerance) must share its grid and is
    only cleaned; one of another rate goes through Tacho interpolation after
    the cleaning. With a bag the cleaned tacho is kept once per cleaning, and
    its interpolation per cleaning and grid (rate, sample count, start), so
    channels alternating in one bag each keep theirs.

    This exact sequence -- resolve both fs, cross-check them, then convert
    tacho to rpm -- used to be written out independently at every call site
    that needs an order-tracking-ready tacho signal.

    `scratch` is the per-measurement bag the TrackingPlan lives in, and like
    the plan it assumes one tacho per bag. With it the tacho's fs and rpm are
    worked out once per file instead of once per channel (#502), and a channel
    with the tacho's dt and time axis takes the tacho's fs -- the same inputs
    give resolve_sampling_frequency the same answer, without the median over
    its time axis that made up most of the per-channel cost. The grid checks
    still run for every channel.

    Returns (fs, speed_rpm), the speed read-only.
    """
    cached = scratch.get(_TACHO_KEY) if scratch is not None else None
    if cached is None:
        cached = (tacho_block.acquisition.dt, tacho_block.primary_axis.values,
                  resolve_sampling_frequency(tacho_block),
                  convert_numeric_array(tacho_block.values, tacho_block.value_unit, "rpm", strict=True))
        if scratch is not None:
            scratch[_TACHO_KEY] = cached
    tacho_dt, tacho_times, tacho_fs, tacho_rpm = cached

    vib_times = vib_block.primary_axis.values
    if (scratch is not None and vib_block.acquisition.dt == tacho_dt
            and (vib_times is tacho_times or np.array_equal(vib_times, tacho_times))):
        fs = tacho_fs
    else:
        fs = resolve_sampling_frequency(vib_block)
    if not _share_sampling_rate(fs, tacho_fs):
        grid_key = (_TACHO_KEY + (tacho_cleaning,)
                    + _channel_grid(fs, len(vib_times), _resolve_start_time(vib_block)))
        interpolated = scratch.get(grid_key) if scratch is not None else None
        if interpolated is None:
            interpolated = _interpolate_tacho(vib_block, tacho_block, fs, tacho_fs,
                                              _cleaned_tacho(scratch, tacho_rpm, tacho_fs, tacho_cleaning))
            interpolated.setflags(write=False)
            if scratch is not None:
                scratch[grid_key] = interpolated
        return fs, interpolated
    require_matching_sample_grid(vib_block, tacho_block, fs)
    return fs, _cleaned_tacho(scratch, tacho_rpm, tacho_fs, tacho_cleaning)


def with_dc_removed(block: NVHDataBlock) -> NVHDataBlock:
    """
    A copy of `block` with the mean taken out of its samples (and a tacho left
    alone -- see remove_dc_offset).

    A new block rather than an edit in place. One loaded recording is handed to
    several consumers; the four call sites that used to write
    `block.y_data = remove_dc_offset(...)` removed it for all of them, so the
    numbers a consumer got depended on whether some other consumer had run
    first. Nothing raised, the plot just quietly differed.
    """
    return replace(
        block,
        values=remove_dc_offset(block.values, block.channel_type),
        provenance=replace(
            block.provenance,
            params={**block.provenance.params, "remove_dc": True},
        ),
    )


# One place per result kind where a raw DSP payload becomes a block. The
# asynchronous path once held only the arrays a worker thread returned, not a
# block, so before these existed it spelled the construction out again, and a spectrum
# was assembled at two sites and an order cut at four. Every one of them
# repeated the unit rule, the naming rule and the metadata copy.


def _provenance(step: str, source_block: NVHDataBlock,
                curve_recipe: Optional[Mapping[str, Any]] = None) -> Provenance:
    """The provenance of a block computed from `source_block`, stamped with
    its `curve_recipe` (`core.curve_recipe`) when it has one (#812, #813)."""
    params = {PARAM_CURVE_RECIPE: dict(curve_recipe)} if curve_recipe is not None else {}
    return Provenance(step=step, parents=(source_block.name,), params=params)


def build_spectrum_block(source_block: NVHDataBlock, frequencies, amplitudes, *,
                         window_type: str,
                         acf: float, ecf_linear: float, enbw_hz: Optional[float],
                         fft_size: Optional[int] = None,
                         averaging_type: Optional[str] = None,
                         exponential_parameter: Optional[float] = None,
                         curve_recipe: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """A computed single-sided canonical spectrum plus the settings it was computed with."""
    return NVHDataBlock.spectrum(
        name=f"1D Spectrum({source_block.name})",
        values=amplitudes, frequencies=frequencies,
        value_unit=build_unit_label(source_block.value_unit, "canonical", "rms"),
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="canonical", acf=acf, ecf_linear=ecf_linear,
            enbw_hz=enbw_hz, fft_size=fft_size, averaging_type=averaging_type,
            exponential_parameter=exponential_parameter,
        ),
        provenance=_provenance("compute_spectrum", source_block, curve_recipe),
        **source_block.inherited_context(),
    )


def build_spectrogram_block(source_block: NVHDataBlock, frequencies, tracking_values, magnitude_matrix, *,
                            tracked_against_speed: bool, window_type: str,
                            fft_size: Optional[int] = None,
                            acf: float = 1.0, ecf_linear: float = 1.0,
                            enbw_hz: Optional[float] = None,
                            curve_recipe: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    A tracked waterfall in canonical bin energy: one spectrum column per rpm step or time slice, so
    `magnitude_matrix` is (frequency, tracking) and the two axes describe it in that
    order.
    """
    return NVHDataBlock.spectrogram(
        name=f"Waterfall({source_block.name})",
        values=magnitude_matrix, frequencies=frequencies, tracking_values=tracking_values,
        tracking_unit="RPM" if tracked_against_speed else "s",
        tracking_quantity="rpm" if tracked_against_speed else "time",
        value_unit=build_unit_label(source_block.value_unit, "canonical", "rms"),
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="canonical", fft_size=fft_size,
            acf=acf, ecf_linear=ecf_linear, enbw_hz=enbw_hz,
        ),
        provenance=_provenance("compute_spectrogram", source_block, curve_recipe),
        **source_block.inherited_context(),
    )


class UnevenRpmAxisError(ValueError):
    """An rpm spectrogram whose speed axis the image cannot draw truthfully."""


def require_uniform_rpm_axis(block: NVHDataBlock) -> None:
    """
    Raises UnevenRpmAxisError unless an rpm spectrogram's speed axis is an
    evenly spaced, strictly increasing grid -- the only axis the image can draw truthfully, since it
    lays its columns evenly between the first and last speed (#434).

    A speed crossed twice or a speed the sweep never reached would put every
    later column at the wrong rpm with nothing raised. Repeated
    columns are spectra from different times, so they are refused rather than
    dropped or averaged. A time axis is not checked -- its slices sit on whole
    samples and are even within one sample by construction.
    """
    tracking_axis = block.axes[1]
    if tracking_axis.quantity != "rpm" or len(tracking_axis.values) < 2:
        return
    steps = np.diff(np.asarray(tracking_axis.values, dtype=np.float64))
    if steps[0] > 0 and np.allclose(steps, steps[0], rtol=1e-6, atol=0.0):
        return
    raise UnevenRpmAxisError(
        f"The RPM axis of '{block.name}' is not an evenly spaced, strictly increasing grid "
        f"(repeated or missing speeds), so the spectrogram image would draw columns at "
        f"the wrong RPM. The measurement most likely holds more than one run-up or "
        f"run-down in the chosen sweep direction; use a recording with a single sweep."
    )


def build_order_cut_block(source_block: NVHDataBlock, rpm_axis, order: float, amplitudes, *,
                          window_type: str,
                          fft_size: Optional[int] = None,
                          value_unit: Optional[str] = None,
                          name: Optional[str] = None,
                          step: str = "compute_order_cuts",
                          curve_recipe: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    One order cut in Linear RMS: the single recipe behind every
    order-cut block, whether Order Tracking or an Evaluation row builds it.
    `value_unit`, `name` and the provenance `step` default to Order Tracking's;
    `rpm_axis` must already be a float64 array when it is shared between blocks.
    `curve_recipe` is the Order Tracking curve recipe of the whole config, stamped
    narrowed to this cut's order; an Evaluation row has none.
    """
    if value_unit is None:
        value_unit = format_order_unit(source_block.value_unit, "linear", "rms")
    if curve_recipe is not None:
        curve_recipe = build_order_cut_curve_recipe(curve_recipe, order)
    provenance = _provenance(step, source_block, curve_recipe)
    return NVHDataBlock.order_cut(
        name=f"Order {order} [{source_block.name}]" if name is None else name,
        values=amplitudes, rpm=rpm_axis, order=order,
        value_unit=value_unit,
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="linear", fft_size=fft_size,
        ),
        provenance=provenance,
        **source_block.inherited_context(),
    )


def build_order_tracking_curve_recipe(config: OrderTrackingConfig) -> Dict[str, Any]:
    """The curve recipe of an Order Tracking `config` before it is narrowed to one order."""
    return build_curve_recipe(KIND_ORDER_CUT, asdict(config))


def build_order_cut_blocks(source_block: NVHDataBlock, rpm_axis,
                           orders_to_amplitude: Dict[float, np.ndarray], *,
                           window_type: str,
                           fft_size: Optional[int] = None,
                           value_unit: Optional[str] = None,
                           curve_recipe: Optional[Mapping[str, Any]] = None) -> List[NVHDataBlock]:
    """
    One block per extracted order. The rpm axis is shared between them; blocks
    are read-only, so that costs nothing and copies nothing. Always in Linear RMS.
    """
    rpm_axis = np.asarray(rpm_axis, dtype=np.float64)
    return [
        build_order_cut_block(
            source_block, rpm_axis, order, amplitudes, window_type=window_type,
            fft_size=fft_size, value_unit=value_unit, curve_recipe=curve_recipe,
        )
        for order, amplitudes in orders_to_amplitude.items()
    ]


def build_overall_level_block(source_block: NVHDataBlock, axis_values, levels, *,
                              tracked_against_speed: bool, window_type: str,
                              fft_size: int, f_start: float, f_stop: Optional[float],
                              effective_band: Tuple[float, float],
                              curve_recipe: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    An Overall Level curve in Linear RMS, the unit an order cut has.
    `f_start`/`f_stop` are the band as requested; `effective_band` is what was
    integrated over this file after clipping to its Nyquist.
    """
    return NVHDataBlock.overall_level(
        name=f"Overall Level({source_block.name})",
        values=levels, axis_values=np.asarray(axis_values, dtype=np.float64),
        axis_quantity="rpm" if tracked_against_speed else "time",
        f_start=float(f_start), f_stop=None if f_stop is None else float(f_stop),
        effective_f_start=float(effective_band[0]), effective_f_stop=float(effective_band[1]),
        value_unit=format_order_unit(source_block.value_unit, "linear", "rms"),
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="linear", fft_size=fft_size,
        ),
        provenance=_provenance("compute_overall_level", source_block, curve_recipe),
        **source_block.inherited_context(),
    )


def build_order_residual_block(source_block: NVHDataBlock, rpm_axis, residual, *,
                               window_type: str, fft_size: int, orders: List[float],
                               curve_recipe: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    A Residual curve in Linear RMS, the unit its order cuts and Overall Level have. The
    order list goes into provenance.params -- the Residual is a function of all
    of them, so its `curve_recipe` keeps the whole list too.
    """
    provenance = _provenance("compute_order_residual", source_block, curve_recipe)
    return NVHDataBlock.order_residual(
        name=f"Residual({source_block.name})",
        values=residual, rpm=np.asarray(rpm_axis, dtype=np.float64),
        value_unit=format_order_unit(source_block.value_unit, "linear", "rms"),
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="linear", fft_size=fft_size,
        ),
        provenance=replace(provenance, params={**provenance.params,
                                               PARAM_ORDERS: [float(o) for o in orders]}),
        **source_block.inherited_context(),
    )


def _timed(step_name: str, function, *args, **kwargs):
    """Call `function` inside the Benchmark stopwatch `step_name`."""
    with benchmark_step(step_name):
        return function(*args, **kwargs)


def compute_spectrum(time_block: NVHDataBlock, config: SpectrumConfig) -> NVHDataBlock:
    """Time-domain block in, frequency-domain block out. Raises on an unresolvable fs."""
    fs = resolve_sampling_frequency(time_block)

    values = time_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, time_block.channel_type)

    frequencies, amplitudes, meta = compute_averaged_spectrum(
        time_data=values, fs=fs, fft_size=config.fft_size, overlap_pct=50.0,
        window_type=config.window_type,
        averaging_type=config.averaging_type,
        exponential_parameter=config.exponential_parameter,
    )

    block = _timed("result_blocks", build_spectrum_block,
        time_block, frequencies, amplitudes,
        window_type=config.window_type,
        acf=meta["acf"], ecf_linear=meta["ecf_linear"], enbw_hz=meta["enbw_hz"],
        fft_size=config.fft_size, averaging_type=config.averaging_type,
        exponential_parameter=config.exponential_parameter,
        curve_recipe=build_curve_recipe(KIND_SPECTRUM, asdict(config)),
    )
    loss = {}
    if meta[META_SKIPPED_FRAMES]:
        loss = {META_SKIPPED_FRAMES: meta[META_SKIPPED_FRAMES], META_FRAMES: meta[META_FRAMES]}
    return _note_invalid_samples(block, time_block, loss)


def _resolve_tracked_loss(values: np.ndarray, plan: TrackingPlan, fft_size: int) -> Dict[str, int]:
    """
    The tracking steps invalid (NaN) samples in `values` leave empty, as
    `_note_invalid_samples` records them (#673); empty when they leave none.
    Raises when they leave every step empty, before anything is computed.
    """
    invalid = ~np.isfinite(values)
    if not invalid.any():
        return {}
    empty = resolve_invalid_tracking_steps(invalid, plan.trigger_indices, fft_size)
    n_empty = int(np.count_nonzero(empty))
    if not n_empty:
        return {}
    if n_empty == empty.size:
        raise ValueError(
            f"Every one of the {empty.size} tracking steps holds an invalid (NaN) "
            "sample; there is nothing left to show."
        )
    return {META_EMPTY_STEPS: n_empty, META_STEPS: int(empty.size)}


def _note_invalid_samples(block: NVHDataBlock, time_block: NVHDataBlock,
                          loss: Mapping[str, int]) -> NVHDataBlock:
    """
    `block` with what invalid (NaN) samples of `time_block` cost it in its
    metadata (`core.block_kinds.META_INVALID_SAMPLES`, #673), or unchanged when
    `loss` is empty: samples no frame or step reached left the result as a
    clean channel's, and a warning about them would be noise.
    """
    if not loss:
        return block
    invalid = int(np.count_nonzero(~np.isfinite(time_block.values)))
    return replace(block, metadata={
        **block.metadata, META_INVALID_SAMPLES: invalid, **{k: int(v) for k, v in loss.items()},
    })


def _resolve_start_time(block: NVHDataBlock) -> float:
    """The time of the block's first sample: not 0 s for every recording (#739)."""
    times = block.primary_axis.values
    return float(times[0]) if len(times) else 0.0


def _tracking_plan_for(scratch: Optional[MutableMapping[str, Any]],
                       config: Union[OrderTrackingConfig, SpectrogramConfig, OverallLevelConfig],
                       tacho_rpm: Optional[np.ndarray],
                       n_samples: int, fs: float, vib_block: NVHDataBlock) -> TrackingPlan:
    """
    The `TrackingPlan` for this channel: reused from `scratch` when the caller
    kept one for this measurement and it still fits, built fresh otherwise --
    this always returns a plan with triggers, never `None`, so the recipes
    downstream (order_cut.compute_tracked_order_cuts,
    spectrogram.compute_tracked_spectrogram_with_window) never have to build
    one of their own.

    Keyed by the config's whole `TrackingSweep` -- tracking mode, step,
    direction, Tracking range and Tacho cleaning: a spectrogram can be
    rpm- or time-tracked, and a graph running both at the same step number must
    not have one overwrite the other's plan in scratch, nor
    a plan cut for one range or window serve another (#805, #807, #839). And by
    the channel's grid (#934): a channel recorded at another rate or length gets
    its own plan instead of being cut at the wrong instants, one that starts at
    another time gets its own time axis, and alternating them rebuilds neither.

    Raises, naming the measurement, when the Tracking range found no target
    in it (`require_tracking_triggers`).
    """
    sweep = resolve_tracking_sweep(config)
    start_time = _resolve_start_time(vib_block)
    key = ("tracking_plan", sweep) + _channel_grid(fs, n_samples, start_time)
    plan = scratch.get(key) if scratch is not None else None
    if plan is None:
        plan = _timed(
            "tracking_plan", build_tracking_plan,
            tacho_rpm, n_samples, fs, sweep, start_time=start_time,
        )
        if scratch is not None:
            scratch[key] = plan
    require_tracking_triggers(plan, vib_block.source.file_name or vib_block.name)
    return plan


def _same_samples(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> bool:
    return a is b or (a is not None and b is not None and np.array_equal(a, b))


class TrackingScratch:
    """
    One `scratch` bag kept across calls, for the tacho and sweep it was last
    asked for (#500). An interactive click reads its channels anew, so without
    it every click on the same file rebuilt the TrackingPlan (~70-100 ms).

    The bag follows the tacho's samples rather than the file: the plan and the
    cached rpm depend on nothing else, so a re-measured file with a new tacho
    gets a new bag and a fresh read of the same tacho keeps the old one -- at
    the price of one array comparison (~1-2 ms on a 75 s run-up). The sweep is
    part of it so the bag holds one plan per tracking mode and channel grid, not
    one per step ever tried (each plan is ~15 MB, ADR §1.117). Thread-safe: a job
    keeps the bag it was handed even after a newer call replaces it, and calls that
    meet a grid new to the bag at the same time build its plan once between them (#99).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._identity = None
        self._tacho: Optional[NVHDataBlock] = None
        self._scratch: Dict[Any, Any] = {}
        self._build_lock = threading.Lock()
        self._built_grids: set = set()

    def resolve_scratch(self, tacho_block: Optional[NVHDataBlock],
                    config: Union[OrderTrackingConfig, SpectrogramConfig, OverallLevelConfig]
                    ) -> MutableMapping[str, Any]:
        return self._resolve(tacho_block, config)[0]

    def _resolve(self, tacho_block, config):
        """The bag for this tacho and sweep, the lock its plans are built under, and their grids."""
        sweep = resolve_tracking_sweep(config)
        identity = (sweep,)
        if tacho_block is not None:
            identity += (tacho_block.value_unit, tacho_block.acquisition.dt, len(tacho_block.values))
        with self._lock:
            old = self._tacho
            same_tacho = (old is tacho_block or (
                old is not None and tacho_block is not None
                and _same_samples(old.values, tacho_block.values)
                and _same_samples(old.primary_axis.values, tacho_block.primary_axis.values)))
            if identity != self._identity or not same_tacho:
                self._identity, self._tacho, self._scratch = identity, tacho_block, {}
                self._build_lock = threading.Lock()
                self._built_grids = set()
            return self._scratch, self._build_lock, self._built_grids

    def compute(self, compute_fn, vib_block: NVHDataBlock, tacho_block: Optional[NVHDataBlock], config):
        """
        `compute_fn` (compute_order_cuts and its tracked siblings) with this
        bag; run it on the worker. The first call for a channel grid computes
        under the bag's lock, so siblings arriving meanwhile wait for its plan
        rather than build their own, then compute side by side. The grid is told
        by dt here: working out `fs` is part of what the lock saves. Without a
        tacho, or tracked against time, there is no plan to wait for.
        """
        scratch, build_lock, built_grids = self._resolve(tacho_block, config)
        if tacho_block is not None and resolve_tracking_sweep(config).mode == "rpm":
            grid = (vib_block.acquisition.dt, len(vib_block.values), _resolve_start_time(vib_block))
            with build_lock:
                if grid not in built_grids:
                    result = compute_fn(vib_block, tacho_block, config, scratch=scratch)
                    built_grids.add(grid)
                    return result
        return compute_fn(vib_block, tacho_block, config, scratch=scratch)


def compute_order_cuts(vib_block: NVHDataBlock, tacho_block: NVHDataBlock,
                       config: OrderTrackingConfig,
                       scratch: Optional[MutableMapping[str, Any]] = None,
                       *, with_overall_level: bool = False,
                       ) -> List[NVHDataBlock]:
    """
    Vibration and tacho blocks in, one order-domain block per requested order out.

    The tacho is always converted to rpm here regardless of the unit it was
    recorded in. Two of the three prior copies of this routine skipped that
    conversion and passed the raw tacho array straight through -- silently
    correct only when the tacho happened to already be in rpm.

    `scratch` is a caller-owned bag scoped to one measurement (the workflow
    runner's per-file memo -- see `signal_processing.workflow.run_graph`). A
    batch cuts every channel of a file against the same tacho, and the
    `TrackingPlan` depends on the tacho, the sweep settings and the channel's grid
    but never on its values, so with a bag it is placed once per file instead of once
    per channel: 0.076 s against 0.016 s for the cuts themselves on the real 75 s
    run-up. Without one every call rebuilds it -- correct, but the repetition
    BUGS.md K2 was about.

    `with_overall_level` (the Order Tracking tab's "Overall Level + Residual",
    ADR §1.141) appends one `overall_level` block over the default band, from
    the same p_canon and plan, equal to `compute_overall_level` with the same
    sweep settings, then one `order_residual` block: that band's energy outside
    every order's band. It is not a config field: the order cut's cache identity is
    the whole config (point 9). A band empty for this file (F min at or past
    its Nyquist) leaves the orders alone and both blocks out
    (`build_overall_level_missing_line`).
    """
    fs, tacho_rpm = _timed("tacho_to_rpm", resolve_and_convert_tacho, vib_block, tacho_block, scratch,
                               tacho_cleaning=resolve_tracking_sweep(config).tacho_cleaning)

    values = vib_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, vib_block.channel_type)

    plan = _tracking_plan_for(scratch, config, tacho_rpm, len(values), fs, vib_block)
    loss = _resolve_tracked_loss(values, plan, config.fft_size)
    overall_level_config = _order_tracking_overall_level_config(config)
    band = None
    if with_overall_level:
        try:
            band = _effective_overall_level_band(overall_level_config, fs)
        except ValueError:
            pass

    if band is None:
        rpm_axis, order_cuts_dict = compute_tracked_order_cuts(
            vib_data=values, fs=fs,
            orders_to_extract=config.orders_to_extract, order_width=config.order_width,
            fft_size=config.fft_size, window_type=config.window_type, plan=plan,
        )
    else:
        rpm_axis, order_cuts_dict, levels, residual = compute_tracked_order_cuts_with_overall_level(
            values, fs, config.orders_to_extract, config.order_width,
            config.fft_size, config.window_type,
            f_start=band[0], f_stop=band[1], plan=plan,
        )

    blocks = _timed("result_blocks", build_order_cut_blocks,
        vib_block, rpm_axis, order_cuts_dict,
        window_type=config.window_type, fft_size=config.fft_size,
        curve_recipe=build_order_tracking_curve_recipe(config),
    )
    if band is not None:
        blocks.append(build_overall_level_block(
            vib_block, rpm_axis, levels,
            tracked_against_speed=True, window_type=overall_level_config.window_type,
            fft_size=overall_level_config.fft_size, f_start=overall_level_config.f_start, f_stop=overall_level_config.f_stop,
            effective_band=band, curve_recipe=build_curve_recipe(KIND_OVERALL_LEVEL, asdict(overall_level_config)),
        ))
        blocks.append(build_order_residual_block(
            vib_block, rpm_axis, residual, window_type=config.window_type,
            fft_size=config.fft_size, orders=config.orders_to_extract,
            curve_recipe=build_order_residual_curve_recipe(asdict(config)),
        ))
    return [_note_invalid_samples(block, vib_block, loss) for block in blocks]


def _order_tracking_overall_level_config(config: OrderTrackingConfig) -> OverallLevelConfig:
    """The Overall Level tab settings the order tracking Overall Level curve equals:
    the default band, this config's FFT, window, sweep, Tracking range, Remove DC
    and Tacho cleaning."""
    return OverallLevelConfig(
        fft_size=config.fft_size, window_type=config.window_type, tracking_mode="rpm",
        remove_dc=config.remove_dc, **resolve_tracking_sweep_fields(config),
    )


def build_overall_level_missing_line(blocks: List[NVHDataBlock]) -> Optional[str]:
    """
    The one log line for an order tracking run asked for its Overall Level curve that
    came back without one, or None when it is there.
    """
    if not blocks or any(b.kind == KIND_OVERALL_LEVEL for b in blocks):
        return None
    channel = blocks[0].provenance.parents[0] if blocks[0].provenance.parents else blocks[0].name
    return (
        f"WARNING: Overall Level and Residual not drawn for {channel}: their band (F min "
        f"{OverallLevelConfig().f_start:g} Hz) is empty below this file's Nyquist frequency."
    )


def build_invalid_samples_line(blocks: List[NVHDataBlock]) -> Optional[str]:
    """
    The one log line for a channel whose time signal held invalid (NaN)
    samples (#673), from what `_note_invalid_samples` recorded on its blocks,
    or None for a clean one. One line per channel: every block of an order
    tracking run comes from the same signal.
    """
    block = next((b for b in blocks if b.metadata.get(META_INVALID_SAMPLES)), None)
    if block is None:
        return None
    meta = block.metadata
    channel = block.provenance.parents[0] if block.provenance.parents else block.name
    invalid = int(meta[META_INVALID_SAMPLES])
    if META_FRAMES in meta:
        lost = f"{meta[META_SKIPPED_FRAMES]} of {meta[META_FRAMES]} frames skipped"
    else:
        lost = f"{meta[META_EMPTY_STEPS]} of {meta[META_STEPS]} tracking steps left empty"
    return f"WARNING: {channel}: {invalid} invalid (NaN) sample{'s' if invalid != 1 else ''} -- {lost}."


def compute_spectrogram(vib_block: NVHDataBlock, tacho_block: Optional[NVHDataBlock],
                        config: SpectrogramConfig,
                        scratch: Optional[MutableMapping[str, Any]] = None) -> NVHDataBlock:
    """
    Vibration block (and tacho, unless tracking against time) in, one tracked
    waterfall block out.

    This is the path a live spectrogram runs on a worker thread, exposed
    synchronously so the block workflow (§1.6) reaches a spectrogram through the
    one place a raw waterfall becomes a block -- not a fourth hand-assembled
    copy of it (§1.12).

    An rpm-tracked waterfall without a tacho raises rather than quietly falling
    back to time slices. In a batch that fallback would write a result set whose
    params say "rpm, step 50" over a file that has no speed signal at all, and
    nothing downstream could tell it from a real one; a raised error becomes a
    per-file message and a "partial" set instead.

    `scratch` is the same per-measurement bag `compute_order_cuts` takes. A
    spectrogram and an order cut with the same tracking mode, step and direction
    over one measurement share the same `TrackingPlan` from it
   , and a multi-channel spectrogram batch builds its plan
    once per file instead of once per channel.
    """
    tracking_mode = normalize_dsp_choice(
        config.tracking_mode, VALID_TRACKING_MODES, "tracking_mode")
    against_time = tracking_mode == "time"

    if not against_time and tacho_block is None:
        raise ValueError(
            "An rpm-tracked spectrogram needs a tacho channel; this measurement "
            "has none. Use the 'Free Run (Time)' tracking mode for files without one."
        )

    values = vib_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, vib_block.channel_type)

    if against_time:
        fs = resolve_sampling_frequency(vib_block)
        tacho_rpm = None
    else:
        fs, tacho_rpm = _timed("tacho_to_rpm", resolve_and_convert_tacho, vib_block, tacho_block, scratch,
                               tacho_cleaning=resolve_tracking_sweep(config).tacho_cleaning)

    plan = _tracking_plan_for(scratch, config, tacho_rpm, len(values), fs, vib_block)
    loss = _resolve_tracked_loss(values, plan, config.fft_size)

    frequencies, tracking_values, magnitude_matrix, window = compute_tracked_spectrogram_with_window(
        vib_data=values, fs=fs, fft_size=config.fft_size,
        window_type=config.window_type, plan=plan,
    )

    acf, ecf_linear = window.acf, window.ecf_linear
    enbw_hz = window.enbw_factor * (fs / config.fft_size)

    block = _timed("result_blocks", build_spectrogram_block,
        vib_block, frequencies, tracking_values, magnitude_matrix,
        tracked_against_speed=not against_time, window_type=config.window_type,
        fft_size=config.fft_size, acf=acf, ecf_linear=ecf_linear, enbw_hz=enbw_hz,
        curve_recipe=build_curve_recipe(KIND_SPECTROGRAM, asdict(config)),
    )
    require_uniform_rpm_axis(block)
    return _note_invalid_samples(block, vib_block, loss)


def _effective_overall_level_band(config: OverallLevelConfig, fs: float) -> Tuple[float, float]:
    """
    The band integrated over this file: F max clipped to its Nyquist, and Full
    Bandwidth (`f_stop=None`) being exactly that Nyquist. Clipped rather than
    refused so a batch over files at mixed rates does not fail for no reason
   ; an F min at or past Nyquist leaves nothing to clip to
    and is an error for this file, not an empty curve (point 10).
    """
    nyquist = fs / 2.0
    f_start = float(config.f_start)
    if config.f_stop is not None and float(config.f_stop) <= f_start:
        raise ValueError(
            f"Overall Level F max ({float(config.f_stop):g} Hz) must be greater than "
            f"F min ({f_start:g} Hz)."
        )
    if f_start >= nyquist:
        raise ValueError(
            f"Overall Level band is empty for this file: F min {f_start:g} Hz is at or "
            f"above its Nyquist frequency of {nyquist:g} Hz."
        )
    f_stop = nyquist if config.f_stop is None else min(float(config.f_stop), nyquist)
    return f_start, f_stop


def compute_overall_level(vib_block: NVHDataBlock, tacho_block: Optional[NVHDataBlock],
                          config: OverallLevelConfig,
                          scratch: Optional[MutableMapping[str, Any]] = None) -> NVHDataBlock:
    """
    Vibration block (and tacho, unless tracking against time) in, one Overall
    Level curve out: the energy of one fixed band per tracking step.

    Refuses rpm tracking without a tacho for the reason compute_spectrogram
    does.

    `scratch` is the same per-measurement bag, under the same plan key: an
    order cut and an Overall Level with equal sweep settings over one file place
    their triggers once.
    """
    tracking_mode = normalize_dsp_choice(
        config.tracking_mode, VALID_TRACKING_MODES, "tracking_mode")
    against_time = tracking_mode == "time"

    if not against_time and tacho_block is None:
        raise ValueError(
            "An rpm-tracked Overall Level needs a tacho channel; this measurement "
            "has none. Use the 'Free Run (Time)' tracking mode for files without one."
        )

    if against_time:
        fs = resolve_sampling_frequency(vib_block)
        tacho_rpm = None
    else:
        fs, tacho_rpm = _timed("tacho_to_rpm", resolve_and_convert_tacho, vib_block, tacho_block, scratch,
                               tacho_cleaning=resolve_tracking_sweep(config).tacho_cleaning)

    band = _effective_overall_level_band(config, fs)

    values = vib_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, vib_block.channel_type)

    plan = _tracking_plan_for(scratch, config, tacho_rpm, len(values), fs, vib_block)
    loss = _resolve_tracked_loss(values, plan, config.fft_size)

    axis_values, levels = compute_tracked_overall_level(
        values, fs, config.fft_size, config.window_type,
        f_start=band[0], f_stop=band[1], plan=plan,
    )

    block = _timed("result_blocks", build_overall_level_block,
        vib_block, axis_values, levels,
        tracked_against_speed=not against_time, window_type=config.window_type,
        fft_size=config.fft_size, f_start=config.f_start, f_stop=config.f_stop,
        effective_band=band,
        curve_recipe=build_curve_recipe(KIND_OVERALL_LEVEL, asdict(config)),
    )
    return _note_invalid_samples(block, vib_block, loss)
