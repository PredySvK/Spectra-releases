# =====================================================================
# FILE: signal_processing/result_blocks.py
# =====================================================================
"""
Single synchronous path for turning a loaded time-domain block into a spectrum,
spectrogram, order cut, or Overall Level (ADR §1.12, §1.58, §1.60, §1.62).

The asynchronous equivalents (SpectralRequests, FileProcessingWorker) wrap
these functions in QRunnable tasks so the UI does not block; neither they nor
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
from dataclasses import replace
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple, Union

import numpy as np

from core.benchmark import benchmark_step
from core.block_kinds import KIND_OVERALL_LEVEL, PARAM_COMPUTATION, PARAM_ORDERS
from core.data_block import NVHDataBlock, Provenance, SpectralProcessing
from core.dsp_configs import (
    SpectrumConfig, SpectrogramConfig, OrderTrackingConfig, OverallLevelConfig,
    VALID_SWEEP_DIRECTIONS, VALID_TRACKING_MODES, normalize_dsp_choice,
)
from core.units import convert_numeric_array, format_spectral_unit, format_order_unit
from signal_processing.dsp.levels import compute_tracked_overall_level
from signal_processing.dsp.spectrum import compute_averaged_spectrum
from signal_processing.dsp.order_cut import (
    compute_tracked_order_cuts, compute_tracked_order_cuts_with_overall_level,
)
from signal_processing.dsp.tracking import TrackingPlan, build_tracking_plan
from signal_processing.dsp.spectrogram import compute_tracked_spectrogram
from signal_processing.dsp.windows import generate_window
from signal_processing.dsp.dc_offset import remove_dc_offset


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


def require_matching_sampling_rate(fs_a: float, name_a: str, fs_b: float, name_b: str) -> None:
    """
    Raises when two channels meant to share a timebase (e.g. vibration and
    tacho for order tracking) don't actually agree on sampling rate. Equal
    sample count is not sufficient evidence of alignment -- two channels can
    have the same length but a different dt, which produces a numerically
    plausible but physically wrong result.
    """
    relative_diff = abs(fs_a - fs_b) / max(fs_a, fs_b)
    if relative_diff > _SAMPLE_RATE_MISMATCH_TOLERANCE:
        raise ValueError(
            f"CRITICAL: Sampling rate mismatch between '{name_a}' ({fs_a:.1f} Hz) and "
            f"'{name_b}' ({fs_b:.1f} Hz) -- off by {relative_diff * 100:.1f}%. "
            f"These channels do not share a timebase."
        )


def require_matching_sample_grid(vib_block: NVHDataBlock, tacho_block: NVHDataBlock, fs: float) -> None:
    """
    Raises unless vibration and tacho cover the same sample instants: the same
    sample count and the same first time stamp (within half a sample).

    A tracking plan places its triggers at tacho sample indices and applies
    them to the vibration unchanged, so an equal sample rate is not enough --
    a tacho that is longer, shorter or starts later yields a curve read at the
    wrong speed with nothing raised. Aligning such channels (resampling,
    trimming) is not done here; they are refused.
    """
    n_vib, n_tacho = len(vib_block.values), len(tacho_block.values)
    if n_vib != n_tacho:
        raise ValueError(
            f"Vibration/tacho length mismatch: '{vib_block.name}' has {n_vib} samples, "
            f"'{tacho_block.name}' has {n_tacho}. Both channels must share the same "
            f"sample count to align trigger indices."
        )

    vib_times, tacho_times = vib_block.primary_axis.values, tacho_block.primary_axis.values
    if len(vib_times) and len(tacho_times):
        vib_start, tacho_start = float(vib_times[0]), float(tacho_times[0])
        if abs(vib_start - tacho_start) > 0.5 / fs:
            raise ValueError(
                f"Vibration/tacho start time mismatch: '{vib_block.name}' starts at "
                f"{vib_start:.6g}s, '{tacho_block.name}' at {tacho_start:.6g}s. Both channels "
                f"must start at the same instant to align trigger indices."
            )


_TACHO_KEY = ("tacho_rpm",)


def resolve_and_convert_tacho(vib_block: NVHDataBlock, tacho_block: NVHDataBlock,
                              scratch: Optional[MutableMapping[str, Any]] = None) -> tuple:
    """
    The vibration sampling frequency, and the tacho channel converted to rpm,
    with both timebases checked against each other along the way (sample rate,
    sample count and start time).

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

    Returns (fs, tacho_rpm).
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
    require_matching_sampling_rate(fs, vib_block.name, tacho_fs, tacho_block.name)
    require_matching_sample_grid(vib_block, tacho_block, fs)
    return fs, tacho_rpm


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
# asynchronous path (SpectralRequests) cannot call compute_* -- its maths
# already ran on a worker thread and it holds only the returned arrays -- so
# before these existed it spelled the construction out again, and a spectrum
# was assembled at two sites and an order cut at four. Every one of them
# repeated the unit rule, the naming rule and the metadata copy.


_COMPUTATION_FIELDS = ("order_width", "step", "direction", "hysteresis", "remove_dc")


def computation_params(config) -> Dict[str, Any]:
    """
    The settings of `config` a block's SpectralProcessing does not record --
    what `Provenance.params[PARAM_COMPUTATION]` holds so two curves computed
    with a different order width or rpm step can be told apart (#428).
    """
    return {name: getattr(config, name) for name in _COMPUTATION_FIELDS if hasattr(config, name)}


def _provenance(step: str, source_block: NVHDataBlock,
                computation: Optional[Mapping[str, Any]]) -> Provenance:
    params = {PARAM_COMPUTATION: dict(computation)} if computation else {}
    return Provenance(step=step, parents=(source_block.name,), params=params)


def build_spectrum_block(source_block: NVHDataBlock, frequencies, amplitudes, *,
                         window_type: str,
                         acf: float, ecf_linear: float, enbw_hz: Optional[float],
                         fft_size: Optional[int] = None,
                         averaging_type: Optional[str] = None,
                         exponential_alpha: Optional[float] = None,
                         computation: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """A computed single-sided canonical spectrum plus the settings it was computed with (ADR §1.60)."""
    return NVHDataBlock.spectrum(
        name=f"1D Spectrum({source_block.name})",
        values=amplitudes, frequencies=frequencies,
        value_unit=format_spectral_unit(source_block.value_unit, "canonical", "rms"),
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="canonical", acf=acf, ecf_linear=ecf_linear,
            enbw_hz=enbw_hz, fft_size=fft_size, averaging_type=averaging_type,
            exponential_alpha=exponential_alpha,
        ),
        provenance=_provenance("compute_spectrum", source_block, computation),
        **source_block.inherited_context(),
    )


def build_spectrogram_block(source_block: NVHDataBlock, frequencies, z_values, magnitude_matrix, *,
                            tracked_against_speed: bool, window_type: str,
                            fft_size: Optional[int] = None,
                            acf: float = 1.0, ecf_linear: float = 1.0,
                            enbw_hz: Optional[float] = None,
                            computation: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    A tracked waterfall in canonical bin energy: one spectrum column per rpm step or time slice, so
    `magnitude_matrix` is (frequency, z) and the two axes describe it in that
    order (ADR §1.60).
    """
    return NVHDataBlock.spectrogram(
        name=f"Waterfall({source_block.name})",
        values=magnitude_matrix, frequencies=frequencies, z_values=z_values,
        z_unit="RPM" if tracked_against_speed else "s",
        z_quantity="rpm" if tracked_against_speed else "time",
        value_unit=format_spectral_unit(source_block.value_unit, "canonical", "rms"),
        processing=SpectralProcessing(
            window_type=window_type, amplitude_mode="rms",
            spectrum_format="canonical", fft_size=fft_size,
            acf=acf, ecf_linear=ecf_linear, enbw_hz=enbw_hz,
        ),
        provenance=_provenance("compute_spectrogram", source_block, computation),
        **source_block.inherited_context(),
    )


class UnevenRpmAxisError(ValueError):
    """An rpm spectrogram whose speed axis the image cannot draw truthfully."""


def require_uniform_rpm_axis(block: NVHDataBlock) -> None:
    """
    Raises UnevenRpmAxisError unless an rpm spectrogram's speed axis is an
    evenly spaced, strictly increasing grid -- the only axis the image can draw truthfully, since it
    lays its columns evenly between the first and last speed (#434).

    Banning the "any" sweep is not enough: two run-ups under "up" cross some
    speeds twice too, and a speed the sweep never reached leaves a gap; both
    put every later column at the wrong rpm with nothing raised. Repeated
    columns are spectra from different times, so they are refused rather than
    dropped or averaged. A time axis is not checked -- its slices sit on whole
    samples and are even within one sample by construction.
    """
    z_axis = block.axes[1]
    if z_axis.quantity != "rpm" or len(z_axis.values) < 2:
        return
    steps = np.diff(np.asarray(z_axis.values, dtype=np.float64))
    if steps[0] > 0 and np.allclose(steps, steps[0], rtol=1e-6, atol=0.0):
        return
    raise UnevenRpmAxisError(
        f"The RPM axis of '{block.name}' is not an evenly spaced, strictly increasing grid "
        f"(repeated or missing speeds), so the spectrogram image would draw columns at "
        f"the wrong RPM. The measurement most likely holds more than one run-up or "
        f"run-down in the chosen sweep direction; use a recording with a single sweep."
    )


def build_order_cut_blocks(source_block: NVHDataBlock, rpm_axis,
                           orders_to_amplitude: Dict[float, np.ndarray], *,
                           window_type: str,
                           fft_size: Optional[int] = None,
                           value_unit: Optional[str] = None,
                           computation: Optional[Mapping[str, Any]] = None) -> List[NVHDataBlock]:
    """
    One block per extracted order. The rpm axis is shared between them; blocks
    are read-only, so that costs nothing and copies nothing. Always in Linear RMS (ADR §1.60).
    """
    if value_unit is None:
        value_unit = format_order_unit(source_block.value_unit, "linear", "rms")
    rpm_axis = np.asarray(rpm_axis, dtype=np.float64)
    processing = SpectralProcessing(
        window_type=window_type, amplitude_mode="rms",
        spectrum_format="linear", fft_size=fft_size,
    )
    return [
        NVHDataBlock.order_cut(
            name=f"Order {order} [{source_block.name}]",
            values=amplitudes, rpm=rpm_axis, order=order,
            value_unit=value_unit, processing=processing,
            provenance=_provenance("compute_order_cuts", source_block, computation),
            **source_block.inherited_context(),
        )
        for order, amplitudes in orders_to_amplitude.items()
    ]


def build_overall_level_block(source_block: NVHDataBlock, axis_values, levels, *,
                              tracked_against_speed: bool, window_type: str,
                              fft_size: int, f_start: float, f_stop: Optional[float],
                              effective_band: Tuple[float, float],
                              computation: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    An Overall Level curve in Linear RMS, the unit an order cut has (ADR §1.62).
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
        provenance=_provenance("compute_overall_level", source_block, computation),
        **source_block.inherited_context(),
    )


def build_order_residual_block(source_block: NVHDataBlock, rpm_axis, residual, *,
                               window_type: str, fft_size: int, orders: List[float],
                               computation: Optional[Mapping[str, Any]] = None) -> NVHDataBlock:
    """
    A Residual curve in Linear RMS, the unit its order cuts and Overall Level have. The
    order list goes into provenance.params -- the Residual is a function of all
    of them (ADR §1.141 point 6).
    """
    provenance = _provenance("compute_order_residual", source_block, computation)
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
        window_type=config.window_type, amplitude_mode="rms",
        spectrum_format="canonical",
        averaging_type=config.averaging_type,
        exponential_alpha=config.exponential_alpha,
    )

    return _timed("result_blocks", build_spectrum_block,
        time_block, frequencies, amplitudes,
        window_type=config.window_type,
        acf=meta["acf"], ecf_linear=meta["ecf_linear"], enbw_hz=meta["enbw_hz"],
        fft_size=config.fft_size, averaging_type=config.averaging_type,
        exponential_alpha=config.exponential_alpha,
        computation=computation_params(config),
    )


def _tracking_plan_for(scratch: Optional[MutableMapping[str, Any]],
                       config: Union[OrderTrackingConfig, SpectrogramConfig, OverallLevelConfig],
                       tacho_rpm: Optional[np.ndarray],
                       n_samples: int, fs: float,
                       tracking_mode: str = "rpm") -> TrackingPlan:
    """
    The `TrackingPlan` for this channel: reused from `scratch` when the caller
    kept one for this measurement and it still fits, built fresh otherwise --
    this always returns a plan, never `None`, so the recipes downstream
    (order_cut.compute_tracked_order_cuts, spectrogram.compute_tracked_spectrogram)
    never have to build one of their own.

    Keyed by tracking mode as well as the sweep settings the plan is built
    from: order cuts are always rpm-tracked, but a spectrogram can be rpm- or
    time-tracked, and a graph running both at the same step number must not
    have one overwrite the other's plan in scratch (ADR §1.58 point 6).
    `matches` guards the rest of it: a channel recorded at another rate or
    length gets its own plan instead of being cut at the wrong instants.
    """
    key = ("tracking_plan", tracking_mode, config.step, config.direction, config.hysteresis)
    plan = scratch.get(key) if scratch is not None else None
    if plan is None or not plan.matches(fs, n_samples):
        plan = _timed(
            "tracking_plan", build_tracking_plan,
            tacho_rpm, n_samples, fs, config.step, config.direction,
            config.hysteresis, tracking_mode=tracking_mode,
        )
        if scratch is not None:
            scratch[key] = plan
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
    part of it so the bag holds one plan per tracking mode, not one per step
    ever tried (each plan is ~15 MB, ADR §1.117). Thread-safe: a job keeps the
    bag it was handed even after a newer call replaces it.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._identity = None
        self._tacho: Optional[NVHDataBlock] = None
        self._scratch: Dict[Any, Any] = {}

    def resolve_scratch(self, tacho_block: Optional[NVHDataBlock],
                    config: Union[OrderTrackingConfig, SpectrogramConfig, OverallLevelConfig]
                    ) -> MutableMapping[str, Any]:
        identity = (config.step, config.direction, config.hysteresis)
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
            return self._scratch

    def compute(self, compute_fn, vib_block: NVHDataBlock, tacho_block: Optional[NVHDataBlock], config):
        """`compute_fn` (compute_order_cuts and its tracked siblings) with this bag; run it on the worker."""
        return compute_fn(vib_block, tacho_block, config, scratch=self.resolve_scratch(tacho_block, config))


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
    `TrackingPlan` depends on the tacho and the sweep settings but never on the
    vibration channel, so with a bag it is placed once per file instead of once
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
    fs, tacho_rpm = _timed("tacho_to_rpm", resolve_and_convert_tacho, vib_block, tacho_block, scratch)

    values = vib_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, vib_block.channel_type)

    plan = _tracking_plan_for(scratch, config, tacho_rpm, len(values), fs)
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
        computation=computation_params(config),
    )
    if band is not None:
        blocks.append(build_overall_level_block(
            vib_block, rpm_axis, levels,
            tracked_against_speed=True, window_type=overall_level_config.window_type,
            fft_size=overall_level_config.fft_size, f_start=overall_level_config.f_start, f_stop=overall_level_config.f_stop,
            effective_band=band, computation=computation_params(overall_level_config),
        ))
        blocks.append(build_order_residual_block(
            vib_block, rpm_axis, residual, window_type=config.window_type,
            fft_size=config.fft_size, orders=config.orders_to_extract,
            computation=computation_params(config),
        ))
    return blocks


def _order_tracking_overall_level_config(config: OrderTrackingConfig) -> OverallLevelConfig:
    """The Overall Level tab settings the order tracking Overall Level curve equals:
    the default band, this config's FFT, window, sweep and Remove DC (ADR §1.141 point 5)."""
    return OverallLevelConfig(
        fft_size=config.fft_size, window_type=config.window_type, tracking_mode="rpm",
        step=config.step, direction=config.direction, hysteresis=config.hysteresis,
        remove_dc=config.remove_dc,
    )


def build_overall_level_missing_line(blocks: List[NVHDataBlock]) -> Optional[str]:
    """
    The one log line for an order tracking run asked for its Overall Level curve that
    came back without one (ADR §1.141 point 12), or None when it is there.
    """
    if not blocks or any(b.kind == KIND_OVERALL_LEVEL for b in blocks):
        return None
    channel = blocks[0].provenance.parents[0] if blocks[0].provenance.parents else blocks[0].name
    return (
        f"WARNING: Overall Level and Residual not drawn for {channel}: their band (F min "
        f"{OverallLevelConfig().f_start:g} Hz) is empty below this file's Nyquist frequency."
    )


def compute_spectrogram(vib_block: NVHDataBlock, tacho_block: Optional[NVHDataBlock],
                        config: SpectrogramConfig,
                        scratch: Optional[MutableMapping[str, Any]] = None) -> NVHDataBlock:
    """
    Vibration block (and tacho, unless tracking against time) in, one tracked
    waterfall block out.

    This is the path SpectralRequests runs on a worker thread, exposed
    synchronously so the block workflow (§1.6) reaches a spectrogram through the
    one place a raw waterfall becomes a block -- not a fourth hand-assembled
    copy of it (§1.12).

    An rpm-tracked waterfall without a tacho raises rather than quietly falling
    back to time slices. In a batch that fallback would write a result set whose
    params say "rpm, step 50" over a file that has no speed signal at all, and
    nothing downstream could tell it from a real one; a raised error becomes a
    per-file message and a "partial" set instead.

    `scratch` is the same per-measurement bag `compute_order_cuts` takes. A
    spectrogram and an order cut with the same tracking mode, step, direction
    and hysteresis over one measurement share the same `TrackingPlan` from it
    (ADR §1.58 point 6), and a multi-channel spectrogram batch builds its plan
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

    direction = normalize_dsp_choice(config.direction, VALID_SWEEP_DIRECTIONS, "direction")
    if not against_time and direction == "any":
        raise ValueError(
            "Any-direction sweep is not supported for an RPM spectrogram: a "
            "run-up plus run-down crosses each speed twice, so the image columns "
            "no longer line up with the RPM axis. Pick Up or Down."
        )

    values = vib_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, vib_block.channel_type)

    if against_time:
        fs = resolve_sampling_frequency(vib_block)
        tacho_rpm = None
    else:
        fs, tacho_rpm = _timed("tacho_to_rpm", resolve_and_convert_tacho, vib_block, tacho_block, scratch)

    plan = _tracking_plan_for(scratch, config, tacho_rpm, len(values), fs,
                              tracking_mode=tracking_mode)

    frequencies, z_values, magnitude_matrix = compute_tracked_spectrogram(
        vib_data=values, fs=fs, fft_size=config.fft_size,
        window_type=config.window_type, plan=plan,
    )

    win, acf, ecf_linear, enbw_factor = generate_window(config.window_type, config.fft_size)
    enbw_hz = enbw_factor * (fs / config.fft_size)

    block = _timed("result_blocks", build_spectrogram_block,
        vib_block, frequencies, z_values, magnitude_matrix,
        tracked_against_speed=not against_time, window_type=config.window_type,
        fft_size=config.fft_size, acf=acf, ecf_linear=ecf_linear, enbw_hz=enbw_hz,
        computation=computation_params(config),
    )
    require_uniform_rpm_axis(block)
    return block


def _effective_overall_level_band(config: OverallLevelConfig, fs: float) -> Tuple[float, float]:
    """
    The band integrated over this file: F max clipped to its Nyquist, and Full
    Bandwidth (`f_stop=None`) being exactly that Nyquist. Clipped rather than
    refused so a batch over files at mixed rates does not fail for no reason
    (ADR §1.62 point 9); an F min at or past Nyquist leaves nothing to clip to
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
    Level curve out: the energy of one fixed band per tracking step (ADR §1.62).

    Refuses rpm tracking without a tacho for the reason compute_spectrogram
    does. Unlike the spectrogram it allows Any direction in both modes: the
    result is an x/y curve like an order cut, and the ban there is about the
    image grid, not the maths (§1.58 point 8).

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
        fs, tacho_rpm = _timed("tacho_to_rpm", resolve_and_convert_tacho, vib_block, tacho_block, scratch)

    band = _effective_overall_level_band(config, fs)

    values = vib_block.values
    if config.remove_dc:
        values = _timed("remove_dc", remove_dc_offset, values, vib_block.channel_type)

    plan = _tracking_plan_for(scratch, config, tacho_rpm, len(values), fs,
                              tracking_mode=tracking_mode)

    axis_values, levels = compute_tracked_overall_level(
        values, fs, config.fft_size, config.window_type,
        f_start=band[0], f_stop=band[1], plan=plan,
    )

    return _timed("result_blocks", build_overall_level_block,
        vib_block, axis_values, levels,
        tracked_against_speed=not against_time, window_type=config.window_type,
        fft_size=config.fft_size, f_start=config.f_start, f_stop=config.f_stop,
        effective_band=band, computation=computation_params(config),
    )
