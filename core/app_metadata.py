# core/app_metadata.py
"""
Product identity constants: the name shown to the user and the version string.

Here in core/ because it is pure data with no I/O and no Qt -- the window title,
the docs window and the startup log all read the same two names from one place.
The QSettings organisation/application keys are deliberately NOT derived from
this: renaming those would orphan every user's saved layout and preferences.
"""

APP_NAME = "Spectra"
# Registry location of the user settings: HKCU\Software\Spectra\{Root,Shared}.
# Frozen strings -- changing them orphans every user's saved preferences.
SETTINGS_ORGANIZATION = "Spectra"
SETTINGS_ROOT = "Root"
SETTINGS_SHARED = "Shared"
# 0.MINOR.PATCH while in alpha; the release tag is {APP_VERSION}, no "v" (ADR §1.144).
APP_VERSION = "0.1.2"
# Public repository holding only the installers and patch notes (ADR §1.140).
RELEASES_REPO = "PredySvK/Spectra-releases"
# Windows taskbar identity. No version in it: a new ID on every Update would
# detach the user's pinned taskbar entry. Installer shortcuts set the same ID,
# so the string itself is frozen too (".NVH" is legacy, not meaningful).
APP_USER_MODEL_ID = f"{APP_NAME}.NVH"

APP_TITLE = f"{APP_NAME} {APP_VERSION}"


def window_title(project_name=None):
    """The exact string shown in the OS title bar -- and, later, in the
    frameless custom bar. One builder so the two never drift apart."""
    if project_name:
        return f"{APP_TITLE} - {project_name}"
    return APP_TITLE
