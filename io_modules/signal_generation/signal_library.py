# =====================================================================
# FILE: io_modules/signal_generation/signal_library.py
# =====================================================================
"""
A version-controlled library of predefined synthetic datasets.

Every dataset is a list of measurements, and every measurement carries a fixed
seed, so `realize_dataset` writes byte-identical .asc files on any machine. That
is the whole point: the tool is moved between PCs and the same test data has to
come back exactly, without copying gigabytes of .asc around -- only this file
travels, in git.

Lives beside synthetic_pipeline.py because it is parameter data plus sequencing
over the generation engine: no Qt, no AppContext, safe on a background thread.
It is not core/ -- it is a signal-generation concern, not a general data model.

The first dataset, "engine_degradation_v1", is a run-to-run degradation study:
five fixed ramp setups (S1..S5) repeated across five runs (R0..R4), with the
motor's mechanical health worsening every run -- growing unbalance, emerging
sub-harmonics, two bearing fault orders that appear mid-life, a rising noise
floor and a progressively noisier tacho. R0 is the healthy baseline.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

FS_HZ = 25600.0  # one rate for the whole file; Nyquist 12800 Hz caps orders at ~21

# --- the seven recorded channels, identical in every measurement --------------
# acc in g, mic in Pa. The tacho column is added by the exporter.
ACC_CHANNELS = ("Motor_HSG", "Bearing_HSG", "Inverter_Cover_Z")
MIC_CHANNELS = ("HSG_1m", "Inverter_Cover_1m", "Motor_Front_1m")

RUN_CYCLES = (0, 5000, 10000, 15000, 20000)


# --- fixed ramp setups (constant across every run) ---------------------------

@dataclass(frozen=True)
class SetupSpec:
    key: str
    label: str
    ramp_type: str
    rpm_start: float
    rpm_stop: float
    direction: str
    duration: float          # seconds, already doubled from the first draft
    plateaus_on: bool = False
    plateaus: int = 0
    plateau_ratio: float = 0.0

    def physical_speeds(self) -> tuple:
        """(start, stop, max) rpm as the shaft actually moves, not as stored."""
        if self.direction == "Ramp Down":
            return self.rpm_stop, self.rpm_start, self.rpm_stop
        if self.direction == "Ramp Up & Down":
            return self.rpm_start, self.rpm_start, self.rpm_stop
        return self.rpm_start, self.rpm_stop, self.rpm_stop


SETUPS = (
    SetupSpec("S1", "SweepUp", "Linear sweep", 500.0, 35000.0, "Ramp Up", 60.0),
    SetupSpec("S2", "SweepDown", "Linear coast-down", 500.0, 35000.0, "Ramp Down", 60.0),
    SetupSpec("S3", "StepUp", "Stepped sweep", 500.0, 35000.0, "Ramp Up", 70.0,
              plateaus_on=True, plateaus=7, plateau_ratio=0.6),
    SetupSpec("S4", "UpDown", "Linear up+down", 1000.0, 30000.0, "Ramp Up & Down", 48.0),
    SetupSpec("S5", "FastUp", "Fast linear sweep", 2000.0, 35000.0, "Ramp Up", 30.0),
)


# --- health schedule --------------------------------------------------------
#
# Each entry is one physical feature: which channel carries it, how to build the
# component, and its amplitude for runs R0..R4 (None = not present yet). The
# amplitude column doubles as the human-readable "order map" printed next to the
# dataset.

def _order(value, amp, **extra):
    comp = {"type": "Order", "value": value, "amplitude": amp,
            "res_freq": extra.get("res_freq", 0.0), "res_amp": extra.get("res_amp", 0.0)}
    for k in ("amp_end", "mod_order", "mod_depth"):
        if k in extra:
            comp[k] = extra[k]
    return comp


def _sine(freq, amp):
    return {"type": "Sine signal", "value": freq, "amplitude": amp,
            "res_freq": 0.0, "res_amp": 0.0}


def _pink(amp):
    return {"type": "Pink Noise", "value": 0.0, "amplitude": amp,
            "res_freq": 0.0, "res_amp": 0.0}


def _resonance(freq, amp, q):
    return {"type": "Resonance", "value": 0.0, "amplitude": amp,
            "res_freq": freq, "res_amp": q}


@dataclass(frozen=True)
class Feature:
    key: str
    channel: str
    order: str              # label for the order map ("1.0", "0.23 +/-1", "8000 Hz", "-")
    meaning: str
    amps: tuple             # length 5, one per run, None = absent
    build: Callable         # (amp, run_idx) -> component dict


# amp_end for the unbalance grows faster than its start value: the warm-up rise
# itself gets worse as the bearing wears.
def _unbalance(amp, run_idx):
    return _order(1.0, amp, amp_end=amp * (1.15 + 0.12 * run_idx))


FEATURES = (
    # -- Motor_HSG (accelerometer, g) --------------------------------------
    Feature("mhsg_o1", "Motor_HSG", "1.0", "Rotor unbalance (+ warm-up drift)",
            (0.05, 0.10, 0.16, 0.26, 0.38), lambda a, r: _unbalance(a, r)),
    Feature("mhsg_o2", "Motor_HSG", "2.0", "Shaft misalignment",
            (0.010, 0.028, 0.042, 0.065, 0.10), lambda a, r: _order(2.0, a)),
    Feature("mhsg_o05", "Motor_HSG", "0.5", "Sub-harmonic / oil whirl",
            (None, None, 0.020, 0.036, 0.052), lambda a, r: _order(0.5, a)),
    Feature("mhsg_o3", "Motor_HSG", "3.0", "Coupling / driveline 3rd",
            (0.015, 0.015, 0.020, 0.030, 0.040), lambda a, r: _order(3.0, a)),
    Feature("mhsg_o6", "Motor_HSG", "6.0", "Driveline 6th",
            (0.010, 0.010, 0.013, 0.020, 0.030), lambda a, r: _order(6.0, a)),
    Feature("mhsg_res400", "Motor_HSG", "400 Hz", "Structural mode 400 Hz (broadband)",
            (0.008, 0.008, 0.010, 0.012, 0.015), lambda a, r: _resonance(400.0, a, 18.0)),
    Feature("mhsg_pink", "Motor_HSG", "-", "Pink noise floor",
            (0.010, 0.013, 0.020, 0.030, 0.045), lambda a, r: _pink(a)),

    # -- Bearing_HSG (accelerometer, g) -----------------------------------
    Feature("bhsg_mesh", "Bearing_HSG", "21.0", "Gear mesh + 4 kHz resonance sweep",
            (0.020, 0.020, 0.035, 0.050, 0.060),
            lambda a, r: _order(21.0, a, res_freq=4000.0, res_amp=12.0)),
    Feature("bhsg_halfmesh", "Bearing_HSG", "10.5", "Half gear-mesh harmonic",
            (0.005, 0.005, 0.008, 0.012, 0.020), lambda a, r: _order(10.5, a)),
    Feature("bhsg_bpfo", "Bearing_HSG", "0.23 +/-1", "Bearing outer-race fault (BPFO), shaft sidebands",
            (None, None, 0.015, 0.030, 0.060),
            lambda a, r: _order(0.23, a, mod_order=1.0, mod_depth=0.6)),
    Feature("bhsg_bpfi", "Bearing_HSG", "3.6 +/-1", "Bearing inner-race fault (BPFI), shaft sidebands",
            (None, None, None, 0.020, 0.045),
            lambda a, r: _order(3.6, a, mod_order=1.0, mod_depth=0.5)),
    Feature("bhsg_o1", "Bearing_HSG", "1.0", "Shaft bleed-through",
            (0.020, 0.020, 0.022, 0.025, 0.030), lambda a, r: _order(1.0, a)),
    Feature("bhsg_pink", "Bearing_HSG", "-", "Pink noise floor",
            (0.012, 0.015, 0.025, 0.040, 0.060), lambda a, r: _pink(a)),

    # -- Inverter_Cover_Z (accelerometer, g) -----------------------------
    Feature("inv_sw", "Inverter_Cover_Z", "8000 Hz", "Inverter switching tone (fixed, non-tracking)",
            (0.030, 0.030, 0.030, 0.032, 0.035), lambda a, r: _sine(8000.0, a)),
    Feature("inv_o1", "Inverter_Cover_Z", "1.0", "Shaft bleed-through",
            (0.015, 0.015, 0.016, 0.018, 0.020), lambda a, r: _order(1.0, a)),
    Feature("inv_res900", "Inverter_Cover_Z", "900 Hz", "Structural mode 900 Hz (broadband)",
            (0.006, 0.006, 0.008, 0.010, 0.012), lambda a, r: _resonance(900.0, a, 22.0)),
    Feature("inv_pink", "Inverter_Cover_Z", "-", "Pink noise floor",
            (0.008, 0.010, 0.016, 0.024, 0.030), lambda a, r: _pink(a)),

    # -- HSG_1m (microphone, Pa) ----------------------------------------
    Feature("hmic_o1", "HSG_1m", "1.0", "Rotor unbalance, airborne",
            (0.20, 0.40, 0.62, 1.00, 1.60), lambda a, r: _unbalance(a, r)),
    Feature("hmic_o2", "HSG_1m", "2.0", "Misalignment, airborne",
            (0.05, 0.11, 0.17, 0.26, 0.40), lambda a, r: _order(2.0, a)),
    Feature("hmic_mesh", "HSG_1m", "21.0", "Gear mesh whine + 4 kHz resonance",
            (0.10, 0.10, 0.17, 0.24, 0.30),
            lambda a, r: _order(21.0, a, res_freq=4000.0, res_amp=10.0)),
    Feature("hmic_res400", "HSG_1m", "400 Hz", "Structural mode 400 Hz (broadband)",
            (0.15, 0.15, 0.20, 0.25, 0.30), lambda a, r: _resonance(400.0, a, 16.0)),
    Feature("hmic_res900", "HSG_1m", "900 Hz", "Structural mode 900 Hz (broadband)",
            (0.12, 0.12, 0.16, 0.20, 0.24), lambda a, r: _resonance(900.0, a, 20.0)),
    Feature("hmic_pink", "HSG_1m", "-", "Pink noise floor",
            (0.05, 0.07, 0.11, 0.16, 0.20), lambda a, r: _pink(a)),

    # -- Inverter_Cover_1m (microphone, Pa) --------------------------
    Feature("imic_sw", "Inverter_Cover_1m", "8000 Hz", "Inverter switching tone, airborne (fixed)",
            (0.15, 0.15, 0.15, 0.16, 0.18), lambda a, r: _sine(8000.0, a)),
    Feature("imic_o1", "Inverter_Cover_1m", "1.0", "Rotor unbalance, airborne",
            (0.10, 0.18, 0.27, 0.42, 0.62), lambda a, r: _order(1.0, a)),
    Feature("imic_res900", "Inverter_Cover_1m", "900 Hz", "Structural mode 900 Hz (broadband)",
            (0.10, 0.10, 0.14, 0.18, 0.22), lambda a, r: _resonance(900.0, a, 22.0)),
    Feature("imic_pink", "Inverter_Cover_1m", "-", "Pink noise floor",
            (0.04, 0.06, 0.10, 0.14, 0.16), lambda a, r: _pink(a)),

    # -- Motor_Front_1m (microphone, Pa) ----------------------------
    Feature("fmic_o1", "Motor_Front_1m", "1.0", "Rotor unbalance, airborne",
            (0.25, 0.45, 0.70, 1.10, 1.70), lambda a, r: _unbalance(a, r)),
    Feature("fmic_o05", "Motor_Front_1m", "0.5", "Sub-harmonic / oil whirl, airborne",
            (None, None, 0.05, 0.08, 0.12), lambda a, r: _order(0.5, a)),
    Feature("fmic_o3", "Motor_Front_1m", "3.0", "Driveline 3rd, airborne",
            (0.06, 0.06, 0.08, 0.11, 0.15), lambda a, r: _order(3.0, a)),
    Feature("fmic_res400", "Motor_Front_1m", "400 Hz", "Structural mode 400 Hz (broadband)",
            (0.12, 0.12, 0.18, 0.24, 0.28), lambda a, r: _resonance(400.0, a, 16.0)),
    Feature("fmic_pink", "Motor_Front_1m", "-", "Pink noise floor",
            (0.05, 0.07, 0.12, 0.16, 0.20), lambda a, r: _pink(a)),
)


# --- tacho degradation per run ---------------------------------------------
# R0 clean; a loose probe at low speed first, then whole-record jitter, then
# missed pulses on top. "start"/"end" region alternates with setup so a
# coast-down (S2) shows its dropout at the end.

def _tacho_noise(run_idx: int, setup: SetupSpec) -> dict:
    if run_idx == 0:
        return {}
    if run_idx == 1:
        region = "end" if setup.direction == "Ramp Down" else "start"
        return {"std_rpm": 15.0, "region": region, "region_frac": 0.18}
    if run_idx == 2:
        return {"std_rpm": 25.0, "region": "all"}
    if run_idx == 3:
        return {"std_rpm": 30.0, "region": "all", "dropout_rate": 0.00020, "dropout_gain": 0.60}
    return {"std_rpm": 40.0, "region": "all", "dropout_rate": 0.00050, "dropout_gain": 0.50}


TACHO_MAP = (
    "clean",
    "15 rpm jitter on first/last 18% of ramp",
    "25 rpm jitter, whole record",
    "30 rpm jitter + missed pulses (rate 2e-4)",
    "40 rpm jitter + missed pulses (rate 5e-4)",
)


# --- assembled dataset -----------------------------------------------------

@dataclass(frozen=True)
class Measurement:
    rel_path: str
    run_idx: int
    cycles: int
    setup: SetupSpec
    seed: int
    params: dict


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    description: str
    fs: float
    acc_channels: tuple
    mic_channels: tuple
    measurements: tuple
    order_map: tuple = field(default_factory=tuple)
    tacho_map: tuple = field(default_factory=tuple)


def _channels_for_run(run_idx: int) -> list:
    """Build the seven-channel component lists for one run's health state."""
    by_channel = {name: [] for name in ACC_CHANNELS + MIC_CHANNELS}
    for feat in FEATURES:
        amp = feat.amps[run_idx]
        if amp is None:
            continue
        by_channel[feat.channel].append(feat.build(amp, run_idx))

    channels = []
    for name in ACC_CHANNELS:
        channels.append({"name": name, "unit": "g", "components": by_channel[name]})
    for name in MIC_CHANNELS:
        channels.append({"name": name, "unit": "Pa", "components": by_channel[name]})
    return channels


def _build_engine_degradation_v1() -> DatasetSpec:
    measurements = []
    for run_idx, cycles in enumerate(RUN_CYCLES):
        run_dir = f"Run_{run_idx}_{cycles}_cycles"
        channels = _channels_for_run(run_idx)
        for setup_idx, setup in enumerate(SETUPS):
            # Deterministic per (run, setup): the formula lives in versioned code,
            # so the same file regenerates anywhere.
            seed = 100000 + run_idx * 100 + setup_idx
            params = {
                "fs": FS_HZ,
                "duration": setup.duration,
                "rpm_start": setup.rpm_start,
                "rpm_stop": setup.rpm_stop,
                "direction": setup.direction,
                "plateaus_on": setup.plateaus_on,
                "plateaus": setup.plateaus,
                "plateau_ratio": setup.plateau_ratio,
                "seed": seed,
                "channels": channels,
                "tacho_noise": _tacho_noise(run_idx, setup),
            }
            rel_path = f"{run_dir}/R{run_idx}_{setup.key}_{setup.label}.asc"
            measurements.append(Measurement(rel_path, run_idx, cycles, setup, seed, params))

    order_map = tuple(
        {"feature": f.key, "channel": f.channel, "order": f.order,
         "meaning": f.meaning, "amps": f.amps}
        for f in FEATURES
    )

    return DatasetSpec(
        key="engine_degradation_v1",
        description=("Run-to-run degradation study: 5 fixed ramp setups x 5 runs "
                     "(0 - 20000 cycles), worsening mechanical health each run."),
        fs=FS_HZ,
        acc_channels=ACC_CHANNELS,
        mic_channels=MIC_CHANNELS,
        measurements=tuple(measurements),
        order_map=order_map,
        tacho_map=TACHO_MAP,
    )


# --- help_demo_v1: small, spectrogram-rich dataset for the Help figures -------
#
# Two runs (healthy / damaged) x four ramps (slow/fast, up/down), three channels.
# The shaft runs 0..9000 rpm (150 Hz), so orders 3/6/9/12 cross the 400 Hz
# structural mode (7 crosses 800 Hz, 10 crosses 1400 Hz) on the way up, and a linear chirp 500 -> 3000 Hz crosses
# everything. Nyquist is 4096 Hz; the highest order (24) peaks at 3600 Hz.

_HELP_DEMO_FS_HZ = 8192.0
_HELP_DEMO_CHANNELS = (("Motor_HSG", "g"), ("Bearing_HSG", "g"), ("HSG_1m", "Pa"))
_HELP_DEMO_RUNS = ("Healthy", "Damaged")

_HELP_DEMO_SETUPS = (
    SetupSpec("S1", "SlowUp", "Linear sweep", 0.0, 9000.0, "Ramp Up", 20.0),
    SetupSpec("S2", "FastUp", "Fast linear sweep", 0.0, 9000.0, "Ramp Up", 6.0),
    SetupSpec("S3", "SlowDown", "Linear coast-down", 0.0, 9000.0, "Ramp Down", 20.0),
    SetupSpec("S4", "FastDown", "Fast coast-down", 0.0, 9000.0, "Ramp Down", 6.0),
)


def _help_demo_components(run_idx: int) -> dict:
    """Components per channel; run 1 is the damaged motor (index into amps = run)."""
    def pick(healthy, damaged):
        return damaged if run_idx else healthy

    chirp = {"type": "Chirp", "value": 500.0, "amplitude": 0.02,
             "res_freq": 3000.0, "res_amp": 0.0}
    return {
        "Motor_HSG": [
            _order(1.0, pick(0.05, 0.30), amp_end=pick(0.06, 0.40)),
            _order(2.0, pick(0.03, 0.08)),
            _order(3.0, 0.03, res_freq=400.0, res_amp=15.0),
            # order 6 and 9 carry shaft-order sidebands (value +/- mod_order)
            _order(6.0, 0.02, res_freq=400.0, res_amp=15.0,
                   mod_order=1.0, mod_depth=pick(0.2, 0.7)),
            _order(9.0, 0.015, res_freq=400.0, res_amp=15.0,
                   mod_order=2.0, mod_depth=pick(0.0, 0.6)),
            _order(12.0, 0.01, res_freq=400.0, res_amp=15.0),
            _order(7.0, 0.015, res_freq=800.0, res_amp=15.0),
            _order(10.0, 0.012, res_freq=1400.0, res_amp=15.0),
            _resonance(400.0, 0.04, 18.0),
            _resonance(800.0, 0.035, 20.0),
            _resonance(1400.0, 0.03, 22.0),
            chirp,
            _pink(pick(0.01, 0.03)),
        ] + ([_order(0.5, 0.04)] if run_idx else []),
        "Bearing_HSG": [
            _order(24.0, pick(0.02, 0.04)),
            _order(1.0, 0.02),
            _pink(pick(0.012, 0.04)),
        ] + ([_order(3.6, 0.05, mod_order=1.0, mod_depth=0.5)] if run_idx else []),
        "HSG_1m": [
            _order(1.0, pick(0.2, 1.0)),
            _order(2.0, pick(0.05, 0.25)),
            _order(3.0, 0.1, res_freq=400.0, res_amp=15.0),
            _resonance(400.0, 0.15, 16.0),
            _resonance(800.0, 0.10, 20.0),
            _resonance(1400.0, 0.08, 22.0),
            _pink(pick(0.05, 0.15)),
        ],
    }


def _build_help_demo_v1() -> DatasetSpec:
    measurements = []
    for run_idx, run_name in enumerate(_HELP_DEMO_RUNS):
        by_channel = _help_demo_components(run_idx)
        channels = [{"name": n, "unit": u, "components": by_channel[n]}
                    for n, u in _HELP_DEMO_CHANNELS]
        for setup_idx, setup in enumerate(_HELP_DEMO_SETUPS):
            seed = 200000 + run_idx * 100 + setup_idx
            params = {
                "fs": _HELP_DEMO_FS_HZ, "duration": setup.duration,
                "rpm_start": setup.rpm_start, "rpm_stop": setup.rpm_stop,
                "direction": setup.direction, "plateaus_on": False,
                "plateaus": 0, "plateau_ratio": 0.0, "seed": seed,
                "channels": channels,
                "tacho_noise": {"std_rpm": 20.0, "region": "all"} if run_idx else {},
            }
            rel_path = f"{run_name}/{run_name}_{setup.key}_{setup.label}.asc"
            measurements.append(Measurement(rel_path, run_idx, 0, setup, seed, params))

    return DatasetSpec(
        key="help_demo_v1",
        description=("Help demo: healthy and damaged run, slow/fast ramps up and down, "
                     "orders crossing 400/800/1400 Hz resonances, sidebands, plus a 500-3000 Hz chirp."),
        fs=_HELP_DEMO_FS_HZ,
        acc_channels=("Motor_HSG", "Bearing_HSG"),
        mic_channels=("HSG_1m",),
        measurements=tuple(measurements),
    )


_BUILDERS = {
    "engine_degradation_v1": _build_engine_degradation_v1,
    "help_demo_v1": _build_help_demo_v1,
}


def list_datasets() -> list:
    return sorted(_BUILDERS)


def build_dataset(key: str) -> DatasetSpec:
    if key not in _BUILDERS:
        raise KeyError(f"unknown dataset {key!r}; have {list_datasets()}")
    return _BUILDERS[key]()


def realize_measurement(measurement: "Measurement", out_root: str) -> dict:
    """
    Writes one measurement's .asc under `out_root`, creating its Run_* subfolder.
    Returns the summary dict from generate_and_export_synthetic (path, seed,
    samples, nyquist_warnings).

    Pure I/O -- no Qt, safe on a background thread. This is the single write
    path: realize_dataset() loops over it, and the GUI "Realize whole dataset"
    job runs one call per step so it can be counted and cancelled.
    """
    import os

    from io_modules.signal_generation.synthetic_pipeline import generate_and_export_synthetic

    target = os.path.join(out_root, measurement.rel_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return generate_and_export_synthetic(measurement.params, target)


def realize_dataset(key: str, out_root: str,
                    on_measurement: Optional[Callable[[int, Measurement, dict], None]] = None) -> list:
    """
    Writes every measurement of dataset `key` under `out_root`, preserving the
    Run_* subfolder layout. Returns the list of per-file summary dicts from
    generate_and_export_synthetic (path, seed, samples, nyquist_warnings).

    Pure I/O sequencing -- no Qt. `on_measurement(index, measurement, summary)`
    is called after each file so a caller can drive a progress bar.
    """
    spec = build_dataset(key)
    summaries = []
    for idx, m in enumerate(spec.measurements):
        summary = realize_measurement(m, out_root)
        summaries.append(summary)
        if on_measurement is not None:
            on_measurement(idx, m, summary)
    return summaries
