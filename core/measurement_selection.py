# =====================================================================
# FILE: core/measurement_selection.py
# =====================================================================
"""
`MeasurementSelection` -- the named query that says what a batch operation runs
over (ARCHITECTURE_DECISIONS §1.12).

Lives in core/ because it is pure data: no I/O, no Qt, JSON round-trippable, so
it can be stored in a project today and inside a workflow recipe later. The
evaluation half -- turning the query into actual sources and channels -- lives
in selection/measurement_selection/.

Why this exists at all: the interactive workflow answers "what am I looking at"
with "the active dock", and that answer is wrong for a batch. A background job
started two minutes ago has to be able to say what it computed over, and by the
time it finishes the active dock is very likely a different one. This is the
same trap as when routing results, one level up: there it is
"where does this result belong", here it is "what was it computed over".

The interactive dock workflow is not replaced by this. The two run side by side
-- see §1.12 for the invariant that keeps them producing the same numbers.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from core.frozen import freeze_identities, freeze_range_map, freeze_str_map
from core.models import ChannelIdentity

# A frozen literal list of sources: what "run it on what I have selected right
# now" produces. Reproducible forever, but it never picks up new measurements.
MODE_EXPLICIT = "explicit"

# A facet predicate evaluated at run time: "the same thing on new data". This is
# the mode a saved recipe wants.
MODE_QUERY = "query"

MODES = (MODE_EXPLICIT, MODE_QUERY)


@dataclass(frozen=True)
class MeasurementSelection:
    """
    Which measurements and which of their channels a batch runs over.

    Frozen the whole way down -- the mapping fields are wrapped in
    MappingProxyType by __post_init__, so a selection handed to a background job
    cannot be edited underneath it while the job is walking it. That is the same
    reasoning as NVHDataBlock's read-only `values` (§1.18): a half-frozen object
    is worse than a mutable one, because it invites the assumption it is safe.

    `column_values` maps Filter column keys to accepted text values (ADR §1.131).
    An absent key imposes no constraint; a present empty tuple selects nothing.
    Identity columns and categorical metadata share this one map.
    """
    name: str = ""
    mode: str = MODE_QUERY

    # --- query mode -------------------------------------------------------
    # Test Setup labels (SourceEntry.setup_label). Empty means "any setup".
    setup_labels: Tuple[str, ...] = ()
    # Filter column key -> accepted values. AND across columns, OR inside one.
    # Query mode uses all columns; explicit mode uses Identity columns only.
    column_values: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    # field key -> (lo, hi) in the field's own type: floats for numeric fields,
    # ISO "YYYY-MM-DD" strings for date fields (see comparator_facets).
    ranges: Mapping[str, Tuple[Any, Any]] = field(default_factory=dict)

    # --- explicit mode ----------------------------------------------------
    source_ids: Tuple[str, ...] = ()
    # Exact pairs belong only to a frozen explicit selection. None means all;
    # an empty tuple means none. Query mode uses column_values exclusively.
    channel_identities: Optional[Tuple[ChannelIdentity, ...]] = None

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(
                f"Unknown selection mode '{self.mode}'. Valid modes: {', '.join(MODES)}."
            )
        object.__setattr__(self, "setup_labels", tuple(str(label) for label in self.setup_labels))
        object.__setattr__(self, "source_ids", tuple(str(sid) for sid in self.source_ids))
        object.__setattr__(self, "column_values", freeze_str_map(self.column_values))
        object.__setattr__(self, "ranges", freeze_range_map(self.ranges))
        if self.channel_identities is not None:
            if self.mode != MODE_EXPLICIT:
                raise ValueError("Exact channel identities require explicit selection mode.")
            object.__setattr__(self, "channel_identities", freeze_identities(self.channel_identities))

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe form, as stored in a project and later in a recipe."""
        data = {
            "name": self.name,
            "mode": self.mode,
            "setup_labels": list(self.setup_labels),
            "column_values": {key: list(values) for key, values in self.column_values.items()},
            "ranges": {key: list(bounds) for key, bounds in self.ranges.items()},
            "source_ids": list(self.source_ids),
        }
        if self.mode == MODE_EXPLICIT:
            data["channel_identities"] = (
                None if self.channel_identities is None else
                [list(identity) for identity in self.channel_identities]
            )
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MeasurementSelection":
        data = data or {}
        return cls(
            name=str(data.get("name") or ""),
            mode=str(data.get("mode") or MODE_QUERY),
            setup_labels=tuple(data.get("setup_labels") or ()),
            column_values=data.get("column_values") or {},
            ranges={
                key: tuple(bounds) for key, bounds in (data.get("ranges") or {}).items()
                if bounds is not None
            },
            source_ids=tuple(data.get("source_ids") or ()),
            channel_identities=data.get("channel_identities"),
        )
