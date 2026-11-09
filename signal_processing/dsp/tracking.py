# =====================================================================
# FILE: signal_processing/dsp/tracking.py
# =====================================================================
"""
Where in a record an analysis block is cut, and the speed trace that decides it.

`clean_rpm_profile` is Tacho cleaning: it turns a raw tacho, on its own rate,
into a usable speed trace. `build_tracking_plan` takes that trace on the
channel's time axis (after Tacho interpolation, ADR §1.306) and places the
sample indices a spectrum is computed at -- every N seconds (time mode) or
every N rpm on the way up or down a sweep (rpm mode). The trigger search behind
it is private: it trusts the plan's checked mode and direction, ordered limits
and positive step.

`TrackingPlan` bundles the two so a caller that runs many vibration channels
against **one** tacho pays for them once. Both depend only on the tacho, the
sample rate and the sweep settings -- never on the vibration channel -- so
recomputing them per channel is pure waste, and it was the single largest cost
of a "Calculate & Save Data" batch (BUGS.md K2).
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from core.dsp_configs import VALID_SWEEP_DIRECTIONS, VALID_TRACKING_MODES, TrackingSweep
from core.tacho_cleaning import DEFAULT_TACHO_CLEANING, TachoCleaning

# The Hampel filter's neighbourhood: the sample and five on each side. A median
# of 11 holds while up to 5 of them are bad, so a dropout of 5 samples is still
# judged against good neighbours.
HAMPEL_WINDOW_SAMPLES = 11
# Floor for the noise sigma, relative to the trace's largest |rpm|. A noise-free
# trace (a synthetic ramp, a tacho held from pulse to pulse) has a MAD of 0; a
# zero threshold would flag float rounding, this floor still flags a real spike.
_HAMPEL_SIGMA_FLOOR = 1e-9
# MAD -> standard deviation for Gaussian noise.
_MAD_TO_SIGMA = 1.4826


def _hampel_spikes(rpm: np.ndarray, threshold_sigma: float) -> np.ndarray:
    """
    The samples the Hampel filter flags in a finite `rpm` trace: those further
    than `threshold_sigma` noise sigmas from the median of their neighbourhood.

    Sigma is one robust estimate for the whole trace (MAD of the deviations),
    not one per window: a MAD of 11 samples is itself too noisy to judge by.
    It replaced a test on the step between neighbours, which at 25.6 kHz read
    ordinary tacho noise as spikes on 96 % of the samples and left the speed
    ~11 rpm low (#837).
    """
    neighbourhood = median_filter(rpm, size=HAMPEL_WINDOW_SAMPLES, mode='nearest')
    deviation = np.abs(rpm - neighbourhood)
    sigma = max(_MAD_TO_SIGMA * float(np.median(deviation)),
                _HAMPEL_SIGMA_FLOOR * float(np.max(np.abs(rpm))))
    return deviation > threshold_sigma * sigma


def clean_rpm_profile(
        raw_rpm: np.ndarray, fs: float, cleaning: TachoCleaning = DEFAULT_TACHO_CLEANING,
) -> np.ndarray:
    """
    Tacho cleaning of a raw tacho at its own rate `fs`: NaN/inf bridged, spikes
    replaced by the Hampel filter at `cleaning.tacho_hampel_sigma`, then a
    moving average of `cleaning.tacho_smoothing_ms`. A non-finite sample counts
    as a spike; with the Hampel filter off it is still filled, and with a 0 ms
    window too the result is the raw tacho otherwise.
    """
    n_samples = len(raw_rpm)
    finite = np.isfinite(raw_rpm)
    if n_samples and not np.any(finite):
        raise ValueError("Tacho channel contains no finite samples (all NaN/inf).")
    if n_samples < 2: return raw_rpm.copy()

    cleaned_rpm = raw_rpm.copy()

    # A NaN or inf would poison the neighbourhood median, so the filter judges a
    # trace with them bridged; they are spikes in their own right (#304: a NaN
    # the smoother saw smeared over a whole window, leaving no usable speed range).
    finite_indices = np.where(finite)[0]
    bridged = cleaned_rpm if finite.all() else np.interp(
        np.arange(n_samples), finite_indices, cleaned_rpm[finite_indices])
    spike_flags = ~finite
    if cleaning.tacho_hampel_filter:
        spike_flags |= _hampel_spikes(bridged, cleaning.tacho_hampel_sigma)

    # Never every sample: the threshold is a multiple of the median deviation, so
    # at most about half of a trace lies beyond it, and a NaN-only trace was refused.
    if np.any(spike_flags):
        valid_indices = np.where(~spike_flags)[0]
        invalid_indices = np.where(spike_flags)[0]
        cleaned_rpm[invalid_indices] = np.interp(invalid_indices, valid_indices, cleaned_rpm[valid_indices])

    window_len = int(round(cleaning.tacho_smoothing_ms / 1000.0 * fs))
    if window_len > 1:
        window_len = min(window_len, n_samples)
        # uniform_filter1d runs the boxcar as a sliding sum in O(n); np.convolve
        # with an explicit ones/window_len kernel is a direct O(n * window_len)
        # convolution, which at 25.6 kHz and a 50 ms window is 1280 taps over
        # 1.9 M samples -- 2.5e9 multiply-adds to compute a moving average.
        # 'nearest' is the same edge clamping np.pad(mode='edge') gave, and for
        # an even window it covers the same [i - w//2, i + w//2 - 1] span, so
        # the documented leading/trailing bias (see the tests) is unchanged.
        cleaned_rpm = uniform_filter1d(cleaned_rpm, size=window_len, mode='nearest')

    return cleaned_rpm


def _interpolated_crossing_indices(
        rpm_profile: np.ndarray, samples_after: np.ndarray, targets: np.ndarray
) -> np.ndarray:
    """
    Fractional sample index of where rpm_profile actually equals each target,
    found by linear interpolation between sample_after - 1 and sample_after
    (the pair the boolean crossing test straddles).

    Snapping to sample_after outright biases every trigger up to one whole
    sample late, which centres the analysis window on an instant where the
    true speed is already past the target -- worth up to one dt of timing
    jitter, small for low orders but enough to blur high orders across bins on
    a fast sweep. compute_order_cuts_from_raw's chunk extraction rounds this
    fractional index to the nearest sample rather than always flooring it.

    A flat pair (span 0) cannot be interpolated and falls back to the sample
    itself.

    frac is clamped to [0, 1]. An interior crossing is already inside that
    interval by construction (rpm[i] <= T < rpm[i+1], or its mirror on the
    way down), so the clamp leaves it
    bit-identical; it only bites on an endpoint trigger that _endpoint_reaches
    accepted within its tolerance. There the target can sit just past the last
    sample (or just short of the one before it), and on a nearly flat final pair
    the extrapolation lands thousands of samples outside the record -- a block of zeros, or one that only catches the
    window's leading edge and gets a coverage gain in the thousands.
    """
    r_prev = rpm_profile[samples_after - 1]
    r_curr = rpm_profile[samples_after]
    span = r_curr - r_prev
    flat = span == 0.0

    with np.errstate(divide='ignore', invalid='ignore'):
        frac = np.clip((targets - r_prev) / span, 0.0, 1.0)
    return np.where(flat, samples_after.astype(np.float64), (samples_after - 1) + frac)


def _interior_crossings(
        rpm_profile: np.ndarray, targets: np.ndarray, direction: str
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Every (target, sample) crossing in the record, in one pass over the profile.

    The obvious implementation loops over the targets and runs a full-length
    boolean comparison per target. That is O(n_targets * n_samples): on the
    25.6 kHz x 75 s records this tool is built for, halving Step [RPM] from 50
    to 10 took trigger generation from 0.7 s to 4.2 s, which is most of what
    made an order recalculation feel frozen (BUGS.md K2).

    Turn it around instead. A sample pair (i, i+1) crosses target T upwards iff
    `rpm[i] <= T < rpm[i+1]`, and since `targets` is sorted ascending, the set
    of targets one pair crosses is a *contiguous slice* of it -- two
    searchsorted lookups per pair, then one repeat-expansion for the whole
    record. The bounds are written as the same `<=` / `<` comparisons the
    per-target loop made on the same float values, so the answer is identical
    bit for bit, not merely close.

    Returns (target_index, sample_index), sorted by target and then by sample,
    which is the order the per-target loop produced.
    """
    previous = rpm_profile[:-1]
    following = rpm_profile[1:]

    if direction == "up":
        low = np.searchsorted(targets, previous, side="left")     # T >= rpm[i]
        high = np.searchsorted(targets, following, side="left")   # T <  rpm[i+1]
    else:
        low = np.searchsorted(targets, following, side="right")   # T >  rpm[i+1]
        high = np.searchsorted(targets, previous, side="right")   # T <= rpm[i]

    counts = np.maximum(high - low, 0)
    pairs_with_crossings = np.flatnonzero(counts > 0)
    if pairs_with_crossings.size == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    repeats = counts[pairs_with_crossings]
    total = int(repeats.sum())
    # Offset of each crossing within its own pair's contiguous target slice.
    group_starts = np.cumsum(repeats) - repeats
    within_group = np.arange(total) - np.repeat(group_starts, repeats)

    target_index = np.repeat(low[pairs_with_crossings], repeats) + within_group
    # +1 because the crossing is credited to the later sample of the pair.
    sample_index = np.repeat(pairs_with_crossings, repeats) + 1

    order = np.lexsort((sample_index, target_index))
    return target_index[order], sample_index[order]


def _endpoint_reaches(rpm_profile: np.ndarray, targets: np.ndarray,
                      direction: str, tol: float) -> np.ndarray:
    """
    Which targets the final sample pair reaches, as a boolean per target.

    The interior crossing test needs a sample strictly past the target, so a
    sweep that ends exactly at rpm_max (up) or rpm_min (down) never satisfies
    it for that final target -- there is no sample after the last one to be
    strictly past it. Treat the last sample pair as reaching the target
    (inclusive) instead, but only when it genuinely approaches from the
    correct side, so a trace that starts flat at the target doesn't fire a
    phantom trigger at index 0.
    """
    if len(rpm_profile) < 2:
        return np.zeros(targets.shape, dtype=bool)

    previous, current = rpm_profile[-2], rpm_profile[-1]
    if direction == "up":
        return (current >= targets - tol) & (previous <= targets + tol) & (previous < current)
    return (current <= targets + tol) & (previous >= targets - tol) & (previous > current)


def _compute_time_triggers(
        time_vector: np.ndarray, t_start: float, t_stop: float, step: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    (sample index, time) of a block every `step` seconds from `t_start` to
    `t_stop`. The caller gives an ordered range (t_start <= t_stop) and a
    positive step; a target with no sample at or before `t_stop` is dropped.
    """
    empty = np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    if time_vector.size == 0:
        return empty

    targets = np.arange(t_start, t_stop + 1e-12, step)
    # A Tracking range that starts before the record (#807) would put every
    # target ahead of the first sample on that one sample.
    targets = targets[targets >= time_vector[0]]
    if targets.size == 0:
        return empty

    # One searchsorted places every trigger at once. The previous version
    # walked all n_samples in Python to find a few hundred of them: at
    # 25.6 kHz over a 75 s record that is three million iterations, while the
    # RPM branch below was already vectorised.
    indices = np.searchsorted(time_vector, targets, side="left")
    indices = indices[indices < time_vector.size]
    indices = indices[time_vector[indices] <= t_stop]
    return indices, time_vector[indices]


def _compute_rpm_triggers(
        rpm_profile: np.ndarray, rpm_min: float, rpm_max: float, step: float, direction: str
) -> Tuple[np.ndarray, np.ndarray]:
    """
    (fractional sample index, target rpm) of one block per multiple of `step`
    between `rpm_min` and `rpm_max`, where `rpm_profile` first reaches it in
    `direction` ("up" or "down"). The caller gives a positive step and a
    checked direction; rpm_min above rpm_max is an empty grid.
    """
    empty = np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    n_samples = len(rpm_profile)

    # The grid is anchored to whole multiples of the step, not to whatever the
    # slowest sample of THIS particular recording happened to be. Two runs of
    # the same test that idle at 118 and 132 rpm otherwise produce order cuts
    # sampled at 118/168/218... and 132/182/232... -- nominally identical
    # settings, yet no two points share a speed, so the two curves cannot be
    # read against each other. The epsilon keeps a limit that already sits on a
    # multiple (0 rpm after the standstill clamp, say) from being pushed up a
    # whole step by float noise.
    first_target = np.ceil(rpm_min / step - 1e-9) * step
    targets = np.arange(first_target, rpm_max + 1e-5, step)
    if targets.size == 0 or n_samples < 2:
        return empty

    target_index, sample_index = _interior_crossings(rpm_profile, targets, direction)

    tol = max(step * 1e-4, 1e-6)
    last_sample = n_samples - 1
    endpoint = _endpoint_reaches(rpm_profile, targets, direction, tol)
    if endpoint.any():
        # A target whose crossings already end on the last sample must not get
        # a second trigger there.
        already_at_end = np.zeros(targets.shape, dtype=bool)
        at_end = sample_index == last_sample
        if at_end.any():
            already_at_end[target_index[at_end]] = True
        extra = np.flatnonzero(endpoint & ~already_at_end)
        if extra.size:
            target_index = np.concatenate([target_index, extra])
            sample_index = np.concatenate([sample_index,
                                           np.full(extra.shape, last_sample, dtype=sample_index.dtype)])
            order = np.lexsort((sample_index, target_index))
            target_index, sample_index = target_index[order], sample_index[order]

    if target_index.size == 0:
        return empty

    # One block per target: the first time the speed reaches it (#745). The
    # crossings are sorted by target and then by sample, so each target's
    # first entry is its earliest one. A later return to the same speed -- a
    # plateau wobbling on the target, a plateau that sags before the next ramp,
    # a dip and recovery -- is a spectrum from another instant at a speed the
    # axis already has, and repeating it breaks the even rpm axis.
    first_of_each = np.flatnonzero(np.diff(target_index, prepend=-1))
    target_index, sample_index = target_index[first_of_each], sample_index[first_of_each]

    trigger_values = targets[target_index]
    return _interpolated_crossing_indices(rpm_profile, sample_index, trigger_values), trigger_values


@dataclass(frozen=True, eq=False)
class TrackingPlan:
    """
    Everything about *where* blocks get cut, for one tacho and one set of sweep
    settings -- and nothing about the vibration channel being cut.

    That split is the whole point. `compute_order_cuts_from_raw` used to clean
    the rpm profile and place the triggers itself, so a batch over the 17
    channels of one file redid identical work 17 times. Hoisting it here lets a
    caller that already reads the tacho once place the triggers once too -- the
    workflow runner does it through `run_graph`'s per-measurement `scratch` bag.

    Measured on the real 75 s / 1.92 M-sample run-up (2026-09-03): building the
    plan is 0.076 s against 0.016 s for the cuts themselves, so rebuilding it per
    channel costs ~1.3 s on a 17-channel file. The figure this docstring used to
    quote -- 0.94 s per channel, ~16 s per file -- predates the vectorised
    crossing search (audit section 5) and was a full order of magnitude stale.

    Deliberately not an NVHDataBlock: this is not a measured signal, it is the
    intermediate state of one computation, and it never reaches the plot, the
    cache or the project.
    """

    mode: str
    fs: float
    n_samples: int
    step: float
    direction: Optional[str]    # None in time mode, which has no direction
    cleaned_rpm: np.ndarray
    trigger_indices: np.ndarray
    axis_values: np.ndarray
    start_time: float = 0.0
    # The sweep the plan was asked for, Tracking range included -- what
    # `require_tracking_triggers` says when the plan came out empty. None is a
    # sweep without a range.
    sweep: Optional[TrackingSweep] = None

    def __post_init__(self):
        # Read-only for the same reason NVHDataBlock's values are: one plan is
        # handed to every channel of a file, and a consumer that scaled or
        # sorted it in place would silently change what the next channel is
        # measured against.
        for array in (self.cleaned_rpm, self.trigger_indices, self.axis_values):
            array.setflags(write=False)

    def matches(self, fs: float, n_samples: int) -> bool:
        """Whether this plan was built for the signal a caller is about to cut."""
        return self.n_samples == n_samples and float(self.fs) == float(fs)


def build_tracking_plan(
        speed_rpm: Optional[np.ndarray], n_samples: int, fs: float,
        sweep: TrackingSweep, start_time: float = 0.0,
) -> TrackingPlan:
    """
    Place the triggers on `speed_rpm` and sort them into the order the result
    axis needs -- once, for however many channels share this tacho.
    `speed_rpm` is the tacho after Tacho cleaning (`clean_rpm_profile`) and
    Tacho interpolation, one finite value per sample of the channel; None
    (no tacho) runs the plan in time mode.

    Time mode carries a zero rpm profile and sorts by sample index; rpm mode
    sorts by speed, so a run-down reads left to right like a run-up. Rpm mode
    has one block per target speed, from its first crossing, so its axis is
    strictly increasing and evenly spaced by construction.

    `start_time` is the time of the first sample. A time-mode axis counts
    from it, so it reads like the time signal of a recording that does not
    start at 0 s (#739); rpm mode does not use it.

    `sweep` is taken as `resolve_tracking_sweep` gave it: its mode and, in
    rpm mode, its direction are checked, not normalised (a time sweep has
    none, ADR §1.302), and its Tacho cleaning is used as is
   . The plan keeps this very sweep, even when a missing tacho
    runs it in time mode.

    `sweep.rpm_min` / `sweep.rpm_max` are the Tracking range in rpm mode, in positive rpm
    even for a reverse-rotation run; None is auto -- 0 rpm and the record's top
    speed, which give exactly the plan without a range. A run-up starts at the
    last sample at or below the minimum before the top speed, a run-down ends
    at the first one after it, and targets above the maximum are dropped. The
    grid stays on multiples of the step. Time mode ignores them.

    `sweep.time_start` / `sweep.time_end` are the Tracking range in time mode (#807), in
    the time of the axis -- from `start_time`, not from the first sample.
    None is auto, the whole record. The first block sits on the start, then
    every step, so the grid is not on multiples of the step. Rpm
    mode ignores them.

    `sweep.tacho_cleaning` is what `speed_rpm` was cleaned with (ADR §1.211,
    §1.306): it keeps a plan apart from another cleaning's, the plan does not
    clean again.
    """
    _require_choice(sweep.mode, VALID_TRACKING_MODES, "tracking_mode")
    if sweep.mode == "rpm":
        _require_choice(sweep.direction, VALID_SWEEP_DIRECTIONS, "direction")
    step, direction = sweep.step, sweep.direction
    rpm_min, rpm_max = sweep.rpm_min, sweep.rpm_max
    time_start, time_end = sweep.time_start, sweep.time_end
    # An inverted range is a typing mistake to report, not an empty result;
    # the ribbon refuses it as typed, a workflow block not.
    if rpm_min is not None and rpm_max is not None and float(rpm_min) >= float(rpm_max):
        raise ValueError(
            f"Tracking range minimum ({float(rpm_min):g} rpm) must be below its "
            f"maximum ({float(rpm_max):g} rpm)."
        )
    if time_start is not None and time_end is not None and float(time_start) >= float(time_end):
        raise ValueError(
            f"Tracking range start ({float(time_start):g} s) must be before its "
            f"end ({float(time_end):g} s)."
        )

    time_vector = start_time + np.arange(n_samples) / fs

    if sweep.mode == "time" or speed_rpm is None:
        mode = "time"
        cleaned_rpm = np.zeros(n_samples, dtype=np.float64)
        start_limit = float(time_vector[0]) if n_samples else 0.0
        stop_limit = float(time_vector[-1]) if n_samples else 0.0
        # The Tracking range (#807) replaces either end; a bound past the
        # record is left to the trigger search, which keeps only its samples.
        if time_start is not None:
            start_limit = float(time_start)
        if time_end is not None:
            stop_limit = float(time_end)
    else:
        mode = "rpm"
        cleaned_rpm = np.array(speed_rpm, dtype=np.float64)
        # A motor run in reverse logs negative rpm all the way down to the
        # run's top speed (-35 000 in the Step2/Sweep2 exports, #456), while
        # order frequencies only follow the magnitude. Flip such a run rather
        # than take abs(): standstill noise stays below zero either way, so
        # the clamp below treats both directions alike.
        if -float(np.min(cleaned_rpm)) > float(np.max(cleaned_rpm)):
            cleaned_rpm = -cleaned_rpm
        # A real tacho reads noise around zero at standstill -- the measured
        # Setup1-Sweep1-1 data dips to -406 rpm -- and Tacho cleaning
        # spreads that rather than removing it. Negative speeds would put the
        # frequency band below DC, where nothing can be measured, so the sweep
        # starts at zero.
        # The Tracking range (#805) narrows that sweep: the grid starts at the
        # first multiple of the step at or above the minimum, and stops at the
        # maximum. Auto (None) is exactly the sweep above.
        floor_rpm = 0.0 if rpm_min is None else float(rpm_min)
        start_limit = max(0.0, floor_rpm, float(np.min(cleaned_rpm)))
        stop_limit = float(np.max(cleaned_rpm))
        if rpm_max is not None:
            stop_limit = min(stop_limit, float(rpm_max))

    # Standstill noise crosses 0 rpm upward again and again: Setup1-Sweep1-1
    # got 21 blocks at 0 rpm, all from the noise after the run-down (#457), and
    # even one block per target would put the low speeds in the noise before
    # the run instead of on it. A run-up only counts from the last
    # sample at or below the minimum (zero on auto) before the top speed, a
    # run-down up to the first one after it -- so a short spin-up past the
    # minimum and back before the run is not taken for the run (#805).
    first, last = 0, n_samples
    if mode == "rpm" and n_samples:
        peak = int(np.argmax(cleaned_rpm))
        if direction == "up":
            at_rest = np.flatnonzero(cleaned_rpm[:peak + 1] <= floor_rpm)
            first, last = (int(at_rest[-1]) if at_rest.size else 0), peak + 1
        else:
            at_rest = np.flatnonzero(cleaned_rpm[peak:] <= floor_rpm)
            first, last = peak, (peak + int(at_rest[0]) + 1 if at_rest.size else n_samples)

    if step <= 0.0 or start_limit > stop_limit:
        # No grid: a step the workflow form let through, or a time range
        # wholly before or after the record.
        indices, values = [], []
    elif mode == "time":
        indices, values = _compute_time_triggers(time_vector, start_limit, stop_limit, step)
    else:
        indices, values = _compute_rpm_triggers(
            cleaned_rpm[first:last], start_limit, stop_limit, step, direction)

    trigger_indices = np.asarray(indices, dtype=np.float64) + first
    axis_values = np.asarray(values, dtype=np.float64)
    if trigger_indices.size:
        order = np.argsort(axis_values) if mode == "rpm" else np.argsort(trigger_indices)
        trigger_indices = trigger_indices[order]
        axis_values = axis_values[order]

    return TrackingPlan(
        mode=mode, fs=fs, n_samples=n_samples, step=step,
        direction=direction if mode == "rpm" else None,
        cleaned_rpm=cleaned_rpm,
        trigger_indices=trigger_indices, axis_values=axis_values, start_time=start_time,
        sweep=sweep,
    )


def _require_choice(value: str, valid: tuple, field_name: str) -> None:
    # resolve_tracking_sweep spells the mode and direction but leaves an
    # unknown one for the computation to refuse.
    if value not in valid:
        raise ValueError(f"Unknown {field_name} {value!r}; expected one of {valid}.")


def _format_bound(value: Optional[float]) -> str:
    return "auto" if value is None else f"{float(value):g}"


def require_tracking_triggers(plan: TrackingPlan, measurement: str) -> None:
    """
    Raises, naming `measurement`, when the plan's Tracking range found no
    target in it -- min 40 000 rpm on a run to 35 000 rpm (#805), or 40 s on a
    record that ends at 30 s (#807). An error rather than an empty result, so
    a batch records the measurement and goes on. A plan
    without a range leaves the analysis's own "no tracking triggers" message
    to say it.
    """
    if plan.trigger_indices.size or plan.step <= 0 or plan.sweep is None:
        return
    sweep = plan.sweep
    if plan.mode == "time":
        if sweep.time_start is None and sweep.time_end is None:
            return
        first = plan.start_time
        last = plan.start_time + (plan.n_samples - 1) / plan.fs if plan.n_samples else first
        raise ValueError(
            f"No tracking triggers in measurement '{measurement}': it runs "
            f"{first:g}-{last:g} s, outside the Tracking range "
            f"{_format_bound(sweep.time_start)}-{_format_bound(sweep.time_end)} s."
        )
    if sweep.rpm_min is None and sweep.rpm_max is None:
        return
    raise ValueError(
        f"No tracking triggers in measurement '{measurement}': its speed runs "
        f"{max(0.0, float(plan.cleaned_rpm.min())):.0f}-{float(plan.cleaned_rpm.max()):.0f} rpm, "
        f"outside the Tracking range "
        f"{_format_bound(sweep.rpm_min)}-{_format_bound(sweep.rpm_max)} rpm."
    )
