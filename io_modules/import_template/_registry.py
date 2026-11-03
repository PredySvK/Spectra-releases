"""
The Import templates a reader may use right now: the open project's copies.

A reader never looks at the built-in templates or at a library -- only here --
so a project reads the same on a PC that has neither (CONTEXT.md "Import
template"). The session installs the project's copies when a project is
created, opened or gains a template; the scan's worker threads and DataAccessor
only read. The whole table is replaced at once, never edited in place.
"""

import hashlib
import json
import logging
from typing import Dict, Mapping, Optional

from core.import_template import ImportTemplate

_log = logging.getLogger(__name__)

_installed: Dict[str, ImportTemplate] = {}
_keys: Dict[str, str] = {}


def install_project_templates(copies: Mapping[str, dict]) -> None:
    """
    Makes these copies (name -> `ImportTemplate.to_dict()`) the templates readers can use.

    A copy this build cannot read (a project written by a newer version) is
    left out and logged: the files assigned to it then fail one by one as
    unknown templates instead of the whole project failing to open.
    """
    installed: Dict[str, ImportTemplate] = {}
    keys: Dict[str, str] = {}
    for name, data in copies.items():
        try:
            installed[name] = ImportTemplate.from_dict(data)
        except (ValueError, KeyError, TypeError) as error:
            _log.warning("Import template '%s' of the project cannot be read: %s", name, error)
            continue
        digest = hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        keys[name] = f"{name}@{digest}"
    global _installed, _keys
    _installed, _keys = installed, keys


def resolve_installed_template(name: str) -> Optional[ImportTemplate]:
    """The installed template of this name, or None."""
    return _installed.get(name)


def resolve_installed_templates() -> Mapping[str, ImportTemplate]:
    """Every installed template by name (a snapshot; do not edit)."""
    return _installed


def resolve_template_cache_key(name: str) -> str:
    """
    What a scan cache entry is keyed by for this assignment: the name and a
    fingerprint of the copy, so changing the template or the assignment re-reads
    the file. Blank for no assignment or an unknown name.
    """
    return _keys.get(name, "")


def resolve_installed_signature() -> str:
    """One string that changes whenever the installed templates do (for caches of recognition)."""
    return "|".join(sorted(_keys.values()))
