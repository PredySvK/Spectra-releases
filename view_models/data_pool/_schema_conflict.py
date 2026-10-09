# =====================================================================
# FILE: view_models/data_pool/_schema_conflict.py
# =====================================================================
"""
Formatting schema conflict descriptions for the Data Pool view model.
"""

from __future__ import annotations

import os
from typing import Any

LAYER_CONFLICT = "layer"


def describe_schema_conflict(conflict: Any) -> str:
    """Names the folders by their own name rather than their full path."""
    parts = ", ".join(
        f"{os.path.basename(where.rstrip(os.sep)) or where}: {what}"
        for where, what in conflict.detail.items()
    )
    if conflict.kind == LAYER_CONFLICT:
        return (f"Spreadsheet column in one folder, measurement-file header field in "
                f"another \u2014 {parts}")
    return f"Different kinds of value per folder \u2014 {parts}"
