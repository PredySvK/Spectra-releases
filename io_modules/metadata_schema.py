# io_modules/metadata_schema.py
"""
Central Business Logic Service managing global metadata schema mapping rules.
Decoupled schema generation and translation from low-level disk IO managers.
Cleaned from legacy ternary evaluation dead-code blocks to enforce readability.
All internal documentation strings and variable labels are standardly written in English.
"""

import datetime as _dt
import re
from typing import List, Dict, Any, Callable, Iterable, Optional
from core.models import MeasurementRunIndex
from io_modules.metadata_parser import find_matching_row, normalize_file_key


# --- Typed metadata schema (ADR §1.1) --------------------------------------
#
# Every schema field carries a `kind`: one of these. The kind is inferred once
# from the values a column actually holds (generate_baseline_schema_master) and
# may be overridden by hand in the Metadata Editor, which sets `kind_is_manual`
# so a later rescan does not re-infer over the user's choice. Values are parsed
# to their typed form once at ingest (see session.project), never per
# filter -- a numeric facet compares numbers, not "10000" < "9000" as text.
FIELD_KINDS = ("str", "int", "float", "date")
NUMERIC_KINDS = ("int", "float")

# Accepted on input; a date value is *stored* normalised to ISO "YYYY-MM-DD"
# (a string), which is both JSON-native for the project file and chronologically
# sortable as-is. The facet layer parses it back to a date for range compares.
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_int(raw: Any) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip().replace(" ", "")
    if text.endswith(".0"):
        text = text[:-2]
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_float(raw: Any) -> Optional[float]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(" ", "")
    # A lone comma is a decimal separator here (European sheets); a string with
    # both is left alone rather than guessed at.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_date(raw: Any, date_format: Optional[str] = None) -> Optional[str]:
    """A raw cell -> ISO 'YYYY-MM-DD', or None. Any time component is dropped."""
    if isinstance(raw, _dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, _dt.date):
        return raw.isoformat()
    text = str(raw).strip()
    if not text:
        return None
    head = text.split()[0]
    formats = (date_format,) if date_format else _DATE_FORMATS
    for fmt in formats:
        try:
            return _dt.datetime.strptime(head, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return None


def parse_value(raw: Any, kind: str, date_format: Optional[str] = None) -> Any:
    """One raw metadata cell -> its typed form, or None when blank/unparseable."""
    if _is_blank(raw):
        return None
    if kind == "int":
        return _parse_int(raw)
    if kind == "float":
        return _parse_float(raw)
    if kind == "date":
        return _parse_date(raw, date_format=date_format)
    return raw.strip() if isinstance(raw, str) else str(raw)


def resolve_date_format(values: Iterable[Any]) -> Optional[str]:
    """
    Finds a single unambiguous date format that fits every non-blank value in a column.

    Returns the strftime format string, or None if the column contains values that
    cannot be parsed as dates, values requiring conflicting formats, or ambiguous
    date formats (such as %d/%m/%Y vs %m/%d/%Y where all day and month values <= 12).
    """
    seen = [value for value in values if not _is_blank(value)]
    if not seen:
        return None

    string_values: List[str] = []
    for val in seen:
        if isinstance(val, (_dt.date, _dt.datetime)):
            continue
        if isinstance(val, (int, float, bool)):
            return None
        text = str(val).strip()
        if not text:
            continue
        string_values.append(text.split()[0])

    if not string_values:
        return "%Y-%m-%d"

    matching = []
    for fmt in _DATE_FORMATS:
        fits_all = True
        for s in string_values:
            try:
                _dt.datetime.strptime(s, fmt)
            except (ValueError, TypeError):
                fits_all = False
                break
        if fits_all:
            matching.append(fmt)

    if len(matching) == 1:
        return matching[0]

    return None


# Backward-compatible alias
infer_date_format = resolve_date_format


def infer_field_kind(values: Iterable[Any]) -> str:
    """
    The tightest kind that fits every non-blank value seen for a column.

    Checked int -> float -> date -> str, so a column of bare years ("2024")
    reads as int, not date; the user retypes it in the Metadata Editor if they
    mean a date. A column with even one value that does not fit falls straight
    back to str -- a mixed column is never silently coerced.

    For date inference (#327), a single unambiguous date format must fit every
    value in the column. If multiple formats match (ambiguous day/month) or
    conflicting formats are needed per cell, the column falls back to str.
    """
    seen = [value for value in values if not _is_blank(value)]
    if not seen:
        return "str"
    if all(_parse_int(value) is not None for value in seen):
        return "int"
    if all(_parse_float(value) is not None for value in seen):
        return "float"
    if resolve_date_format(seen) is not None:
        return "date"
    return "str"


def resolve_schema_field_kind(config: Dict[str, Any], baseline: Optional[dict] = None) -> str:
    """The Auto hint, independent of a manually pinned kind (including old projects)."""
    baseline = baseline or {}
    return (baseline.get("inferred_kind") or baseline.get("kind")
            or config.get("inferred_kind")
            or (config.get("kind", "str") if not config.get("kind_is_manual") else "str"))


def resolve_schema_field(defaults: dict, stored: Optional[dict] = None) -> dict:
    """Merge discovery with user choices; inference and field origin stay factual."""
    if not isinstance(stored, dict):
        entry = dict(defaults)
        if "kind" in entry:
            entry.setdefault("inferred_kind", entry["kind"])
            entry.setdefault("kind_is_manual", False)
        return entry

    manual = bool(stored.get("kind_is_manual", False))
    entry = {
        key: stored.get(key, defaults.get(key, fallback))
        for key, fallback in (("custom_label", ""), ("is_active", True),
                              ("usable_as_filter", True))
    }
    entry.update(
        layer=defaults.get("layer", stored.get("layer", "excel")),
        kind=stored.get("kind", "str") if manual else defaults.get("kind", stored.get("kind", "str")),
        kind_is_manual=manual,
        inferred_kind=resolve_schema_field_kind(stored, defaults),
    )
    date_format = (stored.get("date_format") if manual else defaults.get("date_format"))
    date_format = date_format or defaults.get("date_format") or stored.get("date_format")
    if date_format:
        entry["date_format"] = date_format
    return entry


def build_schema_field_choice(config: dict, baseline: dict, chosen_kind: Optional[str]) -> dict:
    """Apply Auto or a manual choice without losing the inference hint or date format."""
    defaults = dict(config)
    defaults.update(baseline)
    defaults["kind"] = resolve_schema_field_kind(config, baseline)
    defaults["inferred_kind"] = defaults["kind"]
    decided = dict(config, kind=chosen_kind, kind_is_manual=chosen_kind is not None)
    return resolve_schema_field(defaults, decided)


def parsed_metadata_for_row(raw_by_key: Dict[str, Any],
                            schema: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    A source's typed metadata: each schema field parsed once to its `kind`.

    Keyed by schema field name. A field whose raw value is blank or does not
    parse for its kind is left out rather than stored as None, so `key in
    parsed` means "has a usable typed value" -- which is exactly what a facet
    needs to decide whether a source is in range or simply has no opinion.
    """
    parsed: Dict[str, Any] = {}
    for key, config in schema.items():
        if key.startswith("__"):
            continue
        typed = parse_value(
            raw_by_key.get(key),
            config.get("kind", "str"),
            date_format=config.get("date_format"),
        )
        if typed is not None:
            parsed[key] = typed
    return parsed


def resolve_excel_metadata_for_files(
    file_names: Iterable[str],
    primary_lookup: Dict[str, Dict[str, Any]],
    fallback_lookup: Dict[str, Dict[str, Any]],
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Resolves each scanned file's Level 2 Excel row: the project's own
    metadata.xlsx (primary) first, the folder-adjacent Metadata.xlsx
    (fallback) only for a file the primary sheet never heard of.

    Scoped to `file_names` -- the files actually found in this folder -- on
    purpose. A project's metadata.xlsx typically describes a whole measurement
    campaign, most of which was never recorded into any one folder; matching
    the two sheets against each other wholesale would log a "skip" for every
    row they happen to share, most of it about files that do not exist here.
    Checking file-by-file means only real conflicts are ever reported, and as
    one count rather than one line per file.

    Returns the resolved lookup, keyed by each file's own normalized identity.
    """
    log_fn = log_fn or print
    lookup: Dict[str, Dict[str, Any]] = {}
    fallback_skipped = 0

    for file_name in file_names:
        key = normalize_file_key(file_name)
        primary_row = find_matching_row(key, primary_lookup)
        if primary_row is not None:
            lookup[key] = primary_row
            if find_matching_row(key, fallback_lookup) is not None:
                fallback_skipped += 1
            continue

        fallback_row = find_matching_row(key, fallback_lookup)
        if fallback_row is not None:
            lookup[key] = fallback_row

    if fallback_skipped:
        log_fn(
            f"METADATA_IO: {fallback_skipped} folder Metadata.xlsx row(s) skipped "
            f"-- already defined in the project's metadata.xlsx."
        )
    return lookup


def generate_baseline_schema_master(indexed_runs: List[MeasurementRunIndex]) -> Dict[str, Any]:
    """
    Dynamically scans runs and channels attributes to build an agnostic schema footprint.
    Predefines human-readable labels and forces default inactive states for system tags.
    """
    schema = {}

    # Every value each Excel column carries across the scanned runs, so the
    # column's kind can be inferred from the data rather than guessed per field.
    excel_values: Dict[str, list] = {}
    for run in indexed_runs:
        metadata = getattr(run, 'metadata', None)
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                excel_values.setdefault(key, []).append(value)

    # 1. Map Level 2 Excel columns keys (Enabled by default)
    for run in indexed_runs:
        if getattr(run, 'metadata', None) and isinstance(run.metadata, dict):
            for key in run.metadata.keys():
                clean_key = str(key).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
                if clean_key != "filename" and key not in schema:
                    raw_vals = excel_values.get(key, [])
                    inferred_kind = infer_field_kind(raw_vals)
                    field_def: Dict[str, Any] = {
                        "custom_label": str(key), "is_active": True,
                        "usable_as_filter": True, "layer": "excel",
                        "kind": inferred_kind,
                    }
                    if inferred_kind == "date":
                        date_fmt = resolve_date_format(raw_vals)
                        if date_fmt:
                            field_def["date_format"] = date_fmt
                    schema[key] = resolve_schema_field(field_def)

    # 2. Hardwire explicit Level 1 properties with optimized labels, filter
    #    policy and kind -- known facts a reader discovers per channel, not
    #    per file (BUGS.md N1/N2). Every reader that has an equivalent (both
    #    .unv and .asc supply func_type/abscissa_inc/abscissa_min/num_pts/
    #    sampling_rate/ordinate_axis_units_lab; only .unv's dataset-58 header
    #    has id1..id5) fills the corresponding ChannelMetadata attribute, and
    #    "layer": "channel" tells comparator_facets to read it from there --
    #    never assumed to be UNV-only or file-level.
    channel_expert_map = {
        "func_type": ("Signal Domain (Time/Freq)", True, "str"),
        "abscissa_inc": ("Time Increment", True, "float"),
        "num_pts": ("Total Data Points (Samples)", True, "int"),
        "sampling_rate": ("Sampling Rate [Hz]", True, "float"),
        "abscissa_min": ("Time Start Offset [s]", False, "float"),
        "id1": ("Measurement Setup Description", False, "str"),
        "id2": ("Acquisition Date & Time", False, "str"),
        "id3": ("File Creation Timestamp", False, "str"),
        "id4": ("Run Section Reference", False, "str"),
        "id5": ("Channel Hardware Label", False, "str"),
        "ordinate_axis_units_lab": ("Physical Measurement Unit", True, "str"),
        # MASTA's header (reader_masta); every other reader leaves them empty.
        "design": ("Design", True, "str"),
        "scenario": ("Scenario", True, "str"),
        "damping": ("Damping", True, "str"),
    }
    # MASTA's Description N: as many as the scanned channels carry, off by default.
    description_count = max(
        (int(key.rsplit("_", 1)[1])
         for run in indexed_runs for meta in (getattr(run, "available_channels", None) or {}).values()
         for key in vars(meta) if re.fullmatch(r"description_\d+", key)),
        default=0)
    for number in range(1, description_count + 1):
        channel_expert_map[f"description_{number}"] = (f"Description {number}", False, "str")

    for key, (nice_label, default_active_state, kind) in channel_expert_map.items():
        if key not in schema:
            schema[key] = resolve_schema_field({
                "custom_label": nice_label,
                "is_active": default_active_state,
                "usable_as_filter": True,
                "layer": "channel",
                "kind": kind,
            })

    return schema
