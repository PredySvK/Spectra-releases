"""
view_models.import_template -- the import wizard's state and preview, without Qt.

- build_template_edit_summary: the consequences of replacing a project's copy
  of a template by the edited one -- the fields that disappear or are renamed,
  and the Filter cards and evaluations that use them (`TemplateEditSummary`).
- WizardEnding: how the wizard ends (library, misfit or project) -- the actions it
  offers (`resolve_actions`), why one cannot be used yet (`resolve_problem`), the
  template it opens on (`resolve_opening_template`: a built-in one under a copy's
  name) and how a finished one saved (`resolve_saved_as`).
- resolve_library_save_problem: why a template cannot go into the library
  under a name (a built-in's). resolve_amplitude_unit_options: the units step 2
  offers for the amplitude.
- build_duplicate_groups: the wizard's optional duplicate check on the first
  sample (same channel, same order, equal values after conversion to RMS,
  whatever the other metadata). `TemplateWizard.keep_duplicates` writes the
  user's choice (keep one copy per group) into the template as the sheets and
  channels it reads. It never runs at scan.
- TemplateWizard: the wizard's state (#1028) -- several samples from the
  start, the step 1 answers the files cannot give (`SampleAnswers`), the step 2
  table set by clicking a row (`TableChoices`), the suggested name and file
  pattern (`resolve_name_suggestion`), the template they make, and why
  Next or Save is off (`resolve_step_problem`). build_sample_preview: its
  preview of every sample, pure for a worker (`SamplePreview`: a tab per file
  and sheet, every channel, the skipped sheets and what the headings state).
- Step 3 of TemplateWizard (#1033): a chip's own cuts -- `build_cut_offers` / `build_word_cut_offer` offer the cuts that
  fit every sample, `TemplateWizard.set_chip_cuts` keeps them (the template's text sources carry them), the
  preview splits the chips by them (`build_sample_preview(..., cuts)`).
- Step 3 of TemplateWizard (#1031): `SamplePreview.chips` (`SampleChips`) are
  every channel's texts split into chips and how each chip changes across the
  samples (CHIP_*); `SampleRoles` are the roles the user gives the chips
  (guessed first, `TemplateWizard.apply_chip_suggestion`). `resolve_channel_roles`
  is what they make of one channel, `resolve_chip_marks` the chips with a role
  in one text, `resolve_name_joins` which name chips keep the text between them.
  A text whose chip count varies is counted from the start or from the end
  (`resolve_chip_anchor`); `resolve_chip_kinds` / `resolve_role_ref` say which
  roles take a chip of one channel's text, whichever end they count from.

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
from view_models.import_template._chip_cuts import (
    CutOffer,
    SourceCuts,
    apply_chip_cuts,
    build_cut_offers,
    build_word_cut_offer,
    resolve_chip_values,
    resolve_cut_label,
    resolve_cut_pieces,
    resolve_default_offer,
)
from view_models.import_template._sample_chips import (
    CHIP_BETWEEN_FILES,
    CHIP_BETWEEN_SHEETS,
    CHIP_IN_COLUMNS,
    CHIP_MISSING,
    CHIP_ROLE_KINDS,
    CHIP_SAME,
    ChannelTexts,
    ChipChange,
    FieldOffer,
    SampleChips,
    SampleRoles,
    build_field_offer,
    build_metadata_field,
    resolve_channel_roles,
    resolve_chip_anchor,
    resolve_chip_kinds,
    resolve_chip_marks,
    resolve_name_joins,
    resolve_role_ref,
)
from view_models.import_template._sample_preview import (
    NOT_BY_SHEET_RULE,
    SampleChannel,
    SamplePreview,
    SampleSheet,
    SampleUnits,
    SkippedSampleSheet,
    build_sample_preview,
    resolve_sample_label,
)
from view_models.import_template._wizard import (
    QUESTION_AMPLITUDE,
    QUESTION_CHANNEL_TYPE,
    QUESTION_DATA_KIND,
    QUESTION_ORIGIN,
    QUESTION_TIME,
    QUESTION_VALUES,
    STEP_CHECK,
    STEP_ROLES,
    STEP_SAMPLES,
    STEP_TABLE,
    TIME_FIXED_RATE,
    TIME_FROM_COLUMN,
    TIME_RATE_FROM_TEXT,
    TIME_SOURCES,
    SampleAnswers,
    TemplateWizard,
    TableChoices,
    resolve_amplitude_unit_options,
    resolve_library_save_problem,
    resolve_name_suggestion,
)
__all__ = [
    "CHIP_BETWEEN_FILES",
    "CHIP_BETWEEN_SHEETS",
    "CHIP_IN_COLUMNS",
    "CHIP_MISSING",
    "CHIP_ROLE_KINDS",
    "CHIP_SAME",
    "ChannelTexts",
    "ChipChange",
    "SampleChips",
    "SampleRoles",
    "FieldOffer",
    "build_field_offer",
    "build_metadata_field",
    "resolve_channel_roles",
    "CutOffer",
    "SourceCuts",
    "apply_chip_cuts",
    "build_cut_offers",
    "build_word_cut_offer",
    "resolve_chip_values",
    "resolve_cut_label",
    "resolve_cut_pieces",
    "resolve_default_offer",
    "resolve_chip_anchor",
    "resolve_chip_kinds",
    "resolve_chip_marks",
    "resolve_name_joins",
    "resolve_role_ref",
    "ACTION_OVERWRITE",
    "ACTION_SAVE",
    "ACTION_SAVE_AS_NEW",
    "ENDING_LIBRARY",
    "ENDING_MISFIT",
    "ENDING_PROJECT",
    "DuplicateCopy",
    "DuplicateGroup",
    "FieldConsequence",
    "NOT_BY_SHEET_RULE",
    "QUESTION_AMPLITUDE",
    "QUESTION_CHANNEL_TYPE",
    "QUESTION_DATA_KIND",
    "QUESTION_ORIGIN",
    "QUESTION_TIME",
    "QUESTION_VALUES",
    "SAVED_NEW",
    "SAVED_OVERWRITE",
    "STEP_CHECK",
    "STEP_ROLES",
    "STEP_SAMPLES",
    "STEP_TABLE",
    "SampleAnswers",
    "SampleChannel",
    "SamplePreview",
    "SampleSheet",
    "SampleUnits",
    "TemplateWizard",
    "SkippedSampleSheet",
    "TIME_FIXED_RATE",
    "TIME_FROM_COLUMN",
    "TIME_RATE_FROM_TEXT",
    "TIME_SOURCES",
    "TableChoices",
    "TemplateEditSummary",
    "WizardEnding",
    "build_sample_preview",
    "build_template_edit_summary",
    "build_duplicate_groups",
    "resolve_kept_copies",
    "resolve_amplitude_unit_options",
    "resolve_library_save_problem",
    "resolve_name_suggestion",
    "resolve_sample_label",
]
