"""
Signal generation facade: engine, presets, pipeline exporter, live preview computation,
and the metadata / channel-pairing spreadsheets of a realized dataset.
"""

from io_modules.signal_generation._dataset_sheets import write_dataset_sheets
from io_modules.signal_generation._preview import (
    PREVIEW_NOISE_SEED,
    compute_preview_arrays,
)
from io_modules.signal_generation.synthetic_pipeline import generate_and_export_synthetic

__all__ = [
    "PREVIEW_NOISE_SEED",
    "compute_preview_arrays",
    "generate_and_export_synthetic",
    "write_dataset_sheets",
]
