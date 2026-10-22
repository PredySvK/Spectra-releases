"""The curve's own metadata for the Cursor Box."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.filter_card_config import COLUMN_ANALYSIS_TYPE, COLUMN_PARAMETER_SET
from selection.field_offer import resolve_field_label
from selection.trace_filter import format_result_kind
from view_models.curve_metadata import build_curve_metadata
from view_models.display_prefix import resolve_number_format
from view_models.plot import Trace


def read_curve_metadata(
    trace: Trace, keys: Iterable[str], schema: Mapping[str, Dict[str, Any]],
    sources_by_path: Dict[str, Any], result_set_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Tuple[str, str]]:
    """``{key: (label, text)}`` for every key of `keys` the curve can answer.

    Keys are Configure Filters column keys (built-ins and schema fields); a key
    the curve or the open project has no value for is simply absent, never "N/A".
    Parameter set is not offered. Values come from the Curve metadata record
   ; this only formats them: numbers in the box's Auto format,
    dates as stored ISO text, Analysis type through its result-kind label.
    """
    (record,) = build_curve_metadata([trace], sources_by_path, result_set_labels or {}, schema)
    found: Dict[str, Tuple[str, str]] = {}
    for key in keys:
        value = record.get(key)
        if value is None or key == COLUMN_PARAMETER_SET:
            continue
        if key == COLUMN_ANALYSIS_TYPE:
            text = format_result_kind(value)
        elif isinstance(value, float):
            text = resolve_number_format("", None).format(value)
        else:
            text = str(value)
        if text:
            found[key] = (resolve_field_label(key, schema), text)
    return found
