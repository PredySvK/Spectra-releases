"""
Channel-drop orchestration: route drop descriptors using dock facts as data.

This component decides which processing path a drop belongs to, removes
duplicate channels, and runs the drop: the order of its lanes, the claim-run-release
skeleton and the error policy (``run_channel_drop``). What it needs from the place
the drop lands comes across one seam, ``DropTarget``; it never sees a Qt dock, an
application context, a file or a thread.

What does not belong here: dock type checks and UI effects (``gui/``), raw
channel I/O (``io_modules/``), or DSP calculations (``signal_processing/``).
"""

from orchestration.channel_drop._routing import (
    DropFacts,
    DropRouting,
    classify_drop_descriptors,
    drop_key,
    drop_keys,
    filter_duplicate_descriptors,
)
from orchestration.channel_drop._drop_plan import ChannelDropPlan, OrderGroup, plan_channel_drop
from orchestration.channel_drop._drop_execution import run_channel_drop
from orchestration.channel_drop._drop_target import (
    DropTarget,
    OrderDropInputs,
    OverallLevelDropInputs,
)
from orchestration.channel_drop._pending_drops import PendingDrops
from orchestration.channel_drop._plotted_keys import read_plotted_keys
from orchestration.channel_drop._tacho_plan import (
    TachoDropPlan,
    TachoRefusal,
    plan_tacho_per_file,
)
from orchestration.channel_drop._spectrogram_routing import (
    SpectrogramDropAction,
    SpectrogramDropDecision,
    decide_spectrogram_drop,
)
from orchestration.channel_drop._result_content_routing import (
    ResultContentDropPlan,
    ResultContentMemoKey,
    plan_result_content_drop,
    result_content_memo_key,
)

__all__ = [
    "ChannelDropPlan",
    "OrderGroup",
    "plan_channel_drop",
    "run_channel_drop",
    "DropTarget",
    "OrderDropInputs",
    "OverallLevelDropInputs",
    "DropFacts",
    "DropRouting",
    "classify_drop_descriptors",
    "drop_key",
    "drop_keys",
    "filter_duplicate_descriptors",
    "PendingDrops",
    "read_plotted_keys",
    "TachoDropPlan",
    "TachoRefusal",
    "plan_tacho_per_file",
    "SpectrogramDropAction",
    "SpectrogramDropDecision",
    "decide_spectrogram_drop",
    "ResultContentDropPlan",
    "ResultContentMemoKey",
    "plan_result_content_drop",
    "result_content_memo_key",
]
