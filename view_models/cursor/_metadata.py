"""The curve's own metadata for the Cursor Box."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.filter_card_config import COLUMN_PARAMETER_SET
from selection.field_offer import resolve_field_label
from view_models.curve_metadata import build_curve_metadata
from view_models.plot import Trace, format_curve_metadata_value


def read_curve_metadata(
    trace: Trace, keys: Iterable[str], schema: Mapping[str, Dict[str, Any]],
    sources_by_path: Dict[str, Any], result_set_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Tuple[str, str]]:
    """``{key: (label, text)}`` for every key of `keys` the curve can answer.

    Keys are Configure Filters column keys (built-ins and schema fields); a key
    the curve or the open project has no value for is simply absent, never "N/A".
    Parameter set is not offered. Values come from the Curve metadata record
   ; this only formats them, as the Curve name does
    (``format_curve_metadata_value``).
    """
    (record,) = build_curve_metadata([trace], sources_by_path, result_set_labels or {}, schema)
    found: Dict[str, Tuple[str, str]] = {}
    for key in keys:
        if key == COLUMN_PARAMETER_SET:
            continue
        text = format_curve_metadata_value(key, record.get(key))
        if text:
            found[key] = (resolve_field_label(key, schema), text)
    return found
