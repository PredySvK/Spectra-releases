# =====================================================================
# FILE: io_modules/signal_generation/asc_exporter.py
# =====================================================================
"""
High-speed ASCII signal exporter compliant with Siemens Simcenter Testlab.
Implements the rigid BEGIN/END block header structure with metadata arrays.
Exports continuous time-domain arrays utilizing standard NumPy serialization.
Supports multiple dynamic vibration channels and customizable physical units.
All internal documentation strings and variable labels are standardly written in English.
"""

import numpy as np
from typing import List, Optional

from io_modules.atomic_write import write_text_atomic

# The ASC header serialises channel names as str(list) and reader_asc splits them
# on "," inside the first "[...]". The format has no escaping, so a name carrying
# any of these would shift every following name and unit off its column -- one
# channel then reads a neighbour's data under its own name (audit 02, S11/11.2).
# frozenset, not set: this is a constant, and a mutable container at module level
# is the module-level mutable state the project forbids.
_HEADER_UNSAFE_CHARS = frozenset(",[]'")


def _reject_header_unsafe_names(names: List[str]) -> None:
    for name in names:
        bad = sorted(set(str(name)) & _HEADER_UNSAFE_CHARS)
        if bad:
            raise ValueError(
                f"channel name {name!r} contains {''.join(bad)!r}: the Siemens ASC "
                f"header cannot carry these characters (they are used as list "
                f"delimiters and have no escaping). Rename the channel."
            )


def export_synthetic_asc(export_path: str, tacho_data: np.ndarray, vib_data_list: List[np.ndarray],
                         dt: float, tacho_name: str = "Tacho_Master", vib_names: List[str] = None,
                         vib_units: Optional[List[str]] = None) -> str:
    """
    Serializes continuous NVH arrays into a strict Siemens Testlab compliant .asc file.
    Stacks an arbitrary number of vibration channels horizontally and returns the
    path actually written. A dot in the requested filename is part of its name;
    only a trailing .asc suffix is treated as an extension.
    """
    num_channels = len(vib_data_list)
    if vib_names is None or len(vib_names) != num_channels:
        vib_names = [f"Channel_{i + 1}" for i in range(num_channels)]

    if vib_units is None or len(vib_units) != num_channels:
        vib_units = ["g"] * num_channels

    _reject_header_unsafe_names([tacho_name, *vib_names])

    asc_final_path = (
        export_path if export_path.lower().endswith(".asc") else f"{export_path}.asc"
    )

    tacho_vector = np.asarray(tacho_data, dtype=np.float64).flatten()
    num_samples = len(tacho_vector)
    time_vector = (np.arange(num_samples) * float(dt)).astype(np.float64)

    clean_vib_vectors = [np.asarray(v, dtype=np.float64).flatten() for v in vib_data_list]

    columns = [time_vector, tacho_vector] + clean_vib_vectors
    data_matrix = np.column_stack(columns)

    # --- SIEMENS ASC HEADER CONSTRUCTION ---
    channel_names_list = ['Time', tacho_name] + vib_names
    units_list = ['s', 'rpm'] + vib_units

    # DELTA needs twelve decimals, not eight. At 25.6 kHz the step is
    # 0.0000390625 s, which "%.8f" truncates to 0.00003906 -- enough to shift the
    # recovered sample rate to 25600.6 Hz and skew every frequency derived from
    # the file. Twelve decimals represent every power-of-two rate up to 102.4 kHz
    # exactly. Fixed point is kept deliberately: it is the most portable thing to
    # hand to a third-party importer.
    header_lines = [
        "BEGIN",
        "START = 0.0",
        f"DELTA = {dt:.12f}",
        f"CHANNELNAME = {str(channel_names_list)}",
        f"UNIT = {str(units_list)}",
        "END"
    ]

    full_header_string = "\n".join(header_lines)

    # The time column carries an absolute value that grows through the record, so
    # it needs more significant digits than the samples do to keep a steady step.
    column_formats = ["%.9e"] + ["%.6e"] * (data_matrix.shape[1] - 1)

    def write_asc(handle):
        np.savetxt(
            fname=handle,
            X=data_matrix,
            fmt=column_formats,
            delimiter=", ",
            header=full_header_string,
            comments=""
        )

    write_text_atomic(asc_final_path, write_asc, encoding="utf-8")

    print(f"SIEMENS_ASC_EXPORT_SUCCESS: Multi-channel grid written to {asc_final_path}")
    return asc_final_path





