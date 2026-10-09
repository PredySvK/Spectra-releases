# =====================================================================
# FILE: gui/handlers/selection_drop.py
# =====================================================================
"""
Draws a Selection (#465): a double click on it in the Selections tab or a drop
on a graph / the Home Workspace.

The Selection is expanded once, on the job runner, into the same channel drop
descriptors a Data Pool drag carries; they then go through the one drop router
(`Workspace.route_channel_drop`) or open a new tab, so mixed types are settled
where they always were. Nothing here keeps a link to the Selection: editing it
later leaves the graph as it is.
"""
from PySide6.QtWidgets import QMessageBox

from core.jobs import job_step
from io_modules.project_store import read_root_directories
from selection.measurement_selection import build_channel_drop_descriptors, resolve
from selection.source_facets import all_pool_sources

__all__ = ["SelectionDropHandler", "CONFIRM_CHANNEL_COUNT"]

# More channels than this ask before anything is drawn.
CONFIRM_CHANNEL_COUNT = 50

_SLOT = "selection_drop.expand"


def _expand(selection, sources, schema, session, runs) -> list:
    """The Selection's channels as drop descriptors. Reads the disk (root folders), so off the GUI thread."""
    by_path = session.sources_by_path(read_root_directories(session.path, session.project.data_roots))
    files = {}
    for run in runs:
        entry = session.entry_for_run(run, by_path)
        if entry is not None:
            files[entry.id] = (run.file_path, run.file_name)
    return build_channel_drop_descriptors(resolve(selection, sources, schema), files)


class SelectionDropHandler:
    def __init__(self, app_context, job_runner, workspace, confirm=None):
        self._context = app_context
        self._job_runner = job_runner
        self._workspace = workspace
        self._confirm = confirm or self._ask

    def draw(self, name: str, dock=None) -> None:
        """Expand Selection `name` and draw it on `dock`, or open a new tab when `dock` is None."""
        context = self._context
        session = context.project_session
        selection = session.find_selection(name)
        if selection is None:
            return
        self._job_runner.submit(
            f"Expand Selection '{name}'",
            [job_step("Expand", _expand, selection, all_pool_sources(session.project),
                      context.pool.schema().master, session, list(context.pool.loaded_runs))],
            lane="interactive", slot_key=_SLOT, quiet=True,
            on_step=lambda descriptors, _index: self._land(name, dock, descriptors),
        )

    def _land(self, name: str, dock, descriptors: list) -> None:
        context = self._context
        if not descriptors:
            context.log(f"WARNING: Selection '{name}' has no channel in the Data Pool to draw.")
            return
        if len(descriptors) > CONFIRM_CHANNEL_COUNT and not self._confirm(name, len(descriptors)):
            return
        if dock is None:
            from gui.file_explorer.actions.channel_drop import resolve_dropped_channels
            self._workspace.open_channels_tab(
                resolve_dropped_channels(descriptors, context), what=f"Selection '{name}'")
        else:
            self._workspace.route_channel_drop(
                dock, descriptors, batch_label=f"Order tracking — Selection '{name}'")

    @staticmethod
    def _ask(name: str, count: int) -> bool:
        return QMessageBox.question(
            None, "Draw Selection", f"Selection '{name}' has {count} channels. Draw them all?",
        ) == QMessageBox.Yes
