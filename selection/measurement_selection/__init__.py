# =====================================================================
# FILE: selection/measurement_selection/__init__.py
# =====================================================================
"""
Measurement selection and save-spec filtering for the selection floor.

Selection floor: which subset of curves or measurements is relevant?
Measurement selection turns a named query or explicit selection into concrete
measurements and channels for batch workflows, determines the channel scope
from loaded runs, and enforces SaveSpec filters on save nodes.

What does not belong here: running the background batch job (orchestration/ or
gui/workspace/), reading raw measurement files from disk (io_modules/), or Qt
widgets and dialogs (gui/).
"""
from core.models import ChannelIdentity
from ._column_values import (
    SELECTION_EXCLUDED_COLUMNS,
    CheckedColumnValues,
    build_checks_from_selection,
    build_column_values,
    build_selection_from_checks,
    resolve_checked_column_values,
    resolve_selection_facets,
)
from selection.measurement_selection._measurement_selection import (
    SaveSourceResolution,
    SelectionResolution,
    WHOLE_POOL_SELECTION_NAME,
    build_channel_drop_descriptors,
    channel_identities_by_type,
    resolve,
    resolve_run_channel_type,
    resolve_save_sources,
    save_spec_allows_channel,
    select_channels_for_run,
    whole_pool_selection,
)

__all__ = [
    "SELECTION_EXCLUDED_COLUMNS",
    "CheckedColumnValues",
    "build_checks_from_selection",
    "build_column_values",
    "build_selection_from_checks",
    "resolve_checked_column_values",
    "resolve_selection_facets",
    "ChannelIdentity",
    "SaveSourceResolution",
    "SelectionResolution",
    "WHOLE_POOL_SELECTION_NAME",
    "build_channel_drop_descriptors",
    "channel_identities_by_type",
    "resolve",
    "resolve_run_channel_type",
    "resolve_save_sources",
    "save_spec_allows_channel",
    "select_channels_for_run",
    "whole_pool_selection",
]
