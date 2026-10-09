"""The spreadsheets written next to a realized dataset: metadata.xlsx and channel_pairing.xlsx."""

import os

from io_modules.signal_generation.signal_library import DatasetSpec


def _run_date(run_idx: int) -> str:
    # Arbitrary, stable; one run per calendar day from 2026-03-02. Built as text because
    # this package may not import datetime (test_architecture: no wall clock in the maths).
    # ponytail: valid while a dataset has fewer than 30 runs
    return f"2026-03-{2 + run_idx:02d}"


# measured -> simulated pairs written next to a dataset that ships a pairing sheet
_PAIRS = {"help_demo_v1": [("Motor_HSG", "Bearing_HSG")]}


def _dwell_s(setup):
    if not setup.plateaus_on or setup.plateaus < 1:
        return None
    return round(setup.duration * setup.plateau_ratio / setup.plateaus, 1)


def _write_metadata_xlsx(spec: DatasetSpec, path: str) -> str:
    import openpyxl

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Measurements"
    # help_demo_v1 ships no order map; its run folder (Healthy/Damaged) becomes a Condition column
    demo = spec.key == "help_demo_v1"
    ws.append(["Date", "Test no.", "File Name", "Recorder", "Setup", "Spin cycle",
               "Ramp type", "Speed start [rpm]", "Speed stop [rpm]", "Ramp time [s]",
               "Steps", "Dwell [s]", "Max speed [rpm]", "Seed", "Comment"]
              + (["Condition"] if demo else []))
    for i, m in enumerate(spec.measurements, start=1):
        s_start, s_stop, s_max = m.setup.physical_speeds()
        comment = ""
        if m.setup.direction == "Ramp Up & Down":
            comment = f"peak {int(m.setup.rpm_stop)} rpm then back down"
        ws.append([
            _run_date(m.run_idx),
            i,
            os.path.splitext(os.path.basename(m.rel_path))[0],
            "SynthGen",
            m.setup.label,
            m.cycles,
            m.setup.ramp_type,
            int(s_start), int(s_stop), m.setup.duration,
            m.setup.plateaus if m.setup.plateaus_on else None,
            _dwell_s(m.setup),
            int(s_max),
            m.seed,
            comment,
        ] + ([os.path.dirname(m.rel_path)] if demo else []))

    if not demo:
        om = wb.create_sheet("Order Map")
        om.append(["Feature", "Channel", "Order", "Meaning", "R0", "R1", "R2", "R3", "R4"])
        for row in spec.order_map:
            cells = ["-" if a is None else a for a in row["amps"]]
            om.append([row["feature"], row["channel"], row["order"], row["meaning"], *cells])
        om.append([])
        om.append(["TACHO", "Tacho_Master", "-", "Tacho channel degradation", *spec.tacho_map])

    wb.save(path)
    return path


def write_dataset_sheets(spec: DatasetSpec, out_root: str) -> list:
    """Writes ``metadata.xlsx`` (and ``channel_pairing.xlsx`` where the dataset has pairs) under ``out_root``."""
    from io_modules.channel_pairing import write_channel_pairing

    os.makedirs(out_root, exist_ok=True)
    written = [_write_metadata_xlsx(spec, os.path.join(out_root, "metadata.xlsx"))]
    if spec.key in _PAIRS:
        pairing = os.path.join(out_root, "channel_pairing.xlsx")
        write_channel_pairing(pairing, [((a, None), (b, None)) for a, b in _PAIRS[spec.key]])
        written.append(pairing)
    return written
