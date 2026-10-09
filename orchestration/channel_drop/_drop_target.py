"""The seam of a channel drop: what the GUI lends one drop run (Qt-free)."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

from core.dsp_configs import OrderTrackingConfig, OverallLevelConfig

from orchestration.channel_drop._routing import DropFacts


@dataclass(frozen=True)
class OrderDropInputs:
    """What an order-cut drop reads from the shell, taken on the GUI thread."""

    config: OrderTrackingConfig
    use_cache: bool
    project_session: Any
    runs_by_path: Mapping[str, Any]
    dock_tacho: Any
    with_overall_level: bool


@dataclass(frozen=True)
class OverallLevelDropInputs:
    """What an Overall Level drop reads from the shell, taken on the GUI thread."""

    config: OverallLevelConfig
    use_cache: bool
    finder: Callable | None
    runs_by_path: Mapping[str, Any]
    dock_tacho: Any


class DropTarget(Protocol):
    """What ``run_channel_drop`` needs from the place a drop lands.

    The GUI implements it over one dock; a test implements it with a fake.
    Everything the run reads about the dock or the shell is a method here,
    so nothing in the run probes attributes it cannot see.
    """

    facts: DropFacts

    def resolve_metadata(self, descriptor: Mapping) -> Any: ...

    def log(self, message: str) -> None: ...

    def run_task(self, worker: Callable, *args, on_success: Callable, on_error: Callable,
                 **run_kwargs) -> None: ...

    def open_imported_channels(self, descriptors: Iterable[dict]) -> None: ...

    def result_content_batch(self, label: str) -> AbstractContextManager: ...

    def serve_result_content(self, descriptor: dict) -> bool: ...

    def spectrum_config(self) -> Any: ...

    def order_inputs(self) -> OrderDropInputs: ...

    def overall_level_inputs(self) -> OverallLevelDropInputs: ...

    def render_simple(self, rendered, *, is_spec: bool) -> None: ...

    def render_orders(self, rendered) -> None: ...

    def render_overall_level(self, rendered) -> None: ...

    def refresh_title(self) -> None: ...
