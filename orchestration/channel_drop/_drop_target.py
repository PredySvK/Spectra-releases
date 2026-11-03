"""The seam of a channel drop: what the GUI lends one drop run (Qt-free)."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

from core.dsp_configs import OrderTrackingConfig, OverallLevelConfig, SpectrumConfig
from selection.parameter_sets import ParameterSet

from orchestration.channel_drop._routing import DropFacts


@dataclass(frozen=True)
class SpectrumDropInputs:
    """What a Spectrum drop's config is resolved from, taken on the GUI thread
    (``resolve_spectrum_drop_config``)."""

    config: SpectrumConfig
    config_from_trace: bool
    base_compute_spec: Mapping[str, Any] | None
    base_spectrum_format: str = ""
    base_amplitude_mode: str = ""


@dataclass(frozen=True)
class SpectrogramDropInputs:
    """What a channel dropped on a spectrogram is paired against, taken on
    the GUI thread when it lands (``decide_spectrogram_drop``).

    ``restored_measurement_path`` is the file of a spectrogram restored from
    the Tab cache, which shows its image without the raw channels it was
    computed from; None for any other. ``run_lookup`` is ``DataPool.run_lookup``.
    """

    vib_block: Any
    tacho_block: Any
    tracking_mode: str
    restored_measurement_path: str | None
    run_lookup: Callable[[str], Any]


@dataclass(frozen=True)
class OrderDropInputs:
    """What an order-cut drop reads from the shell, taken on the GUI thread."""

    config: OrderTrackingConfig
    run_lookup: Callable[[str], Any]
    dock_tacho: Any
    with_overall_level: bool


@dataclass(frozen=True)
class OverallLevelDropInputs:
    """What an Overall Level drop reads from the shell, taken on the GUI thread."""

    config: OverallLevelConfig
    run_lookup: Callable[[str], Any]
    dock_tacho: Any


class DropTarget(Protocol):
    """What ``run_channel_drop`` needs from the place a drop lands.

    The GUI implements it over one dock; a test implements it with a fake.
    Everything the run reads about the dock or the shell is a method here,
    so nothing in the run probes attributes it cannot see. The ``draw_*``
    methods only draw; what is logged around a draw and what is kept is the
    run's.
    """

    facts: DropFacts

    def log(self, message: str) -> None: ...

    def run_task(self, worker: Callable, *args, on_success: Callable, on_error: Callable,
                 **run_kwargs) -> None: ...

    def open_imported_channels(self, descriptors: Iterable[dict]) -> None: ...

    def spectrum_inputs(self) -> SpectrumDropInputs: ...

    def restored_config(self, recipe: Mapping[str, Any]) -> Any:
        """The ``live_compute.RestoreConfig`` restored overlays saved with
        ``recipe`` compute with: the recipe laid over the ribbon's config of
        this dock's kind -- never the "new curve takes the trace's settings"
        choice."""

    def drop_restore(self, resolved: Any) -> Any:
        """What one drop task of restored overlays hands its worker
        (``live_compute.DropRestore``): where their Tab cache files are and
        ``resolved`` (None without a recipe), said once per channel that is
        computed after all."""

    def cache_finder(self) -> Callable | None:
        """The worker-thread result-set lookup (`ProjectSession.cache_finder`),
        None when the cache is switched off."""

    def order_inputs(self) -> OrderDropInputs: ...

    def overall_level_inputs(self) -> OverallLevelDropInputs: ...

    def parameter_sets(self) -> list[ParameterSet]:
        """The dock's Parameter Sets, its result sets still queued included:
        the channels re-dropped after a Refresh or a reopen arrive before their
        dock's sets land (#427)."""

    def drawing(self) -> AbstractContextManager:
        """Everything drawn inside lands on the dock as one draw (#440)."""

    def draw_time_curve(self, descriptor: dict, block) -> None: ...

    def draw_spectrum_curve(self, descriptor: dict, block) -> None: ...

    def draw_order_curves(self, descriptor: dict, channel_name: str, blocks) -> None:
        """The order cuts of one channel -- and its Overall Level and Residual,
        which carry no order number -- each as a curve."""

    def draw_overall_level_curve(self, block) -> None: ...

    def plot_model(self) -> Any:
        """The dock's ``PlotModel`` as drawn so far, None while it holds no curve."""

    def keep(self, descriptor: dict, result) -> None:
        """Keep the drawn ``result`` of ``descriptor`` in the dock's Tab cache
       ."""

    def spectrogram_inputs(self) -> SpectrogramDropInputs: ...

    def hold_spectrogram_channels(self, vib_block, tacho_block, dropped) -> None:
        """Hold the vib/tacho pair; ``dropped`` is the pooled ``(run_index,
        channel_meta)`` of a dropped vibration channel -- what Refresh, the
        cache lookup and the saved tab read the channel from -- None for a tacho."""

    def run_spectrogram_compute(self) -> None:
        """Compute the held pair as the dock's own compute; the tab title follows."""

    def refresh_title(self) -> None: ...
