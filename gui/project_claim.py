"""
One open project, one window across processes (#546).

An open project holds a named local server derived from its path; a second
launch (double-click, File > Open) that finds the name taken pings the holder
to raise its window instead of opening the same project twice. The OS drops the
name with the process, so a crash leaves no stale lock. Short local pipe, so it
runs synchronously on the GUI thread.
"""
import hashlib
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_TIMEOUT_MS = 300


def _claim_name(project_path: str) -> str:
    key = os.path.normcase(os.path.abspath(project_path))
    return "spectra-project-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def activate_holder(project_path: str) -> bool:
    """Asks the process holding this project to raise its window; False if nobody holds it."""
    socket = QLocalSocket()
    socket.connectToServer(_claim_name(project_path))
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        return False
    socket.write(b"activate")
    socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class ProjectClaim(QObject):
    """This process's claim on the project it has open (at most one)."""

    activation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: QLocalServer | None = None
        self._name: str | None = None

    def owns(self, project_path: str) -> bool:
        return self._name is not None and self._name == _claim_name(project_path)

    def hold(self, project_path: str | None) -> None:
        """Claims `project_path` (None = nothing open) and drops the previous claim."""
        name = _claim_name(project_path) if project_path else None
        if name == self._name:
            return
        self.release()
        if name is None:
            return
        server = QLocalServer(self)
        if server.listen(name):
            server.newConnection.connect(self._on_connection)
            self._server, self._name = server, name
        else:
            server.deleteLater()  # lost a race for the name; the other window keeps the project

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
        self._server = self._name = None

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            self._server.nextPendingConnection().deleteLater()
            self.activation_requested.emit()
