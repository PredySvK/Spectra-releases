# core/asset_paths.py
"""
Filesystem locations the app needs but does not treat as project data:
bundled read-only resources (icons, later help content) and the per-user
writable directory for logs and runtime artefacts.

Here in core/ because it is pure path arithmetic -- no Qt, no project model,
no reading or writing (the caller creates the directory it gets back). It is
also the single place that knows PyInstaller's frozen layout (sys._MEIPASS);
main.py used to carry a second copy of that check for the crash log.
"""

import os
import sys
from pathlib import Path

APP_DIRNAME = "Spectra"


def _bundle_root() -> Path:
    # PyInstaller unpacks bundled data under _MEIPASS; in a normal checkout the
    # repo root is this file's grandparent (core/ -> root).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> str:
    """Absolute path to a bundled read-only resource, e.g.
    ``resource_path("resources", "icons", "app_icon.png")``. Works the same in a
    source checkout and inside a frozen .exe."""
    return str(_bundle_root().joinpath(*parts))


def perf_report_dir() -> str:
    """Default folder of the Benchmark reports: ``docs/perf`` in a checkout, a
    per-user folder in a frozen build (the install folder is read-only)."""
    if getattr(sys, "frozen", False):
        return str(user_data_dir() / "perf")
    return str(_bundle_root() / "docs" / "perf")


def user_data_dir() -> Path:
    """Per-user writable directory for logs and runtime artefacts. Never write
    next to the executable -- an installed build lives in Program Files, which
    is read-only. The directory is not guaranteed to exist yet; the caller must
    ``mkdir(parents=True, exist_ok=True)`` before writing."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / APP_DIRNAME
