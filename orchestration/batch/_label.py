# =====================================================================
# FILE: orchestration/batch/_label.py
# =====================================================================
"""
Default result set labeling for batch workflows (ADR §1.6 phase 7C, §1.21).

When a workflow run or batch is executed without an explicit user-given label,
a default folder name is derived from the terminal node's parameters and the
channels in the measurement selection.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Optional

from core.block_kinds import KIND_ORDER_CUT
from core.filter_card_config import COLUMN_CHANNEL, COLUMN_DIRECTION
from core.measurement_selection import MeasurementSelection
from core.workflow_graph import Workflow
from io_modules.result_cache.cache_naming import (
    build_channel_component,
    build_kind_result_set_label,
    build_result_set_label,
)
from signal_processing.workflow import sole_terminal_node, spec_for
from selection.source_facets import EMPTY_FACET_VALUE


def default_result_set_label(workflow: Workflow, selection: MeasurementSelection,
                             total_available_bases: Optional[int] = None) -> str:
    """
    What to call the result set when the caller did not name the run.

    A result set is a folder on disk, so the name is what the user navigates by
    -- "Spectrogram_2048_All_Channels" rather than the workflow's working title.
    Order cuts keep the spelling they have always had (§1.21).

    `total_available_bases` is how many distinct sensors the batch could have
    drawn from, which is what decides "All_Channels" against "5_Channels". A
    caller that knows it -- Calculate & Save Data has just counted them in the
    loaded folder -- passes it, so ticking every sensor by hand in "Selected
    Channels" mode gets the same name as picking "All Channels". A caller that
    does not reads the selection's Channel column constraint or explicit pairs.
    """
    node = sole_terminal_node(workflow)
    kind = spec_for(node.block_type).produces

    bases = selection.column_values.get(COLUMN_CHANNEL)
    directions = selection.column_values.get(COLUMN_DIRECTION, ())
    base_directions = {
        base: [None if direction == EMPTY_FACET_VALUE else direction for direction in directions]
        for base in bases or ()
    }
    if selection.channel_identities is not None:
        base_directions = {}
        for base, direction in selection.channel_identities:
            base_directions.setdefault(base, []).append(direction)
        bases = tuple(base_directions)
    channel_component = (
        "All_Channels" if bases is None else
        build_channel_component(base_directions, total_available_bases or 0)
    )
    if kind == KIND_ORDER_CUT:
        return build_result_set_label(
            node.params.get("orders_to_extract") or [], base_directions,
            total_available_bases or 0, channel_component=channel_component,
        )
    return build_kind_result_set_label(kind, node.params, channel_component)
