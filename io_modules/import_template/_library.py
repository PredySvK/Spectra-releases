"""
The user's library of Import templates: a folder of JSON template files that
can be copied to colleagues (CONTEXT.md "Import template").

Writing or reading one template file is a short, user-started write or read of
a small file, so it runs on the GUI thread (§1.137). A reader never looks here
-- only at the open project's copies (_registry.py).
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional

from core.asset_paths import user_data_dir
from core.import_template import ImportTemplate

_log = logging.getLogger(__name__)

_UNSAFE_FILE_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def resolve_library_folder() -> Path:
    """The folder the user's library lives in."""
    return user_data_dir() / "import_templates"


def resolve_library_file(name: str, folder: Optional[Path] = None) -> Path:
    """The file the template of this name is kept in."""
    stem = _UNSAFE_FILE_CHARACTERS.sub("_", name).strip(" .") or "template"
    return Path(folder or resolve_library_folder()) / f"{stem}.json"


def write_template_file(template: ImportTemplate, path: Path) -> Path:
    """Writes the template to this file (export, library save); returns the file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(template.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return path


def read_template_file(path: Path) -> ImportTemplate:
    """
    The template in this file. Raises ValueError with a message for the user when
    the file is no template or is of a format version this build does not read --
    never a half-read template.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("it holds no template")
        return ImportTemplate.from_dict(data)
    except OSError as error:
        raise ValueError(f"'{path.name}' cannot be read: {error}") from error
    except (KeyError, TypeError) as error:
        raise ValueError(f"'{path.name}' is not an Import template ({error!r}).") from error
    except ValueError as error:
        raise ValueError(f"'{path.name}' cannot be used: {error}") from error


def write_library_template(template: ImportTemplate, folder: Optional[Path] = None) -> Path:
    """Saves the template into the library, replacing one of the same name; returns its file."""
    return write_template_file(template, resolve_library_file(template.name, folder))


def write_library_template_from_file(source: Path, folder: Optional[Path] = None,
                            builtin_names: Iterable[str] = ()) -> ImportTemplate:
    """
    Copies the template file `source` into the library under the template's name
    (replacing one of that name). ValueError when the file cannot be used or the
    name is a built-in template's -- a built-in is never shadowed.
    """
    template = read_template_file(source)
    if template.name.strip().lower() in {name.lower() for name in builtin_names}:
        raise ValueError(f"'{template.name}' is the name of a built-in template; rename the template in the file.")
    write_library_template(template, folder)
    return template


def delete_library_template(name: str, folder: Optional[Path] = None) -> bool:
    """
    Removes the library's template of this name -- only the library's file; a
    project's own copy is untouched. False when the library has none.
    """
    folder = Path(folder or resolve_library_folder())
    candidates = [resolve_library_file(name, folder)]
    candidates += [path for path in sorted(folder.glob("*.json")) if path not in candidates]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            found = read_template_file(path)
        except ValueError:
            continue
        if found.name == name:
            path.unlink()
            return True
    return False


def read_library_templates(folder: Optional[Path] = None) -> List[ImportTemplate]:
    """
    The library's templates, by name. A file this build cannot read is left out
    and logged, so one broken file does not hide the others.
    """
    folder = Path(folder or resolve_library_folder())
    if not folder.is_dir():
        return []
    templates = []
    for path in sorted(folder.glob("*.json")):
        try:
            templates.append(ImportTemplate.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError, TypeError) as error:
            _log.warning("Import template file '%s' cannot be read: %s", path, error)
    return sorted(templates, key=lambda template: template.name.lower())
