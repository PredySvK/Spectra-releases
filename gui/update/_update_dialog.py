"""Show the offered App version and release patch notes."""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout

from io_modules.update import UpdateOffer

_IMG_TAG = re.compile(r'<img\b[^>]*?\bsrc="([^"]+)"[^>]*>', re.IGNORECASE)

# Document margins plus the indent of the bullet the screenshot sits under.
_IMAGE_SIDE_SPACE = 70


def _images_as_markdown(notes: str, loaded: set[str]) -> str:
    """HTML <img> to Markdown; an image that was not downloaded becomes a link opened in the browser."""
    return _IMG_TAG.sub(lambda m: f"{'!' if m[1] in loaded else ''}[Screenshot]({m[1]})", notes)


class _NotesBrowser(QTextBrowser):
    """Patch notes whose screenshots are drawn as wide as the box, so nothing scrolls sideways."""

    def __init__(self, notes: str, images: dict[str, bytes]):
        super().__init__()
        self._images = {url: QImage.fromData(data) for url, data in images.items()}
        self._markdown = _images_as_markdown(notes, {u for u, i in self._images.items() if not i.isNull()})
        self.setOpenExternalLinks(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMarkdown(self._markdown)

    def loadResource(self, resource_type, url):
        image = self._images.get(url.toString())
        if resource_type == QTextDocument.ResourceType.ImageResource and image is not None:
            width = self.viewport().width() - _IMAGE_SIDE_SPACE
            if width > 0:
                return image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
            return image
        return super().loadResource(resource_type, url)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._images:
            self.setMarkdown(self._markdown)


class UpdateDialog(QDialog):
    """Accept to download the Update; reject to keep working."""

    def __init__(self, offer: UpdateOffer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spectra Update")
        self.resize(840, 630)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Spectra {offer.app_version} is available."))
        layout.addWidget(_NotesBrowser(offer.notes or "No patch notes provided.", offer.images))
        buttons = QDialogButtonBox()
        buttons.addButton("Update now", QDialogButtonBox.ButtonRole.AcceptRole)
        later = buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        later.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
