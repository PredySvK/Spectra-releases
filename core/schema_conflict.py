# =====================================================================
# FILE: core/schema_conflict.py
# =====================================================================
"""
A Schema conflict: one field name that two data folders disagree about.

Pure data, shared by the session that detects conflicts while merging the
pool's schema and the view model that describes them to the user. It lives
here because those two sit on the same floor and must not import each other.
"""

from dataclasses import dataclass, field
from typing import Dict

# The same field name meaning two different things in two data folders. Both
# kinds are merged rather than refused -- a union that loses a column would
# hide data the user just added -- but the user is told, because a facet built
# out of a collision reads as one field and behaves like two.
LAYER_CONFLICT = "layer"        # spreadsheet column here, measurement-file fact there
TYPE_CONFLICT = "value_type"    # numbers here, free text there


@dataclass
class SchemaConflict:
    """
    One field name that two data folders disagree about.

    `detail` maps each folder to what it says about the field, so the dialog
    can name the folders rather than asking the user to guess which of their
    Excel sheets is the odd one out.
    """
    key: str
    kind: str
    detail: Dict[str, str] = field(default_factory=dict)
