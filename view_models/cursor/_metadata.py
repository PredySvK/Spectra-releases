"""The curve's own metadata for the Cursor Box (ADR §1.149)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.filter_card_config import (
    BUILTIN_COLUMN_LABELS, COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_ORDER,
)
from selection.source_facets import curve_field_value, curve_range_value
from selection.trace_filter import IDENTITY_FACET_ATTR, format_result_kind
from view_models.plot import Trace
from view_models.trace_filter import identity_for_trace

from ._box import format_auto


def read_curve_metadata(
    trace: Trace, keys: Iterable[str], schema: Mapping[str, Dict[str, Any]],
    sources_by_path: Dict[str, Any], result_set_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Tuple[str, str]]:
    """``{key: (label, text)}`` for every key of `keys` the curve can answer.

    Keys are Configure Filters column keys (built-ins and schema fields); a key
    the curve or the open project has no value for is simply absent, never "N/A".
    Parameter set is not offered.
    Numeric fields use the box's Auto format, dates show as stored ISO text.
    """
    identity = identity_for_trace(trace, sources_by_path, result_set_labels)
    found: Dict[str, Tuple[str, str]] = {}
    for key in keys:
        text: Optional[str] = None
        if key == COLUMN_CHANNEL:
            text = trace.channel_name or None
        elif key in IDENTITY_FACET_ATTR:
            text = getattr(identity, IDENTITY_FACET_ATTR[key])
        elif key == COLUMN_ANALYSIS_TYPE:
            text = format_result_kind(identity.result_kind) if identity.result_kind else None
        elif key == COLUMN_ORDER:
            text = None if identity.order is None else f"{identity.order:g}"
        elif key in schema and identity.source is not None:
            text = curve_field_value(
                identity.source, dict(schema), key, identity.channel_identity, identity.channel_index)
            if text is None:
                value = curve_range_value(
                    identity.source, dict(schema), key, identity.channel_identity, identity.channel_index)
                text = format_auto(value) if isinstance(value, float) else value
        if text:
            label = BUILTIN_COLUMN_LABELS.get(key) or schema.get(key, {}).get("custom_label", key)
            found[key] = (label, str(text))
    return found
