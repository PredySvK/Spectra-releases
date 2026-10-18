"""
view_models.result_sets -- How a typed result-set name is previewed, without Qt.

Architecture:
- View-model floor (Floor 3): What does the user's typed name become on disk, and
  how should the dialog describe that?
- Name preview: build_label_preview classifies a typed name as empty / unusable /
  changed / unchanged and carries the sanitised folder name.

What does NOT belong here: what to do with an unusable name (Compute blocks, Save
Spec falls back to an auto-name -- the callers' policy in gui/), the sanitising rule
itself (io_modules.result_cache), or Qt widgets (gui/).
"""

from ._label_preview import LabelKind, LabelPreview, build_label_preview

__all__ = [
    "LabelKind",
    "LabelPreview",
    "build_label_preview",
]
