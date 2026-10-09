# =====================================================================
# FILE: view_models/evaluation/_orders.py
# =====================================================================
"""
Order input parsing for the Evaluation view model.
"""

from __future__ import annotations

import re
from typing import List, Optional

_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)$")


def parse_orders_text(text: str) -> Optional[List[float]]:
    """Parse a delimited list of orders.

    Decimal separator must be a dot ('.').
    Orders can be separated by commas (',') or semicolons (';').

    Returns:
        - [] if text is empty or only whitespace.
        - List of positive floats if all entries are valid.
        - None if any entry is invalid (unparseable text, negative/zero order,
          missing entry between delimiters or trailing/leading delimiter).
    """
    stripped = text.strip()
    if not stripped:
        return []

    pieces = re.split(r"[,;]", stripped)
    orders: List[float] = []
    for piece in pieces:
        p = piece.strip()
        if not p or not _NUMBER_RE.match(p):
            return None
        try:
            val = float(p)
        except ValueError:
            return None
        if val <= 0.0:
            return None
        orders.append(val)
    return orders
