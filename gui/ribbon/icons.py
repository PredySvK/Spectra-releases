# =====================================================================
# FILE: gui/ribbon/icons.py
# =====================================================================
"""
Loads the bundled ribbon icon set (resources/icons/ribbon/*.svg) as QIcons,
recoloured for whatever background the button sits on.

The SVGs are Lucide geometry with ``stroke="currentColor"``. Qt's SVG renderer
has no CSS cascade, so ``currentColor`` would fall back to black and vanish on
the dark ribbon -- this module swaps that token for an explicit hex before
rasterising. One cache per (name, colour, size) keeps repeated ribbon rebuilds
from re-reading and re-rendering the files.

Lives in gui/ribbon/ because it is the same kind of thing as ribbon_widgets.py:
a shared building block of the ribbon, Qt-only, knowing nothing about the
project model.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from core.asset_paths import resource_path

# Icon foreground per button background. "on_dark" is the ribbon's own grey;
# "on_accent" is any coloured (primary/commit/danger) button, where the glyph
# has to stay white to read.
COLOR_ON_DARK = "#e6e6e6"
COLOR_ON_ACCENT = "#ffffff"
COLOR_DISABLED = "#6f6f6f"


@lru_cache(maxsize=256)
def _rendered(name: str, color: str, px: int) -> QPixmap:
    path = resource_path("resources", "icons", "ribbon", f"{name}.svg")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return QPixmap()  # a missing icon must not crash a ribbon rebuild
    raw = raw.replace("currentColor", color)

    renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")))
    image = QImage(px, px, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    return QPixmap.fromImage(image)


def ribbon_icon(name: str, *, on_accent: bool = False, size: int = 20) -> QIcon:
    """
    QIcon for ``resources/icons/ribbon/<name>.svg``.

    `on_accent` picks the white glyph for coloured buttons; the default grey is
    for the plain ribbon. `size` is the pixmap side in logical px -- the icon
    carries a normal and a dimmed (disabled) pixmap so Qt greys it correctly.
    """
    color = COLOR_ON_ACCENT if on_accent else COLOR_ON_DARK
    icon = QIcon()
    icon.addPixmap(_rendered(name, color, size), QIcon.Mode.Normal)
    icon.addPixmap(_rendered(name, COLOR_DISABLED, size), QIcon.Mode.Disabled)
    return icon
