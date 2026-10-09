# =====================================================================
# FILE: gui/file_explorer/pool_watcher.py
# =====================================================================
"""
Noticing that a folder in the pool changed on disk.

A measurement campaign writes files while the application is open. Without
this the user has to know to press refresh, and the one thing they reliably
do not know is that a file they cannot see has appeared.

Two things make a naive QFileSystemWatcher useless here, and both are handled
below rather than left to surprise someone later:

  - The scan cache lives under the project now (ADR §1.22), not in the data
    folder, so a refresh writing it no longer touches anything watched here.
    The watcher still compares what the measurement files look like rather than
    whether something in the folder moved: any other stray file dropped next to
    the data (an old .nvh_workspace_cache.json, an editor's temp file) must not
    be able to wake it either.
  - A file being copied in arrives as a burst of change notifications, and
    half of them describe a file that is still growing. The burst is collected
    and acted on once it goes quiet.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer

from io_modules.measurement_files import canonical_path, folder_fingerprint

# How long a folder has to stay quiet before it is re-read. Long enough to sit
# out a multi-file copy, short enough that a finished measurement shows up
# while the user is still looking at the screen.
SETTLE_MS = 1200


class PoolWatcher(QObject):
    """Watches the pool's folders and re-reads the ones that really changed."""

    def __init__(self, app_context, data_pool, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.data_pool = data_pool

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)

        self._fingerprints: dict = {}
        self._pending: set = set()
        self._refreshing: set = set()

        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._refresh_settled)

    def sync(self):
        """
        Brings the watched set in line with the pool.

        Called after anything that changes which folders are in the pool. A
        folder that is watched but no longer in the pool would keep waking the
        application up about data it is not showing.
        """
        wanted = {directory for directory in self.app_context.pool.pool_directories
                  if os.path.isdir(directory)}
        watched = set(self._watcher.directories())

        gone = watched - wanted
        if gone:
            self._watcher.removePaths(list(gone))
        for directory in gone:
            self._fingerprints.pop(canonical_path(directory), None)
            self._pending.discard(directory)
            self._refreshing.discard(directory)

        new = wanted - watched
        if new:
            self._watcher.addPaths(list(new))

        # Any refresh that was superseded or interrupted by another ingest
        # is returned to pending now that the runner has gone quiet.
        if self._refreshing and not self.data_pool.is_running:
            self._pending.update(self._refreshing)
            self._refreshing.clear()

        # The fingerprint is taken now, for every folder new to the watch, so
        # the first notification has something to compare against. Without it
        # the first change of any kind would look like a real one. Guarded by
        # an explicit membership test rather than setdefault: setdefault still
        # evaluates folder_fingerprint() for folders already known, re-hashing
        # the whole pool on every sync().
        #
        # Folders that are waiting for a re-read or currently in flight must not
        # be photographed: their disk state is ahead of what is in the pool,
        # and snapshotting it now would make the pending change look like it
        # had already been read (issue #388).
        deferred = {canonical_path(directory) for directory in self._pending | self._refreshing}
        for directory in wanted:
            key = canonical_path(directory)
            if key not in self._fingerprints and key not in deferred:
                self._fingerprints[key] = folder_fingerprint(directory)

        if self._pending and not self.data_pool.is_running:
            self._settle.start()

    def stop(self):
        """Drops every watch. Used when the window closes."""
        self._settle.stop()
        directories = self._watcher.directories()
        if directories:
            self._watcher.removePaths(directories)
        self._fingerprints.clear()
        self._pending.clear()
        self._refreshing.clear()

    # ---- reacting -----------------------------------------------------

    def _on_directory_changed(self, directory: str):
        self._pending.add(directory)
        self._settle.start()

    def _refresh_settled(self):
        """Re-reads the folders whose measurement files actually differ now."""
        # An ingest the user started outranks this. Superseding it would cancel
        # a folder they are waiting for, to react to a change they have not
        # noticed yet; the pending folders are looked at again once things are quiet.
        if self.data_pool.is_running:
            self._settle.start()
            return

        pending, self._pending = self._pending, set()

        changed = []
        for directory in pending:
            if not os.path.isdir(directory):
                continue
            key = canonical_path(directory)
            fingerprint = folder_fingerprint(directory)
            if fingerprint == self._fingerprints.get(key):
                continue
            changed.append(directory)

        if not changed:
            return

        self.app_context.log(
            f"POOL: {len(changed)} folder(s) changed on disk -- re-reading."
        )
        self._refreshing.update(changed)
        self.data_pool.refresh_directories(
            changed, quiet=True,
            on_finished=lambda outcome: self._on_refresh_finished(outcome, changed),
        )

    def _on_refresh_finished(self, outcome, directories):
        if not outcome.completed:
            self._pending.update(directories)
            self._refreshing.difference_update(directories)
            if not self.data_pool.is_running:
                self._settle.start()
            return

        for directory in directories:
            self._refreshing.discard(directory)
            if os.path.isdir(directory):
                key = canonical_path(directory)
                self._fingerprints[key] = folder_fingerprint(directory)
