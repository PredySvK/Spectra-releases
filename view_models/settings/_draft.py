"""The draft: edited values that take effect only on Apply."""

from typing import Any

from ._pages import SETTINGS_IMMEDIATE_KEYS, SETTINGS_PROJECT_KEYS, SettingsPage


class SettingsDraft:
    """Last applied values plus the user's unapplied edits."""

    def __init__(self, values: dict[str, Any]):
        self._applied = dict(values)
        self._edited = dict(values)

    def value(self, key: str) -> Any:
        return self._edited[key]

    def set_value(self, key: str, value: Any) -> None:
        self._edited[key] = value

    @property
    def dirty_keys(self) -> set[str]:
        return {key for key, value in self._edited.items() if value != self._applied[key]}

    @property
    def is_dirty(self) -> bool:
        return bool(self.dirty_keys)

    def page_is_dirty(self, page: SettingsPage) -> bool:
        return any(field.key in self.dirty_keys for field in page.fields)

    def apply(self) -> dict[str, Any]:
        """The changed values, which from now on are the applied ones."""
        changed = {key: self._edited[key] for key in self.dirty_keys}
        self._applied.update(changed)
        return changed

    def revert(self) -> dict[str, Any]:
        """Return the immediate values to restore, then drop all edits."""
        restore = {key: self._applied[key] for key in self.dirty_keys & SETTINGS_IMMEDIATE_KEYS}
        self._edited = dict(self._applied)
        return restore

    def adopt_external_values(self, values: dict[str, Any]) -> None:
        """Follow external changes in clean fields; other edits survive and Revert uses the latest values.

        An immediate field is a live preview of the panel itself, so a panel changed
        outside the window (a dock closed by the mouse) wins over its unapplied edit.
        """
        dirty = self.dirty_keys
        for key, value in values.items():
            if key in dirty and key in SETTINGS_IMMEDIATE_KEYS:
                # Our own preview's echo must not replace the restore point.
                self._edited[key] = value
                continue
            if key not in dirty:
                self._edited[key] = value
            self._applied[key] = value

    def adopt_project_values(self, values: dict[str, Any]) -> None:
        """Another project was opened: its values replace the project fields, unapplied edits included."""
        for key in SETTINGS_PROJECT_KEYS & values.keys():
            self._applied[key] = self._edited[key] = values[key]
