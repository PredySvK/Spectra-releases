"""Download and launch the per-user Update installer (ADR §1.140)."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.request import urlopen

from core.jobs import CancelToken
from ._download_file import open_download_file
from ._request import build_request


def is_installed_windows_app() -> bool:
    """True only in the frozen Windows Spectra, the one place an in-app Update can run."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def write_empty_installer() -> Path:
    """Reserve a unique executable in the user's temporary folder.

    Runs synchronously on the GUI thread: creating one empty temp file the user
    just asked for takes milliseconds (an exception to the "must not freeze" rule).
    """
    descriptor, name = tempfile.mkstemp(prefix="Spectra-update-", suffix=".exe")
    os.close(descriptor)
    return Path(name)


def remove_installer(installer: Path) -> None:
    """Remove a failed, cancelled or declined temporary Update."""
    installer.unlink(missing_ok=True)


def write_installer(url: str, destination: Path, *, cancel_token: CancelToken,
                   progress_fn: Callable[[int, int], None]) -> Path:
    """Stream the installer; the caller removes ``destination`` on any failure."""
    cancel_token.raise_if_cancelled()
    request = build_request(url)
    with open_download_file(destination) as output, urlopen(request, timeout=10) as response:
        total = int(response.headers.get("Content-Length", "0"))
        done = 0
        progress_fn(done, total)
        while True:
            cancel_token.raise_if_cancelled()
            chunk = response.read(64 * 1024)
            cancel_token.raise_if_cancelled()
            if not chunk:
                break
            output.write(chunk)
            done += len(chunk)
            progress_fn(done, total)
        if done == 0 or (total and done != total):
            raise OSError("Incomplete Update download")
    cancel_token.raise_if_cancelled()
    return destination


def run_installer(installer: Path) -> None:
    """Detach a silent install into the running executable's existing folder.

    Blocks until the process is created, which an antimalware scan of the fresh
    download can stretch to seconds: call it through a helper that keeps the
    GUI pumping events (main.run_keeping_gui_alive).
    """
    if not is_installed_windows_app():
        raise OSError("In-app Update requires an installed Windows Spectra")
    subprocess.Popen(
        [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
         "/RESTARTAPP=1", f"/DIR={Path(sys.executable).parent}"],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
