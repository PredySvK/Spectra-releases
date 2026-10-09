"""
The one owner of the spectrogram a single graph holds -- ``GraphCurves``'
counterpart for a dock whose content is one 2D map rather than a curve list.

A ``GraphSpectrogram`` keeps the ``SpectrogramModel`` a dock draws, built from
the canonical block it was given (ADR §1.60). Showing a block and rebuilding it
in other display settings both go through it and end in exactly one
``on_change`` call, so the dock draws what changed and never builds the model
itself.

Settings (colour scale, spectrum format, amplitude mode, dB) arrive as
arguments, for the same reason as in ``GraphCurves``: which settings object
belongs to a dock is a GUI question.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ._graph_curves import _weak_listener
from ._plot_model import SpectrogramModel
from ._plot_model_builder import build_spectrogram_model


class GraphSpectrogram:
    """The spectrogram one graph holds, and every change to it."""

    def __init__(self, on_change: Optional[Callable[[SpectrogramModel], None]] = None) -> None:
        self._on_change = _weak_listener(on_change)
        self._current: Optional[SpectrogramModel] = None

    # ------------------------------------------------------------------ reads

    @property
    def model(self) -> Optional[SpectrogramModel]:
        """The snapshot the dock draws; None until the first block lands."""
        return self._current

    @property
    def block(self) -> Optional[Any]:
        """The canonical block the current model is built from."""
        return self._current.block if self._current is not None else None

    # ----------------------------------------------------------------- writes

    def show_block(
        self,
        block: Any,
        *,
        color_scale: str = "Linear",
        spectrum_format: str = "linear",
        amplitude_mode: str = "rms",
        decibel_scale: Optional[bool] = None,
    ) -> None:
        """Show ``block`` instead of whatever was held."""
        self._replace(build_spectrogram_model(
            block,
            color_scale=color_scale,
            spectrum_format=spectrum_format,
            amplitude_mode=amplitude_mode,
            decibel_scale=decibel_scale,
        ))

    def rebuild_display(
        self,
        *,
        color_scale: str,
        spectrum_format: str,
        amplitude_mode: str,
        decibel_scale: Optional[bool] = None,
    ) -> None:
        """The held block again in other display settings -- no STFT re-run."""
        if self.block is not None:
            self.show_block(
                self.block,
                color_scale=color_scale,
                spectrum_format=spectrum_format,
                amplitude_mode=amplitude_mode,
                decibel_scale=decibel_scale,
            )

    def _replace(self, model: SpectrogramModel) -> None:
        self._current = model
        if self._on_change is not None:
            self._on_change(model)
