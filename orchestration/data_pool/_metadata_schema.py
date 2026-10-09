"""
Metadata schema orchestration: storing an edited schema in the project (#424).

Pure functions (no Qt, no AppContext) coordinating the pool update and save.
"""
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from session.data_pool import DataPool

def save_metadata_schema(pool: "DataPool", schema: Dict) -> List[str]:
    """
    Store the edited metadata schema in the project and save it, unless the project holds other unsaved edits
    (ProjectSession.save_edit).

    If saving fails with OSError or ValueError, the pool still carries the
    schema in memory and the error message is returned for the UI to report.

    Returns:
        List of error messages, or an empty list on success.
    """
    session = pool.project_session

    def edit():
        pool.update_project_schema(schema)

    try:
        session.save_edit(edit)
    except (OSError, ValueError) as error:
        return [f"Metadata schema kept in memory but not saved: {error}"]
    return []
