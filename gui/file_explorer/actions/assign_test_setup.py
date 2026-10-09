# =====================================================================
# FILE: gui/file_explorer/actions/assign_test_setup.py
# =====================================================================
"""
Service Action: filing measurements under a test setup.

A test setup is the hardware configuration or test state a run belongs to --
the level above the measurement that the folder layout on disk usually fails
to express, because the same rig gets measured into whatever folder was
convenient that day. It is the top level of the Data Pool tree.

The assignment is a user decision that exists nowhere else, so it is recorded
against the project's SourceEntry (ProjectSession.set_setup_label) and marks
the project dirty. A file that is not part of the project yet cannot carry one
-- that happens only while no data folder has been registered, and it is
reported rather than silently dropped, exactly as a unit correction is.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtWidgets import QInputDialog

from session.project import apply_setup_label


def execute_assign_test_setup(app_context, explorer_widget, file_paths):
    """
    Asks for a setup name and files every given measurement under it.

    Existing setups are offered first, with a blank entry at the top for
    clearing the assignment, but the field stays editable so inventing a new
    one takes no extra step -- naming a setup is the common case, choosing an
    existing one the exception.
    """
    if not file_paths:
        return

    project = app_context.project_session.project
    choices = [""] + project.setup_labels()

    chosen, ok = QInputDialog.getItem(
        explorer_widget,
        "Assign to Test Setup",
        f"Test setup for {len(file_paths)} measurement(s)\n"
        f"(pick an existing one or type a new name; blank clears it):",
        choices,
        0,
        editable=True,
    )

    if not ok:
        return

    label = chosen.strip()
    assigned, unknown = apply_setup_label(app_context.project_session, file_paths, label)

    explorer_widget.rebuild_tree_view()

    if assigned:
        target = f"'{label}'" if label else "no setup"
        app_context.log(f"POOL: Assigned {assigned} measurement(s) to {target}.")

    if unknown:
        # Same failure mode as a unit correction on an unregistered folder:
        # there is no SourceEntry to hold the decision, so it cannot survive a
        # reload and saying nothing would let it vanish unnoticed.
        app_context.log(
            f"WARNING: {unknown} measurement(s) are not part of the project yet; "
            f"their test setup was not stored."
        )
