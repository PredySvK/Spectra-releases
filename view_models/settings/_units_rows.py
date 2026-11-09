"""The preview of a Units row, computed without Qt."""

from view_models.display_prefix import resolve_units_preview

from ._draft import SettingsDraft
from ._pages import UnitsRow


def resolve_units_row_preview(row: UnitsRow, draft: SettingsDraft) -> str:
    """A sample number written the way ``row`` shows it with the draft's unit, prefix and decimals."""
    unit = draft.value(row.unit_key) if row.unit_key else row.preview_unit
    return resolve_units_preview(
        unit, row.label.lower(), draft.value(row.prefix_key), draft.value(row.decimals_key))
