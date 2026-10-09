# =====================================================================
# FILE: signal_processing/dsp/tracking.py
# =====================================================================
"""
Where in a record an analysis block is cut, and the speed trace that decides it.

Two things live here. `clean_rpm_profile` turns a raw tacho into a usable speed
trace, and `generate_tracking_triggers` turns that trace into the sample indices
a spectrum is computed at -- every N seconds (time mode) or every N rpm on the
way up or down a sweep (rpm mode).

`TrackingPlan` bundles the two so a caller that runs many vibration channels
against **one** tacho pays for them once. Both depend only on the tacho, the
sample rate and the sweep settings -- never on the vibration channel -- so
recomputing them per channel is pure waste, and it was the single largest cost
of a "Calculate & Save Data" batch (BUGS.md K2).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy.ndimage import uniform_filter1d

from core.dsp_configs import (
    VALID_SWEEP_DIRECTIONS,
    VALID_TRACKING_MODES,
    normalize_dsp_choice,
)


def clean_rpm_profile(
        raw_rpm: np.ndarray, fs: float,
        max_gradient_rpm_s: float = 200000.0, smoothing_window_s: float = 0.05
) -> np.ndarray:
    n_samples = len(raw_rpm)
    finite = np.isfinite(raw_rpm)
    if n_samples and not np.any(finite):
        raise ValueError("Tacho channel contains no finite samples (all NaN/inf).")
    if n_samples < 2: return raw_rpm.copy()

    dt = 1.0 / fs
    cleaned_rpm = raw_rpm.copy()

    with np.errstate(invalid='ignore'):
        gradients = np.abs(np.diff(cleaned_rpm) / dt)
    spike_flags = np.zeros(n_samples, dtype=bool)
    spike_flags[1:] = gradients > max_gradient_rpm_s
    spike_flags[:-1] = spike_flags[:-1] | spike_flags[1:]
    # A NaN gradient never compares greater than anything, so a NaN sample
    # would slip past the test above and the smoother would smear it over a
    # whole window -- leaving no usable speed range at all (#304).
    spike_flags |= ~finite

    if np.any(spike_flags):
        valid_indices = np.where(~spike_flags)[0]
        invalid_indices = np.where(spike_flags)[0]
        if len(valid_indices) == 0:
            # Everything is spiky: keep the finite samples, fill only the gaps.
            valid_indices = np.where(finite)[0]
            invalid_indices = np.where(~finite)[0]
        cleaned_rpm[invalid_indices] = np.interp(invalid_indices, valid_indices, cleaned_rpm[valid_indices])

    window_len = int(round(smoothing_window_s * fs))
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
    elif direction == "down":
        low = np.searchsorted(targets, following, side="right")   # T >  rpm[i+1]
        high = np.searchsorted(targets, previous, side="right")   # T <= rpm[i]
    else:
        up_targets, up_samples = _interior_crossings(rpm_profile, targets, "up")
        down_targets, down_samples = _interior_crossings(rpm_profile, targets, "down")
        pairs = np.unique(
            np.stack([np.concatenate([up_targets, down_targets]),
                      np.concatenate([up_samples, down_samples])], axis=1),
            axis=0,
        ) if up_targets.size or down_targets.size else np.empty((0, 2), dtype=np.int64)
        return pairs[:, 0], pairs[:, 1]

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
    if direction == "down":
        return (current <= targets + tol) & (previous >= targets - tol) & (previous > current)
    # "any" tried up first and then down; both can never hold at once, because
    # each demands the opposite sign of (current - previous).
    return (_endpoint_reaches(rpm_profile, targets, "up", tol)
            | _endpoint_reaches(rpm_profile, targets, "down", tol))


def _accept_after_hysteresis(rpm_profile: np.ndarray, crossings: np.ndarray,
                             target: float, direction: str,
                             hysteresis_rpm: float) -> np.ndarray:
    """
    Which of one target's crossings survive the noise guard: a repeat only
    counts once the speed has genuinely left the target's neighbourhood in
    between, otherwise a trace dithering across a target fires once per wobble.

    The span between two accepted crossings is reduced once with reduceat
    rather than re-scanned per crossing. The acceptance itself stays a walk,
    because whether a crossing is accepted depends on which one was accepted
    before it -- but it walks over per-segment extremes, not over the samples.
    """
    if crossings.size < 2:
        return crossings

    span_start, span_stop = int(crossings[0]), int(crossings[-1])
    span = rpm_profile[span_start:span_stop]
    local_edges = crossings[:-1] - span_start

    if direction == "up":
        segment_extremes = np.minimum.reduceat(span, local_edges)
        left_the_band = segment_extremes < (target - hysteresis_rpm)
    elif direction == "down":
        segment_extremes = np.maximum.reduceat(span, local_edges)
        left_the_band = segment_extremes > (target + hysteresis_rpm)
    else:
        segment_extremes = np.maximum.reduceat(np.abs(span - target), local_edges)
        left_the_band = segment_extremes > hysteresis_rpm

    accepted = [crossings[0]]
    # Running extreme since the last accepted crossing: the span between two
    # accepted crossings is the union of the segments skipped in between.
    running = left_the_band[0]
    for position in range(1, crossings.size):
        if running:
            accepted.append(crossings[position])
            running = left_the_band[position] if position < left_the_band.size else False
        else:
            running = running or (left_the_band[position] if position < left_the_band.size else False)
    return np.asarray(accepted, dtype=crossings.dtype)


def generate_tracking_triggers(
        time_vector: np.ndarray, rpm_profile: np.ndarray, fs: float, tracking_mode: str = "rpm",
        start_limit: float = 0.0, stop_limit: float = 100000.0, increment: float = 100.0,
        direction: str = "up", hysteresis_rpm: float = 10.0
) -> Tuple[List[float], List[float], List[str]]:
    n_samples = len(rpm_profile)
    if n_samples == 0: return [], [], []

    # "Up", "bogus" and "" used to all land in the bidirectional / rpm branch
    # silently; an unknown tracking_mode fell to rpm -- audit 02 F7-A / 7.7.
    tracking_mode = normalize_dsp_choice(tracking_mode, VALID_TRACKING_MODES, "tracking_mode")
    direction = normalize_dsp_choice(direction, VALID_SWEEP_DIRECTIONS, "direction")

    dt = 1.0 / fs

    if tracking_mode == "time":
        t_start, t_stop = min(start_limit, stop_limit), max(start_limit, stop_limit)
        if increment <= 0.0:
            return [], [], []

        targets = np.arange(t_start, t_stop + 1e-12, abs(increment))
        if targets.size == 0:
            return [], [], []

        # One searchsorted places every trigger at once. The previous version
        # walked all n_samples in Python to find a few hundred of them: at
        # 25.6 kHz over a 75 s record that is three million iterations, while the
        # RPM branch below was already vectorised.
        indices = np.searchsorted(time_vector, targets, side="left")

        keep = indices < n_samples
        indices = indices[keep]
        if indices.size:
            keep = time_vector[indices] <= t_stop
            indices = indices[keep]

        if indices.size and direction in ("up", "down") and n_samples > 1:
            # Reject a target whose sample is moving against the requested sweep
            # direction. The old loop instead held the target back and then fired
            # a burst of catch-up triggers once the slope agreed again, which put
            # several analysis blocks on almost the same instant.
            slope = np.gradient(rpm_profile, dt)[indices]
            agrees = slope >= -0.1 if direction == "up" else slope <= 0.1
            indices = indices[agrees]

        return (indices.tolist(),
                time_vector[indices].tolist(),
                ["time"] * indices.size)

    # --- RPM tracking: one pass over the profile, not one per target ---------
    # Guarded the same way the time branch above is: np.arange with a zero step
    # raises ZeroDivisionError from inside numpy, which reaches the user as a
    # stack trace instead of the caller's "no tracking triggers" message.
    if increment <= 0.0:
        return [], [], []

    rpm_min, rpm_max = min(start_limit, stop_limit), max(start_limit, stop_limit)

    # The grid is anchored to whole multiples of the step, not to whatever the
    # slowest sample of THIS particular recording happened to be. Two runs of
    # the same test that idle at 118 and 132 rpm otherwise produce order cuts
    # sampled at 118/168/218... and 132/182/232... -- nominally identical
    # settings, yet no two points share a speed, so the two curves cannot be
    # read against each other. The epsilon keeps a limit that already sits on a
    # multiple (0 rpm after the standstill clamp, say) from being pushed up a
    # whole step by float noise.
    step = abs(increment)
    first_target = np.ceil(rpm_min / step - 1e-9) * step
    targets = np.arange(first_target, rpm_max + 1e-5, step)
    if targets.size == 0 or n_samples < 2:
        return [], [], []

    target_index, sample_index = _interior_crossings(rpm_profile, targets, direction)

    tol = max(abs(increment) * 1e-4, 1e-6)
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
        return [], [], []

    # Runs even at hysteresis 0: the guard is "did the speed leave the band",
    # and at zero width that still rejects a repeat crossing whose in-between
    # samples only ever touched the target exactly. Only targets crossed more
    # than once can lose anything, and on a clean monotone sweep there are none.
    group_starts = np.flatnonzero(np.diff(target_index, prepend=-1))
    group_ends = np.append(group_starts[1:], target_index.size)
    kept = [
        _accept_after_hysteresis(rpm_profile, sample_index[start:stop],
                                 float(targets[target_index[start]]),
                                 direction, hysteresis_rpm)
        for start, stop in zip(group_starts, group_ends)
    ]
    surviving = np.concatenate(kept)
    if surviving.size != sample_index.size:
        keep_counts = np.array([block.size for block in kept])
        target_index = np.repeat(target_index[group_starts], keep_counts)
        sample_index = surviving

    if sample_index.size == 0:
        return [], [], []

    trigger_values = targets[target_index]
    trigger_indices = _interpolated_crossing_indices(rpm_profile, sample_index, trigger_values)

    return (trigger_indices.tolist(),
            trigger_values.tolist(),
            ["sweep"] * trigger_values.size)


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
    direction: str
    hysteresis_rpm: float
    cleaned_rpm: np.ndarray
    trigger_indices: np.ndarray
    axis_values: np.ndarray

    def __post_init__(self):
        # Read-only for the same reason NVHDataBlock's values are: one plan is
        # handed to every channel of a file, and a consumer that scaled or
        # sorted it in place would silently change what the next channel is
        # measured against.
        for array in (self.cleaned_rpm, self.trigger_indices, self.axis_values):
            array.setflags(write=False)

    def matches(self, fs: float, n_samples: int, step: Optional[float] = None,
                direction: Optional[str] = None,
                hysteresis_rpm: Optional[float] = None) -> bool:
        """
        Whether this plan was built for the signal *and* the sweep settings a
        caller is about to cut against.

        The sweep arguments are optional only for backwards compatibility: a
        plan carries `step`, `direction` and `hysteresis_rpm`, and a caller that
        passes them but leaves them unchecked (as this did before audit 02 /
        7.6) will happily cut an order against a plan built on a different rpm
        grid, with nothing in the result to show for it.
        """
        if self.n_samples != n_samples or float(self.fs) != float(fs):
            return False
        if step is not None and float(self.step) != float(step):
            return False
        if direction is not None and self.direction != direction:
            return False
        if hysteresis_rpm is not None and float(self.hysteresis_rpm) != float(hysteresis_rpm):
            return False
        return True


def build_tracking_plan(
        tacho_data: Optional[np.ndarray], n_samples: int, fs: float,
        step: float, direction: str, hysteresis_rpm: float,
        tracking_mode: str = "rpm",
) -> TrackingPlan:
    """
    Clean the tacho, place the triggers, and sort them into the order the
    result axis needs -- once, for however many channels share this tacho.

    Time mode carries a zero rpm profile and sorts by sample index; rpm mode
    sorts by speed, so a run-down reads left to right like a run-up.
    """
    tracking_mode = normalize_dsp_choice(tracking_mode, VALID_TRACKING_MODES, "tracking_mode")
    direction = normalize_dsp_choice(direction, VALID_SWEEP_DIRECTIONS, "direction")

    time_vector = np.arange(n_samples) / fs

    if tracking_mode == "time" or tacho_data is None:
        mode = "time"
        cleaned_rpm = np.zeros(n_samples, dtype=np.float64)
        start_limit = float(time_vector[0]) if n_samples else 0.0
        stop_limit = float(time_vector[-1]) if n_samples else 0.0
    else:
        mode = "rpm"
        cleaned_rpm = clean_rpm_profile(tacho_data, fs)
        # A motor run in reverse logs negative rpm all the way down to the
        # run's top speed (-35 000 in the Step2/Sweep2 exports, #456), while
        # order frequencies only follow the magnitude. Flip such a run rather
        # than take abs(): standstill noise stays below zero either way, so
        # the clamp below treats both directions alike.
        if -float(np.min(cleaned_rpm)) > float(np.max(cleaned_rpm)):
            cleaned_rpm = -cleaned_rpm
        # A real tacho reads noise around zero at standstill -- the measured
        # Setup1-Sweep1-1 data dips to -406 rpm -- and the smoothing above
        # spreads that rather than removing it. Negative speeds would put the
        # frequency band below DC, where nothing can be measured, so the sweep
        # starts at zero. Restricting the range properly still belongs in the
        # UI as explicit start/stop rpm limits, the way Testlab does it.
        start_limit = max(0.0, float(np.min(cleaned_rpm)))
        stop_limit = float(np.max(cleaned_rpm))

    # Standstill noise crosses 0 rpm upward again and again, and the hysteresis
    # cannot hold it back: Setup1-Sweep1-1 got 21 blocks at 0 rpm, all from the
    # noise after the run-down (#457). A run-up only counts from the last
    # sample at or below zero before the top speed, a run-down up to the first
    # one after it.
    first, last = 0, n_samples
    if mode == "rpm" and direction in ("up", "down") and n_samples:
        peak = int(np.argmax(cleaned_rpm))
        if direction == "up":
            at_rest = np.flatnonzero(cleaned_rpm[:peak + 1] <= 0.0)
            first, last = (int(at_rest[-1]) if at_rest.size else 0), peak + 1
        else:
            at_rest = np.flatnonzero(cleaned_rpm[peak:] <= 0.0)
            first, last = peak, (peak + int(at_rest[0]) + 1 if at_rest.size else n_samples)

    indices, values, _ = generate_tracking_triggers(
        time_vector=time_vector[first:last], rpm_profile=cleaned_rpm[first:last], fs=fs,
        tracking_mode=mode, start_limit=start_limit, stop_limit=stop_limit, increment=step,
        direction=direction, hysteresis_rpm=hysteresis_rpm,
    )

    trigger_indices = np.asarray(indices, dtype=np.float64) + first
    axis_values = np.asarray(values, dtype=np.float64)
    if trigger_indices.size:
        order = np.argsort(axis_values) if mode == "rpm" else np.argsort(trigger_indices)
        trigger_indices = trigger_indices[order]
        axis_values = axis_values[order]

    return TrackingPlan(
        mode=mode, fs=fs, n_samples=n_samples, step=step, direction=direction,
        hysteresis_rpm=hysteresis_rpm, cleaned_rpm=cleaned_rpm,
        trigger_indices=trigger_indices, axis_values=axis_values,
    )
