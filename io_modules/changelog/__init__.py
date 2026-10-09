"""
io_modules.changelog -- Reads the released versions out of ``CHANGELOG.md`` (Floor 4).

The file is bundled next to the app (packaging/spectra.spec); a small local read,
so synchronous. ``## Unreleased`` is not a release and is skipped.

What does NOT belong here: showing it (gui/welcome).
"""

from ._reading import Change, ChangelogEntry, read_changelog

__all__ = ["Change", "ChangelogEntry", "read_changelog"]
