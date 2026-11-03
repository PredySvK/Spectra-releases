"""
view_models.import_template -- the import wizard's state and preview, without Qt.

- ImportTemplateWizard: a sample `Workbook` and the template being built on it.
  `change(**fields)` makes a choice (any ImportTemplate field), `show_sheet`
  picks the sheet the grid shows, `preview()` is what the dialog draws, and
  `resolve_fit_problem` says why the template does not fit the sample yet.
  Metadata is chosen on the sample's pieces: `add_metadata_source`,
  `change_metadata_source`, `assign_piece` (refuses a field fed from two
  sources, see `resolve_duplicate_field_problem`) and `drop_piece`.
- build_wizard_preview: the preview as a pure function of plain values, so the
  dialog can run it on a worker. It reads the sample through the same
  `build_template_reading` as the Data Pool scan, so the preview never differs
  from the result. Its metadata table (`metadata_fields`, each
  `PreviewChannel.metadata`) has the kinds the Data Pool schema will give.
- build_template_edit_summary: the consequences of replacing a project's copy
  of a template by the edited one -- the fields that disappear or are renamed,
  and the Filter cards and evaluations that use them (`TemplateEditSummary`).
- WizardEnding: how the wizard ends (library, misfit or project) -- the actions it
  offers (`resolve_actions`), why one cannot be used yet (`resolve_problem`), the
  template it opens on (`resolve_opening_template`: a built-in one under a copy's
  name) and how a finished one saved (`resolve_saved_as`).
- resolve_library_save_problem: why a template cannot go into the library
  under a name (a built-in's).
- build_duplicate_groups: the wizard's optional duplicate check on the sample
  (same channel, same order, equal values after conversion to RMS, whatever
  the other metadata). `ImportTemplateWizard.keep_duplicates` writes the
  user's choice (keep one copy per group) into the template as the sheets and
  channels it reads. It never runs at scan.
- `ImportTemplateWizard.use_sample` shows a further sample file (whether the
  template fits each is io_modules/import_template's `read_sample_fits`).
- build_default_template: the first guess on a new sample (heading row, column
  layout, channel name).

What does NOT belong here: Qt widgets and colours (gui/), reading the sample
or writing the template file (io_modules/import_template).
"""

from view_models.import_template._duplicates import (
    DuplicateCopy,
    DuplicateGroup,
    build_duplicate_groups,
    resolve_kept_copies,
)
from view_models.import_template._edit_summary import (
    FieldConsequence,
    TemplateEditSummary,
    build_template_edit_summary,
)
from view_models.import_template._ending import (
    ACTION_OVERWRITE,
    ACTION_SAVE,
    ACTION_SAVE_AS_NEW,
    ENDING_LIBRARY,
    ENDING_MISFIT,
    ENDING_PROJECT,
    SAVED_NEW,
    SAVED_OVERWRITE,
    WizardEnding,
)
from view_models.import_template._preview import (
    CELL_DATA,
    CELL_HEADER,
    CELL_IGNORED,
    PreviewChannel,
    PreviewField,
    PreviewPiece,
    PreviewSource,
    WizardPreview,
    build_wizard_preview,
)
from view_models.import_template._wizard import (
    ImportTemplateWizard,
    build_default_template,
    resolve_duplicate_field_problem,
    resolve_library_save_problem,
)

__all__ = [
    "ACTION_OVERWRITE",
    "ACTION_SAVE",
    "ACTION_SAVE_AS_NEW",
    "CELL_DATA",
    "CELL_HEADER",
    "CELL_IGNORED",
    "ENDING_LIBRARY",
    "ENDING_MISFIT",
    "ENDING_PROJECT",
    "DuplicateCopy",
    "DuplicateGroup",
    "FieldConsequence",
    "ImportTemplateWizard",
    "PreviewChannel",
    "PreviewField",
    "PreviewPiece",
    "PreviewSource",
    "SAVED_NEW",
    "SAVED_OVERWRITE",
    "TemplateEditSummary",
    "WizardEnding",
    "WizardPreview",
    "build_default_template",
    "build_template_edit_summary",
    "build_wizard_preview",
    "build_duplicate_groups",
    "resolve_duplicate_field_problem",
    "resolve_kept_copies",
    "resolve_library_save_problem",
]
