"""The Curve metadata record of a batch of traces."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from core.filter_card_config import (
    COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_CHANNEL_TYPE,
    COLUMN_DATA_POOL_LABEL, COLUMN_DIRECTION, COLUMN_FILE_NAME,
    COLUMN_ORDER, COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
)
from selection.parameter_sets import parameter_set_for_signature, parameter_sets_from_traces
from selection.source_facets import curve_field_value
from view_models.plot import Trace
from view_models.trace_filter import identity_for_trace

RESULT_SET_LIVE = "Live"


def build_curve_metadata(
    traces: Sequence[Trace],
    sources_by_path: Dict[str, Any],
    result_set_labels: Dict[str, str],
    schema: Mapping[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One record per trace, in the order of `traces`: ``{column key: typed value}``.

    Keys are the Filter card column keys (built-ins and every schema field,
    whether or not the field is offered as a filter). A column the curve has no
    value for is absent -- a channel field its own channel lacks is never
    another channel's. Result set reads "Live" for a curve of no result set.
    """
    identities = [identity_for_trace(trace, sources_by_path, result_set_labels) for trace in traces]
    parameter_sets = tuple(parameter_sets_from_traces(identities))

    records: List[Dict[str, Any]] = []
    for trace, identity in zip(traces, identities):
        record: Dict[str, Any] = {COLUMN_RESULT_SET: identity.result_set_label or RESULT_SET_LIVE}
        parameter_set = parameter_set_for_signature(identity.parameter_signature, parameter_sets)
        builtins = {
            COLUMN_CHANNEL: identity.channel_identity[0] or trace.channel_name,
            COLUMN_DIRECTION: identity.direction,
            COLUMN_CHANNEL_TYPE: identity.channel_type,
            COLUMN_FILE_NAME: identity.file_name or trace.file_name,
            COLUMN_DATA_POOL_LABEL: identity.data_pool_label,
            COLUMN_ANALYSIS_TYPE: identity.result_kind,
            COLUMN_ORDER: identity.order,
            COLUMN_PARAMETER_SET: parameter_set.label if parameter_set is not None else None,
        }
        record.update({key: value for key, value in builtins.items() if value not in (None, "")})

        if identity.source is not None:
            for key in schema:
                value = curve_field_value(
                    identity.source, schema, key, identity.channel_identity, identity.channel_index)
                if value not in (None, ""):
                    record[key] = value
        records.append(record)
    return records
