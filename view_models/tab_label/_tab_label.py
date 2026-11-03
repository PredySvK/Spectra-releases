"""
Core pure-function implementation of workspace tab label resolution.

Builds short Tab labels and tooltips for graph tabs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Union

from core.units import strip_channel_name_prefix
from view_models.analysis_kinds import resolve_analysis_kind

MAX_TAB_LABEL_LENGTH: int = 25


@dataclass(frozen=True)
class TabSource:
    """A data source displayed on a graph dock: measurement file/channel or result set."""
    file_name: str
    channel_name: str
    result_set_id: str = ""


@dataclass(frozen=True)
class TabLabel:
    """Short display label, full tooltip and search-friendly full source text."""
    label: str
    tooltip: str
    full_source_name: str = ""


def build_tab_source(
    file_name: str = "",
    channel_name: str = "",
    result_set_id: str = "",
) -> TabSource:
    """Builds a TabSource from explicit parameters."""
    return TabSource(
        file_name=str(file_name or ""),
        channel_name=str(channel_name or ""),
        result_set_id=str(result_set_id or ""),
    )


def _elide(text: str, max_length: int = MAX_TAB_LABEL_LENGTH) -> str:
    """Truncates text exceeding max_length with an ellipsis character (…)."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def _as_tab_source(item: Union[TabSource, Mapping[str, Any]]) -> TabSource:
    """Converts a TabSource or descriptor mapping to a TabSource."""
    if isinstance(item, TabSource):
        return item
    if isinstance(item, Mapping):
        file_name = str(item.get("file_name", "") or (item.get("meta_ref") or {}).get("file_name", ""))
        channel_name = str(item.get("channel_name", "") or (item.get("meta_ref") or {}).get("channel_name", ""))
        result_set_id = str(item.get("result_set_id", ""))
        return TabSource(file_name=file_name, channel_name=channel_name, result_set_id=result_set_id)
    return TabSource(file_name="", channel_name=str(item))


def _deduplicate_sources(sources: Sequence[Union[TabSource, Mapping[str, Any]]]) -> List[TabSource]:
    """
    Counts each measurement file + channel pair once, and each result-set curve once.
    """
    seen_measurement_keys = set()
    deduped: List[TabSource] = []
    for item in sources:
        source = _as_tab_source(item)
        if source.result_set_id:
            deduped.append(source)
        else:
            clean_chan = strip_channel_name_prefix(source.channel_name)
            key = (source.file_name, clean_chan)
            if key not in seen_measurement_keys:
                seen_measurement_keys.add(key)
                deduped.append(source)
    return deduped


def build_tab_label(
    analysis_kind: str,
    sources: Sequence[Union[TabSource, Mapping[str, Any]]] = (),
    *,
    dead_link: Optional[Any] = None,
    custom_label: Optional[str] = None,
    max_label_length: int = MAX_TAB_LABEL_LENGTH,
) -> TabLabel:
    """
    Builds the display label, tooltip and full source name for a workspace graph tab.

    - Dead link: ⚠ <channel> with 'Missing' and reason in tooltip.
    - Custom label: overrides the automatic label; tooltip retains source details.
    - Single source: <icon> <channel> (no ×N).
    - Comparison (N > 1):
        - common channel -> <icon> <channel> ×N
        - common file -> <icon> <file> ×N
        - otherwise -> <icon> Compare ×N
    - Label width is capped at max_label_length (~25 chars) with an ellipsis.
    """
    # 1. Missing file / Dead link
    if dead_link is not None:
        raw_channel = getattr(dead_link, "channel_name", "") or str(dead_link)
        clean_channel = strip_channel_name_prefix(raw_channel) if raw_channel else "Missing"
        reason = getattr(dead_link, "reason", "")
        reason_text = f" ({reason})" if reason else ""
        raw_label = f"⚠ {clean_channel}"
        tooltip = f"Missing: {clean_channel}{reason_text}"
        full_source = f"Missing: {clean_channel}"
        return TabLabel(
            label=_elide(raw_label, max_label_length),
            tooltip=tooltip,
            full_source_name=full_source,
        )

    # Resolve analysis kind icon
    try:
        kind_entry = resolve_analysis_kind(analysis_kind)
        icon = kind_entry.icon
        display_name = kind_entry.display_name
    except (ValueError, KeyError):
        icon = ""
        display_name = analysis_kind

    prefix = f"{icon} " if icon else ""

    # 2. Deduplicated sources
    deduped = _deduplicate_sources(sources)
    n = len(deduped)

    # Build sources tooltip lines
    cleaned_channels = [strip_channel_name_prefix(s.channel_name) for s in deduped]
    source_lines: List[str] = []
    for s, ch in zip(deduped, cleaned_channels):
        if s.file_name and ch:
            source_lines.append(f"{s.file_name} [{ch}]")
        elif s.file_name:
            source_lines.append(s.file_name)
        elif ch:
            source_lines.append(ch)

    sources_summary = "\n".join(source_lines)
    full_source_text = ", ".join(source_lines) if source_lines else display_name

    # 3. Custom label
    if custom_label is not None and custom_label.strip():
        trimmed_custom = custom_label.strip()
        tooltip = f"{trimmed_custom}\n{sources_summary}" if sources_summary else trimmed_custom
        return TabLabel(
            label=_elide(trimmed_custom, max_label_length),
            tooltip=tooltip,
            full_source_name=trimmed_custom,
        )

    # 4. Automatic label
    if n == 0:
        raw_label = f"{prefix}{display_name}".strip()
        tooltip = display_name
        full_source_text = raw_label
    elif n == 1:
        clean_ch = cleaned_channels[0]
        raw_label = f"{prefix}{clean_ch}".strip()
        tooltip = source_lines[0] if source_lines else clean_ch
        full_source_text = tooltip
    else:
        # Check common channel
        has_common_channel = len(set(cleaned_channels)) == 1 and bool(cleaned_channels[0])
        files = [s.file_name for s in deduped if s.file_name]
        has_common_file = len(files) == n and len(set(files)) == 1 and bool(files[0])

        if has_common_channel:
            raw_label = f"{prefix}{cleaned_channels[0]} ×{n}".strip()
        elif has_common_file:
            raw_label = f"{prefix}{files[0]} ×{n}".strip()
        else:
            raw_label = f"{prefix}Compare ×{n}".strip()

        tooltip = sources_summary

    return TabLabel(
        label=_elide(raw_label, max_label_length),
        tooltip=tooltip,
        full_source_name=full_source_text,
    )
