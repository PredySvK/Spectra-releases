"""
What one ingest run is asked to do (`IngestRequest`) and the questions the
shell answers for it (`IngestAskers`).

The kind of run is the one concept every difference between runs hangs off
(#903): an **Add** reads a selection and is the only kind that may ask about
Test setups; a **Refresh** re-reads folders already in the pool and is the only
kind that admits files the project does not know yet (the plan's `Admission`,
#1006); a **Template edit** replaces the project's copy of an Import template
and re-reads only its files, asking nothing. Callers say which kind they want;
they never set the flags that follow from it.

All internal documentation strings and variable labels are standardly written
in English.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence, Tuple

from core.import_template import ImportTemplate
from orchestration.data_pool._source_amplitude import SourceAmplitudeAsker
from orchestration.data_pool._template_assignment import ImportTemplateAsker, Misfit


class IngestKind(Enum):
    """The kind of an ingest run; see the module docstring for what each one means."""

    ADD = "add"
    REFRESH = "refresh"
    TEMPLATE_EDIT = "template_edit"


@dataclass(frozen=True)
class IngestRequest:
    """
    One ingest run, as the shell asks for it. Built through `add`, `refresh`
    or `template_edit`, never field by field.

    `paths` is the selection of an Add, or the folders of a Refresh.
    `import_templates` are the templates an Add reads with. `replacements` are
    templates that replace the project's copy of their name when the run starts
    reading -- the edit of a Template edit, or a confirmed edit an Add of
    misfits brings along; the files the replaced copies read are re-read in the
    same run. `offer_to_library` is a template the shell is offered to save
    into the library once the run has completed.
    """

    kind: IngestKind
    paths: Tuple[str, ...] = ()
    import_templates: Tuple[ImportTemplate, ...] = ()
    replacements: Tuple[ImportTemplate, ...] = ()
    ask_for_setup: bool = False
    quiet: bool = False
    offer_to_library: Optional[ImportTemplate] = None

    @classmethod
    def add(cls, paths: Sequence[str], *, import_templates: Sequence[ImportTemplate] = (),
            replacements: Sequence[ImportTemplate] = (), ask_for_setup: bool = False,
            quiet: bool = False, offer_to_library: Optional[ImportTemplate] = None) -> "IngestRequest":
        """An Add of folders and/or measurements, read with `import_templates` where they fit."""
        return cls(IngestKind.ADD, tuple(paths), tuple(import_templates), tuple(replacements),
                   ask_for_setup=ask_for_setup, quiet=quiet, offer_to_library=offer_to_library)

    @classmethod
    def refresh(cls, directories: Sequence[str], *, quiet: bool = False) -> "IngestRequest":
        """A re-read of folders already in the pool."""
        return cls(IngestKind.REFRESH, tuple(directory for directory in directories if directory), quiet=quiet)

    @classmethod
    def template_edit(cls, template: ImportTemplate, *, quiet: bool = False,
                      offer_to_library: Optional[ImportTemplate] = None) -> "IngestRequest":
        """A confirmed edit of the project's copy of `template`'s name: replace it, re-read its files."""
        return cls(IngestKind.TEMPLATE_EDIT, replacements=(template,), quiet=quiet,
                   offer_to_library=offer_to_library)

    @property
    def asks(self) -> bool:
        """Whether the run asks the which-template and Source amplitude questions (a Template edit never does)."""
        return self.kind is not IngestKind.TEMPLATE_EDIT


@dataclass(frozen=True)
class EditedTemplate:
    """What the import wizard ended with: the template, and whether it was saved as a new one."""

    template: ImportTemplate
    saved_as_new: bool = False


# The consequence summary of replacing a copy by a library template -> True to
# replace, False to keep the copy, None to cancel the Add.
LibraryChangeAsker = Callable[[object], Optional[bool]]
# (project's copy, sample file, opened from the misfit report, names taken) ->
# what the wizard ended with, None when it was closed without saving.
TemplateEditor = Callable[[ImportTemplate, str, bool, Tuple[str, ...]], Optional[EditedTemplate]]
# The consequence summary of an edit -> whether the user confirmed it.
TemplateEditConfirmer = Callable[[object], bool]
# (misfits, whether each can be fixed in a project template) -> the misfit to fix, None for none.
MisfitChooser = Callable[[Tuple[Misfit, ...], Tuple[bool, ...]], Optional[Misfit]]


@dataclass(frozen=True)
class IngestAskers:
    """
    The questions a run and its follow-up may put to the user, one callable
    each; a missing one is a question nobody asks. Without `source_amplitude`
    and `import_template` a run asks nothing (opening a project); without
    `library_change` an Add keeps the project's copy of a changed template.
    """

    source_amplitude: Optional[SourceAmplitudeAsker] = None
    import_template: Optional[ImportTemplateAsker] = None
    library_change: Optional[LibraryChangeAsker] = None
    edit_template: Optional[TemplateEditor] = None
    confirm_edit: Optional[TemplateEditConfirmer] = None
    choose_misfit: Optional[MisfitChooser] = None
    save_to_library: Optional[Callable[[ImportTemplate], None]] = None
