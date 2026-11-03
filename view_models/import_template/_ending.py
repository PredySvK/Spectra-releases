"""
How the import wizard ends: which actions it offers, why one cannot be used yet, the
template it opens on, and how a finished one saved.

Library: Save into the library. Misfit: Overwrite the template loaded (same name) or
Save as new into the library. Project: apply the edit to the project's copy (same
name). Overwrite and Apply write nothing: the caller replaces the project's copy
after its summary. Writing a library file is the caller's, on the GUI thread (§1.137).
"""

import dataclasses
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from core.import_template import ImportTemplate
from io_modules.import_template import read_builtin_templates
from view_models.import_template._preview import WizardPreview
from view_models.import_template._wizard import ImportTemplateWizard, resolve_library_save_problem

ENDING_LIBRARY = "library"
ENDING_MISFIT = "misfit"
ENDING_PROJECT = "project"
SAVED_OVERWRITE = "overwrite"
SAVED_NEW = "new"

ACTION_SAVE = "save"
ACTION_OVERWRITE = "overwrite"
ACTION_SAVE_AS_NEW = "save_as_new"

_ACTIONS = {
    ENDING_LIBRARY: (ACTION_SAVE,),
    ENDING_MISFIT: (ACTION_OVERWRITE, ACTION_SAVE_AS_NEW),
    ENDING_PROJECT: (ACTION_OVERWRITE,),
}


@dataclass(frozen=True)
class WizardEnding:
    """
    The rules of one way to end the wizard. `builtin_names` are the names the
    library refuses (the shipped templates' when None); `taken_names` are the
    project's templates, which Save as new must not reuse.
    """

    kind: str = ENDING_LIBRARY
    builtin_names: Optional[Tuple[str, ...]] = None
    taken_names: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in _ACTIONS:
            raise ValueError(f"'{self.kind}' is not a wizard ending; expected one of {', '.join(_ACTIONS)}.")
        if self.builtin_names is not None:
            object.__setattr__(self, "builtin_names", tuple(self.builtin_names))
        object.__setattr__(self, "taken_names", tuple(self.taken_names))

    def resolve_actions(self) -> Tuple[str, ...]:
        """The actions this ending offers, in button order."""
        return _ACTIONS[self.kind]

    def edits_builtin(self, template: Optional[ImportTemplate]) -> bool:
        """A built-in template is read-only: edited in the library, it can only be saved under another name."""
        if self.kind != ENDING_LIBRARY or template is None:
            return False
        return template.name.lower() in {name.lower() for name in self._resolve_builtin_names()}

    def resolve_opening_template(self, template: Optional[ImportTemplate]) -> Optional[ImportTemplate]:
        """The template the wizard opens on: a built-in one under a copy's name, any other as it is."""
        if self.edits_builtin(template):
            return dataclasses.replace(template, name=f"{template.name} (copy)")
        return template

    def resolve_problem(self, action: str, wizard: ImportTemplateWizard, preview: WizardPreview) -> str:
        """Why `action` cannot be used with the template as it stands, blank when it can."""
        if action not in self.resolve_actions():
            return f"This wizard does not offer '{action}'."
        if action == ACTION_OVERWRITE:
            return self._resolve_overwrite_problem(wizard, preview)
        name = wizard.template.name.strip()
        if action == ACTION_SAVE_AS_NEW:
            taken = {other.strip().lower() for other in self.taken_names} | {wizard.original_name.strip().lower()}
            if name and name.lower() in taken:
                return f"A template '{name}' exists already; save the new one under another name."
        return (resolve_library_save_problem(name, self.builtin_names)
                or wizard.resolve_fit_problem(preview))

    def resolve_saved_as(self, action: str) -> str:
        """How a wizard that ended in `action` saved: `SAVED_OVERWRITE` wrote nowhere, `SAVED_NEW` is in the library."""
        return SAVED_OVERWRITE if action == ACTION_OVERWRITE else SAVED_NEW

    def _resolve_overwrite_problem(self, wizard: ImportTemplateWizard, preview: WizardPreview) -> str:
        if wizard.template.name.strip() != wizard.original_name.strip():
            return (f"Overwrite keeps the name '{wizard.original_name}'; "
                    "under another name, save it as a new template.")
        return wizard.resolve_fit_problem(preview)

    def _resolve_builtin_names(self) -> Iterable[str]:
        if self.builtin_names is not None:
            return self.builtin_names
        return [template.name for template in read_builtin_templates()]
