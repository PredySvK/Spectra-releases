"""
Signal generation facade: the predefined-dataset library (list, build, realize),
the params -> file exporter and the bare ASC writer under it, the live preview
computation, and the metadata / channel-pairing spreadsheets of a realized dataset.
"""

from io_modules.signal_generation._asc_exporter import export_synthetic_asc
from io_modules.signal_generation._dataset_sheets import write_dataset_sheets
from io_modules.signal_generation._preview import (
    PREVIEW_NOISE_SEED,
    compute_preview_arrays,
    compute_preview_start_rpm,
)
from io_modules.signal_generation._signal_library import (
    build_dataset,
    list_datasets,
    realize_dataset,
    realize_measurement,
)
from io_modules.signal_generation._synthetic_pipeline import generate_and_export_synthetic

__all__ = [
    "PREVIEW_NOISE_SEED",
    "build_dataset",
    "compute_preview_arrays",
    "compute_preview_start_rpm",
    "export_synthetic_asc",
    "generate_and_export_synthetic",
    "list_datasets",
    "realize_dataset",
    "realize_measurement",
    "write_dataset_sheets",
]
