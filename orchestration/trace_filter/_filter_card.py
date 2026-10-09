"""
Filter card orchestration: persisting updated filter cards to the project session.

Pure functions (no Qt, no AppContext) coordinating project updates and saves.
"""
from typing import List, TYPE_CHECKING

from core.filter_card_config import FilterCardConfig

if TYPE_CHECKING:
    from session.project import ProjectSession


def save_filter_card(session: "ProjectSession", card: FilterCardConfig) -> List[str]:
    """
    Store the updated filter card in the project and save it, unless the
    project holds other unsaved edits (ProjectSession.save_edit, #337).

    If saving fails with OSError or ValueError, the session still retains the card
    in memory and the error message is returned for the UI to report.

    Returns:
        List of error messages, or an empty list on success.
    """
    try:
        session.save_edit(lambda: session.project.put_filter_card(card))
    except (OSError, ValueError) as error:
        return [f"Filter configuration kept in memory but not saved: {error}"]
    return []
