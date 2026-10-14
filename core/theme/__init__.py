"""
theme: the one home of the application's colours -- Qt-free data.

`Theme` (Dark / Light) is the look of the application; `GraphTheme` (Follow
theme / Dark / Light) is the look of a graph's plot area and is chosen
independently (CONTEXT.md > Appearance, ADR §1.158). `resolve_graph_look`
turns the pair into the one `GraphLook` a graph draws with.

Application tokens, plot-area tokens and curve palettes exist for both looks;
`resolve_theme` turns a persisted value into a Theme (Dark when unreadable).
"""

from core.theme._tokens import (
    AppTokens,
    GraphLook,
    GraphTheme,
    GraphTokens,
    Theme,
    app_tokens,
    curve_palette,
    graph_tokens,
    resolve_graph_look,
    resolve_graph_theme,
    resolve_theme,
)

__all__ = [
    "AppTokens",
    "GraphLook",
    "GraphTheme",
    "GraphTokens",
    "Theme",
    "app_tokens",
    "curve_palette",
    "graph_tokens",
    "resolve_graph_look",
    "resolve_graph_theme",
    "resolve_theme",
]
