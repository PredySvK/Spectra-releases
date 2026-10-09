# =====================================================================
# FILE: signal_processing/dsp/steps/spectrum_scaling.py
# =====================================================================
"""
Step: the scaling table (Format x Amplitude, ACF/ECF correction, PSD, edge
correction) that turns averaged Unscaled power (CONTEXT.md) into canonical
bin energy (P_canon) and canonical bin energy into a displayable spectrum.

The table itself lives in `core/scaling_table.py` (ADR §1.61): `core/`
cannot import `signal_processing/`, but `core/data_block.py` needs the same
formula to compute a display view of a stored block, so the table exists
once in `core/` and both this step and `data_block.py` call it. This module
just re-exports the two functions the recipes (spectrum.py, spectrogram.py)
call, so they import from the DSP steps package rather than reaching into
`core/` directly; the tracked recipes get P_canon from
frame_fft.canonical_power_matrix, which scales inside each FFT batch.
"""

from core.scaling_table import compute_canonical_power, scale_canonical_to_amplitude

__all__ = ["compute_canonical_power", "scale_canonical_to_amplitude"]
