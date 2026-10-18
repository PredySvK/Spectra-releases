"""
A curve read row by row as number pairs: ANSYS (frequency, amplitude) lines and
MASTA (rpm, amplitude) cells.

Whatever cannot be read is counted, never skipped silently: a row
that is not two numbers -- text, a half pair, a blank row with data below it --
is a lost row. Only the blank rows below the last filled one are not; there the
column has simply ended.
"""

from typing import Any, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from core.models import LostPart


class NumberPairs(NamedTuple):
    pairs: List[Tuple[float, float]]
    lost_rows: int


def _parse_number(cell) -> Optional[float]:
    """A cell as a number, or None for a blank or a non-number (a footer, a note)."""
    if isinstance(cell, str):
        cell = cell.strip()
        if "," in cell and "." not in cell:
            cell = cell.replace(",", ".")   # Number stored as text with a decimal comma.
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def _is_blank(cell) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())


def read_number_pairs(rows: Iterable[Sequence[Any]]) -> NumberPairs:
    """The (x, y) pairs of `rows`, each row its cells, and how many rows were lost."""
    pairs = []
    lost_rows = 0
    blank_run = 0
    for cells in rows:
        if all(_is_blank(cell) for cell in cells):
            blank_run += 1
            continue
        lost_rows += blank_run   # A gap: the column goes on below it.
        blank_run = 0
        numbers = [_parse_number(cell) for cell in cells]
        if len(numbers) == 2 and None not in numbers:
            pairs.append((numbers[0], numbers[1]))
        else:
            lost_rows += 1
    return NumberPairs(pairs, lost_rows)


def build_lost_rows_part(dataset: Optional[int], lost_rows: int) -> Optional[LostPart]:
    """The Lost part for `lost_rows` rows of one channel, or None when nothing was lost."""
    if not lost_rows:
        return None
    rows = "1 row that is" if lost_rows == 1 else f"{lost_rows} rows that are"
    return LostPart(dataset, f"{rows} not two numbers")
