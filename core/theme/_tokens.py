"""Theme / Graph theme enums, the resolver and the frozen colour tokens."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Tuple


class Theme(str, Enum):
    DARK = "dark"
    LIGHT = "light"


class GraphTheme(str, Enum):
    FOLLOW = "follow"
    DARK = "dark"
    LIGHT = "light"


class GraphLook(str, Enum):
    """The resolved look of a plot area: never "follow"."""
    DARK = "dark"
    LIGHT = "light"


def resolve_theme(value: object) -> Theme:
    """Unreadable or absent persisted choices mean Dark."""
    try:
        return Theme(value)
    except (ValueError, TypeError):
        return Theme.DARK


def resolve_graph_theme(value: object) -> GraphTheme:
    """Unreadable or absent persisted choices mean Follow theme."""
    try:
        return GraphTheme(value)
    except (ValueError, TypeError):
        return GraphTheme.FOLLOW


def resolve_graph_look(theme: Theme, graph_theme: GraphTheme) -> GraphLook:
    """Follow theme takes the application Theme; Dark / Light override it."""
    if graph_theme is GraphTheme.FOLLOW:
        return GraphLook(theme.value)
    return GraphLook(graph_theme.value)


@dataclass(frozen=True)
class AppTokens:
    """Colours `QPalette` does not cover, for one Theme."""
    icon_on_ribbon: str
    icon_on_accent: str
    icon_disabled: str
    ribbon_primary: Tuple[str, str]
    ribbon_commit: Tuple[str, str]
    ribbon_danger: Tuple[str, str]
    title_close_hover: str
    input_error: str
    log_background: str
    log_text: str
    log_border: str
    item_missing: str
    item_unreadable: str
    pool_in: str
    pool_project_folder: str
    pool_metadata: str
    text_muted: str
    text_subtle: str
    text_hint: str
    text_description: str
    text_problem: str
    text_inactive: str
    text_divider: str
    welcome_accent: str
    welcome_border: str
    action_primary: str
    search_highlight_background: str
    search_highlight_text: str
    cursor_background: str
    cursor_border: str
    cursor_accent: str
    cursor_checked: str
    cursor_text_off: str
    cursor_text_on: str
    cursor_chip_background: str
    cursor_chip_border: str
    cursor_chip_hover: str
    cursor_chip_checked: str
    cursor_chip_checked_border: str
    cursor_chip_disabled: str
    cursor_chip_disabled_border: str
    workflow_background: str
    workflow_surface: str
    workflow_border: str
    workflow_text: str
    workflow_muted: str
    workflow_accent: str
    workflow_error: str
    workflow_ready: str
    workflow_kind_colours: Mapping[str, str]
    help_background: str
    help_text: str
    help_heading: str
    help_subheading: str
    help_rule: str  # heading underline and table borders
    help_link: str
    help_code_background: str
    help_note_background: str
    help_note_text: str


@dataclass(frozen=True)
class GraphTokens:
    """Plot-area colours for one `GraphLook`."""
    background: str
    base_curve: str
    axis: str  # axes, their labels and the legend text: pyqtgraph's own default foreground
    cursor_box_line: str
    cursor_box_fill: Tuple[int, int, int, int]
    band_rms_line: str
    band_rms_line_hover: str
    band_rms_box_fill: Tuple[int, int, int, int]
    band_rms_region_fill: Tuple[int, int, int, int]
    band_rms_region_hover_fill: Tuple[int, int, int, int]
    curve_palette: Tuple[str, ...]


# Generated offline; see docs/curve_palette_generation.md. Four lightness
# rounds of the same twelve hues, one row per round.
_CURVE_PALETTES = {
    GraphLook.DARK: (
        "#ff958d", "#01d5b2", "#ea91ef", "#b5c333", "#95b6ff", "#ff9b51",
        "#01cfe0", "#ff8dbc", "#6ed274", "#bda7ff", "#e6ad00", "#54c4ff",
        "#d55753", "#009d82", "#b55fba", "#848f00", "#5680e6", "#ca6800",
        "#0198a4", "#cd568b", "#399e43", "#8f6edb", "#a97f00", "#0091c9",
        "#ffd1cd", "#45ffd8", "#fdcaff", "#dbea62", "#cfdeff", "#ffd4b8",
        "#81f2ff", "#ffcfe0", "#96fa9a", "#e0d8ff", "#ffd988", "#bae5ff",
        "#b33736", "#007b66", "#95419a", "#677000", "#3a61c4", "#9f5100",
        "#007781", "#ab366e", "#097f23", "#7250ba", "#856300", "#00729f",
    ),
    GraphLook.LIGHT: (
        "#ac3031", "#007460", "#8e3b94", "#626a00", "#355bbd", "#974c00",
        "#00717a", "#a43068", "#00791e", "#6c4ab3", "#7e5e00", "#006c97",
        "#810010", "#004e40", "#69126f", "#414700", "#173796", "#673200",
        "#004c53", "#7b0046", "#005211", "#4c258c", "#553e00", "#004867",
        "#d55753", "#009d82", "#b55fba", "#848f00", "#5680e6", "#ca6800",
        "#0198a4", "#cd568b", "#399e43", "#8f6edb", "#a97f00", "#0091c9",
        "#5c0009", "#00372c", "#4d0053", "#2d3100", "#061d7c", "#492200",
        "#00353a", "#580031", "#003909", "#380473", "#3c2b00", "#003249",
    ),
}


def curve_palette(look: GraphLook) -> Tuple[str, ...]:
    """Twelve hues in four lightness rounds (48 colours) for black (Dark) or white (Light) plot areas."""
    return _CURVE_PALETTES[look]


_DARK_APP = AppTokens(
    icon_on_ribbon="#e6e6e6", icon_on_accent="#ffffff", icon_disabled="#6f6f6f",
    ribbon_primary=("#33465c", "#3f566f"),
    ribbon_commit=("#4a4366", "#585078"),
    ribbon_danger=("#a12d2d", "#b23a3a"),
    title_close_hover="#c42b1c",
    input_error="#d9534f",
    log_background="#1e1e1e", log_text="#aaaaaa", log_border="#2d2d2d",
    item_missing="#c62828", item_unreadable="#9e9e9e",
    pool_in="#2e7d32", pool_project_folder="#1565c0", pool_metadata="#ef6c00",
    text_muted="#808080", text_subtle="#888888", text_hint="#9aa0a6",
    text_description="#666666", text_problem="#b00020", text_inactive="#a0a0a4",
    text_divider="#000000",
    welcome_accent="#3b5998", welcome_border="#444444", action_primary="#2b579a",
    search_highlight_background="#d6b656", search_highlight_text="#151515",
    cursor_background="#2e3436", cursor_border="#444c4e", cursor_accent="#2ec4b6",
    cursor_checked="#1f4a4a", cursor_text_off="#8a9a9a", cursor_text_on="#e8fffd",
    cursor_chip_background="rgba(255,255,255,20)",
    cursor_chip_border="rgba(255,255,255,45)",
    cursor_chip_hover="rgba(255,255,255,50)", cursor_chip_checked="#1f9e92",
    cursor_chip_checked_border="rgba(255,255,255,120)",
    cursor_chip_disabled="rgba(255,255,255,8)",
    cursor_chip_disabled_border="rgba(255,255,255,20)",
    workflow_background="#1e1e1e", workflow_surface="#2d2d2d",
    workflow_border="#606060", workflow_text="#ffffff",
    workflow_muted="#a0a0a0", workflow_accent="#b8b8b8",
    workflow_error="#ef827e", workflow_ready="#7bc99b",
    workflow_kind_colours=MappingProxyType({
        "time_response": "#5bb8a6", "spectrum": "#e5bb62",
        "spectrogram": "#ac8fe5", "order_cut": "#78aee5",
        "overall_level": "#e58b78",
    }),
    help_background="#1e1e1e", help_text="#d4d4d4", help_heading="#ffffff",
    help_subheading="#569cd6", help_rule="#555555", help_link="#6aa9ff",
    help_code_background="#2d2d2d", help_note_background="#4a3b12", help_note_text="#ffe08a",
)

_LIGHT_APP = AppTokens(
    icon_on_ribbon="#2b2b2b", icon_on_accent="#ffffff", icon_disabled="#a8a8a8",
    ribbon_primary=("#33465c", "#3f566f"),
    ribbon_commit=("#4a4366", "#585078"),
    ribbon_danger=("#a12d2d", "#b23a3a"),
    title_close_hover="#c42b1c",
    input_error="#d9534f",
    log_background="#ffffff", log_text="#404040", log_border="#c8c8c8",
    item_missing="#c62828", item_unreadable="#757575",
    pool_in="#2e7d32", pool_project_folder="#1565c0", pool_metadata="#ef6c00",
    text_muted="#666666", text_subtle="#707070", text_hint="#5f6368",
    text_description="#555555", text_problem="#b00020", text_inactive="#707074",
    text_divider="#c8c8c8",
    welcome_accent="#3b5998", welcome_border="#c0c0c0", action_primary="#2b579a",
    search_highlight_background="#ffe08a", search_highlight_text="#151515",
    cursor_background="#eef1f2", cursor_border="#b8c0c2", cursor_accent="#16877d",
    cursor_checked="#bfe6e1", cursor_text_off="#5c6a6a", cursor_text_on="#0b3b37",
    cursor_chip_background="rgba(0,0,0,12)",
    cursor_chip_border="rgba(0,0,0,40)",
    cursor_chip_hover="rgba(0,0,0,30)", cursor_chip_checked="#1f9e92",
    cursor_chip_checked_border="rgba(0,0,0,110)",
    cursor_chip_disabled="rgba(0,0,0,6)",
    cursor_chip_disabled_border="rgba(0,0,0,18)",
    workflow_background="#f5f5f5", workflow_surface="#ffffff",
    workflow_border="#9a9a9a", workflow_text="#1e1e1e",
    workflow_muted="#5f5f5f", workflow_accent="#555555",
    workflow_error="#c62828", workflow_ready="#2e7d32",
    workflow_kind_colours=MappingProxyType({
        "time_response": "#1f8a78", "spectrum": "#a67a00",
        "spectrogram": "#6a4cb8", "order_cut": "#2a6fb8",
        "overall_level": "#c24a30",
    }),
    help_background="#ffffff", help_text="#1e1e1e", help_heading="#000000",
    help_subheading="#1f5fa8", help_rule="#c8c8c8", help_link="#0b5cc4",
    help_code_background="#eeeeee", help_note_background="#fff3cd", help_note_text="#5c4400",
)

_DARK_GRAPH = GraphTokens(
    background="#000000",
    base_curve="#ffcc00",
    axis="#969696",
    cursor_box_line="#e8edf2",
    cursor_box_fill=(18, 24, 31, 230),
    band_rms_line="#c8c864",
    band_rms_line_hover="#ff0000",
    band_rms_box_fill=(18, 24, 31, 210),
    band_rms_region_fill=(90, 160, 220, 40),
    band_rms_region_hover_fill=(90, 160, 220, 70),
    curve_palette=curve_palette(GraphLook.DARK),
)


_LIGHT_GRAPH = GraphTokens(
    background="#ffffff",
    base_curve="#806600",
    axis="#505050",
    cursor_box_line="#202830",
    cursor_box_fill=(245, 248, 252, 230),
    band_rms_line="#505050",
    band_rms_line_hover="#202830",
    band_rms_box_fill=(245, 248, 252, 210),
    band_rms_region_fill=(30, 100, 170, 40),
    band_rms_region_hover_fill=(30, 100, 170, 70),
    curve_palette=curve_palette(GraphLook.LIGHT),
)


def app_tokens(theme: Theme) -> AppTokens:
    return _LIGHT_APP if theme is Theme.LIGHT else _DARK_APP


def graph_tokens(look: GraphLook) -> GraphTokens:
    return _LIGHT_GRAPH if look is GraphLook.LIGHT else _DARK_GRAPH
