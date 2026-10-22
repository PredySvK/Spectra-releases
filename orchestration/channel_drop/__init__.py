"""
Channel-drop orchestration: route drop descriptors using dock facts as data.

This component decides which processing path a drop belongs to, removes
duplicate channels, resolves drop descriptors against the Data Pool (and
back) and the FFT settings of a Spectrum drop, and runs the drop: the order of
its lanes, the claim-run-release skeleton, the landing of every result (its
cache-hit lines, draw and keep, and the pairing of a spectrogram's channels)
and the error policy (``run_channel_drop``).
What it needs from the place the drop lands comes across one seam,
``DropTarget``; it never sees a Qt dock, an application context, a file or a
thread.

What does not belong here: dock type checks and UI effects (``gui/``), raw
channel I/O (``io_modules/``), or DSP calculations (``signal_processing/``).
"""

from orchestration.channel_drop._routing import (
    DropFacts,
    classify_drop_descriptors,
    drop_key,
    drop_keys,
    filter_duplicate_descriptors,
)
from orchestration.channel_drop._drop_plan import plan_channel_drop
from orchestration.channel_drop._drop_execution import run_channel_drop
from orchestration.channel_drop._drop_target import (
    DropTarget,
    OrderDropInputs,
    OverallLevelDropInputs,
    SpectrogramDropInputs,
    SpectrumDropInputs,
)
from orchestration.channel_drop._spectrum_drop_config import resolve_spectrum_drop_config
from orchestration.channel_drop._pending_drops import PendingDrops
from orchestration.channel_drop._dropped_channels import (
    build_channel_descriptors,
    resolve_dropped_channel,
    resolve_dropped_channels,
)
from orchestration.channel_drop._plotted_keys import read_plotted_keys
from orchestration.channel_drop._tacho_plan import plan_tacho_per_file
from orchestration.channel_drop._spectrogram_routing import decide_spectrogram_drop
from orchestration.channel_drop._result_content_routing import (
    ResultContentMemoKey,
    plan_result_content_drop,
    result_content_memo_key,
)

__all__ = [
    "plan_channel_drop",
    "run_channel_drop",
    "DropTarget",
    "OrderDropInputs",
    "OverallLevelDropInputs",
    "SpectrogramDropInputs",
    "SpectrumDropInputs",
    "resolve_spectrum_drop_config",
    "DropFacts",
    "classify_drop_descriptors",
    "drop_key",
    "drop_keys",
    "filter_duplicate_descriptors",
    "PendingDrops",
    "resolve_dropped_channel",
    "resolve_dropped_channels",
    "build_channel_descriptors",
    "read_plotted_keys",
    "plan_tacho_per_file",
    "decide_spectrogram_drop",
    "ResultContentMemoKey",
    "plan_result_content_drop",
    "result_content_memo_key",
]
