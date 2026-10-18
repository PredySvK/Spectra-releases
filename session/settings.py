"""
settings -- the one Settings store: the application settings' only read and write path.

`SettingsStore` holds the value of every key in `core.settings`, writes a change
to the `SettingsStorage` it was given and tells its subscribers what actually
changed. Qt-free: the QSettings storage lives in app_context.py,
tests use an in-memory one.

What does not belong here: labels and pages (view_models/settings), what a
change sets off in the open window (gui/handlers/window_settings.py).
"""

from typing import Any, Callable, Protocol

from core.settings import SETTING_DEFINITIONS, resolve_setting_value

__all__ = ["SettingsStorage", "SettingsStore"]


class SettingsStorage(Protocol):
    """Where the values are kept; ``read`` gives None for an absent key."""

    def read(self, key: str) -> object | None: ...

    def write(self, key: str, value: object) -> None: ...

    def remove(self, key: str) -> None: ...


class SettingsStore:
    """Every application setting, coerced; read once from the storage, then kept in step with it."""

    def __init__(self, storage: SettingsStorage):
        self.storage = storage
        self._values = {key: resolve_setting_value(key, storage.read(key)) for key in SETTING_DEFINITIONS}
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []

    def value(self, key: str) -> Any:
        return self._values[key]

    def apply(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Write the values that differ after coercion and return them; an unknown key raises KeyError."""
        coerced = {key: resolve_setting_value(key, value) for key, value in changes.items()}
        changed = {key: value for key, value in coerced.items() if value != self._values[key]}
        for key, value in changed.items():
            self.storage.write(key, value)
        self._values.update(changed)
        self._notify(changed)
        return changed

    def reset(self) -> dict[str, Any]:
        """Remove every setting from the storage; all of them are reported, now at their defaults."""
        for key in SETTING_DEFINITIONS:
            self.storage.remove(key)
        self._values = {key: definition.default for key, definition in SETTING_DEFINITIONS.items()}
        changed = dict(self._values)
        self._notify(changed)
        return changed

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Call ``callback`` with the changed values after every apply or reset that changed any."""
        self._subscribers.append(callback)

    def _notify(self, changed: dict[str, Any]) -> None:
        if changed:
            for callback in self._subscribers:
                callback(changed)
