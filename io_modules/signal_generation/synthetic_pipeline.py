# =====================================================================
# FILE: io_modules/signal_generation/synthetic_pipeline.py
# =====================================================================
"""
One pure entry point that turns a Signal Generator parameter dict into a
finished Siemens ASC file on disk: build the master tacho/phase vectors,
synthesize every channel's vibration, write the file.

Lives in io_modules/ because the last step is disk I/O. It only sequences
signal_generation_engine (math) and asc_exporter (write) -- both already
here -- so the GUI action and its background controller share exactly one
generate-and-export path instead of each spelling out the same five calls.

No Qt, no AppContext: safe to run whole on a background worker thread.
All internal documentation strings and variable labels are written in English.
"""

import numpy as np

from io_modules.signal_generation.asc_exporter import export_synthetic_asc
from io_modules.signal_generation.signal_generation_engine import (
    apply_tacho_noise,
    compose_vibration_signal,
    generate_rpm_profile,
    generate_tacho_pulse,
    generate_time_vector,
)

_PULSES_PER_REV = 1


def _nyquist_warnings(params: dict) -> list:
    """Warn once for each Order or Sine component that can alias above fs/2."""
    nyquist_hz = params["fs"] / 2.0
    top_rpm = max(params["rpm_start"], params["rpm_stop"])
    warnings = []
    for channel in params["channels"]:
        for comp in channel["components"]:
            component_type = comp.get("type")
            value = comp.get("value", 0.0)
            mod_order = comp.get("mod_order", 0.0)
            modulated = mod_order > 0 and comp.get("mod_depth", 0.0) > 0
            sideband = mod_order if modulated else 0.0

            if component_type == "Order" and value > 0:
                f_top = (value + sideband) * top_rpm / 60.0
                label = f"order {value:g}"
            elif component_type == "Sine signal" and value > 0:
                f_top = value + sideband
                label = f"sine {value:g} Hz"
            else:
                continue

            if f_top > nyquist_hz:
                if modulated:
                    label += f" with modulation sideband +{mod_order:g}"
                warnings.append(
                    f"{channel['name']}: {label} reaches {f_top:.0f} Hz > "
                    f"Nyquist {nyquist_hz:.0f} Hz (will alias)"
                )
    return warnings


def generate_and_export_synthetic(params: dict, export_path: str) -> dict:
    """
    Generates the full multi-channel record described by `params` and writes
    it to `export_path` as a Siemens Testlab ASC file.

    `params` is gui.dialogs.signal_generator_dialog.SignalGeneratorDialog's
    get_generation_parameters() output. Returns a small summary dict for the
    caller to log -- the arrays themselves stay inside this function, there is
    nothing on screen that wants them.

    `params["seed"]` is optional. When absent one is drawn and returned in the
    summary, so the log always records what would be needed to reproduce the
    file byte for byte; a White Noise component would otherwise make every
    generation unrepeatable.

    `params["tacho_noise"]` is optional. When present its keys are passed to
    apply_tacho_noise, degrading only the tacho *channel* written to disk -- the
    vibration is always synthesized from the clean profile. The returned summary
    carries `nyquist_warnings` for any Order whose top frequency crosses fs/2.
    """
    fs = params["fs"]
    duration = params["duration"]
    dt = 1.0 / fs

    seed = params.get("seed")
    if seed is None:
        # SeedSequence, not np.random.randint: a fresh entropy draw that does
        # not depend on -- or disturb -- the global numpy random state.
        seed = int(np.random.SeedSequence().entropy) % (2 ** 31)
    seed = int(seed)
    rng = np.random.default_rng(seed)

    t_master = generate_time_vector(duration, fs)
    rpm_master = generate_rpm_profile(
        t_master, params["rpm_start"], params["rpm_stop"], params["direction"],
        params["plateaus_on"], params["plateaus"], params["plateau_ratio"],
    )
    phase_master, _ = generate_tacho_pulse(rpm_master, dt, _PULSES_PER_REV)

    vib_data_list, vib_names_list, vib_units_list = [], [], []
    for channel in params["channels"]:
        vib_data_list.append(
            compose_vibration_signal(
                t_master, phase_master, channel["components"], rpm_master, rng=rng
            )
        )
        vib_names_list.append(channel["name"])
        vib_units_list.append(channel["unit"])

    # The vibration above used the clean profile; the tacho *channel* on disk is
    # what the instrument would have recorded -- optionally degraded.
    tacho_cfg = params.get("tacho_noise") or {}
    tacho_channel = apply_tacho_noise(rpm_master, rng, **tacho_cfg) if tacho_cfg else rpm_master

    written_path = export_synthetic_asc(
        export_path=export_path,
        tacho_data=tacho_channel,
        vib_data_list=vib_data_list,
        dt=dt,
        tacho_name="Tacho_Master",
        vib_names=vib_names_list,
        vib_units=vib_units_list,
    )

    return {
        "channels": len(vib_data_list),
        "samples": int(len(t_master)),
        "path": written_path,
        "seed": seed,
        "nyquist_warnings": _nyquist_warnings(params),
    }
