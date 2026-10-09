# =====================================================================
# FILE: gui/file_explorer/actions/locate_missing_file.py
# =====================================================================
"""
Service Action: pointing the project at a measurement that has moved.

A project stores where its data was, relatively and absolutely, which covers
the project being copied somewhere else. What it cannot cover is the data
itself being moved, renamed or handed over on a stick that mounted as another
drive letter. Then the file is simply not where the project says, and the only
one who knows where it went is the user.

So the pool marks it rather than hiding it, and this is how the user answers.
The project entry is kept and re-pointed (ProjectSession.relocate_source) --
its id is what every computed result set refers to, and its metadata and unit
corrections exist nowhere else.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from io_modules.measurement_files import SUPPORTED_EXTENSIONS

LOCATE_FILTER = (
    f"Measurement files ({' '.join(SUPPORTED_EXTENSIONS)});;All Files (*.*)"
)


def execute_locate_missing_file(app_context, explorer_widget, run_index, data_pool=None) -> bool:
    """Asks where a missing measurement went and re-points the project at it."""
    session = app_context.project_session
    entry = session.source_for_path(run_index.file_path)

    if entry is None:
        QMessageBox.information(
            explorer_widget, "Nothing to re-point",
            f"'{run_index.file_name}' is not part of the project, so there is no "
            f"stored location to correct. Add its folder to the Data Pool instead.",
        )
        return False

    chosen, _ = QFileDialog.getOpenFileName(
        explorer_widget,
        f"Locate '{run_index.file_name}'",
        _starting_directory(app_context, run_index),
        LOCATE_FILTER,
    )
    if not chosen:
        return False

    if not session.relocate_source(entry.id, chosen):
        QMessageBox.warning(
            explorer_widget, "Could not re-point the file",
            f"'{os.path.basename(chosen)}' could not be used.\n\n"
            f"It is either unreadable, or the project already has an entry for it -- "
            f"one measurement cannot have two.",
        )
        return False

    app_context.log(f"PROJECT: '{run_index.file_name}' re-pointed at {chosen}.")

    # The pool still holds a run built from the old path, so the folder it now
    # lives in is re-read; that is also what pulls in a whole folder's worth of
    # files if the data moved wholesale.
    app_context.pool.remove_pool_runs([run_index.file_path])

    if data_pool is not None:
        data_pool.add_paths([chosen])
    else:
        app_context.add_pool_directory(os.path.dirname(chosen), only_files={chosen})
        explorer_widget.rebuild_tree_view()

    return True


def _starting_directory(app_context, run_index) -> str:
    """
    Opens somewhere useful: a folder already in the pool, then the last one
    browsed, then the user's home. The file's own recorded folder is skipped
    on purpose -- it is the one place the file is known not to be.
    """
    for directory in app_context.pool.pool_directories:
        if os.path.isdir(directory):
            return directory

    if app_context.active_directory and os.path.isdir(app_context.active_directory):
        return app_context.active_directory

    return os.path.expanduser("~")
