"""
`WizardJobs`: the import wizard's background work on the `JobRunner` port -- reading the
sample (again, when the text format changes), the preview, the check of further sample
files and the duplicate check -- and the one rule for whether a result still holds.

Every result is kept with the question it answers (the template, and for the preview
the shown sheet and workbook); it holds while the wizard asks the same question. A
result that lands after the question changed is kept, but is not current (and an
older preview never replaces the current one, whatever order they land in), so a
template changed in any way -- a choice, a metadata piece, the duplicates choice --
makes the preview, the duplicates and the further samples' check stale at once.
"""

from typing import Callable, Dict, Optional, Sequence, Tuple

from core.import_template import ImportTemplate
from core.jobs import job_step
from io_modules.import_template import TextFormat, build_text_format, read_sample_fits, read_workbook
from orchestration.jobs import JobRunner
from view_models.import_template import (
    ImportTemplateWizard, WizardEnding, WizardPreview, build_duplicate_groups, build_wizard_preview,
)

SAMPLE_SLOT_KEY = "import_template_sample"
PREVIEW_SLOT_KEY = "import_template_preview"
FITS_SLOT_KEY = "import_template_sample_fits"
DUPLICATES_SLOT_KEY = "import_template_duplicates"
OTHER_SAMPLE_SLOT_KEY = "import_template_other_sample"
_SLOT_KEYS = (SAMPLE_SLOT_KEY, PREVIEW_SLOT_KEY, FITS_SLOT_KEY, DUPLICATES_SLOT_KEY, OTHER_SAMPLE_SLOT_KEY)

# What `on_change` says changed; the listener reads the rest from `WizardJobs`.
CHANGE_OPENED = "opened"            # the sample was read: `wizard` exists, show its template
CHANGE_TEMPLATE = "template"        # the template changed by a choice or a metadata edit; the step made it shows it
CHANGE_REWRITTEN = "rewritten"      # the template changed by the duplicates choice: show it again
CHANGE_WORKBOOK = "workbook"        # the preview shows another workbook (or the same one read again)
CHANGE_PREVIEW = "preview"          # a preview landed
CHANGE_FITS = "fits"                # the further samples' check landed
CHANGE_DUPLICATES = "duplicates"    # the duplicate check started, landed or failed
CHANGE_MESSAGE = "message"          # `message` is news for the status line

_STALE_PREVIEW = "The preview of the template as it stands is still being read."


class WizardJobs:
    """
    "Read, preview and check the wizard's sample, and tell me what still holds."

    `on_change(kind)` runs on the thread that called the method that started the
    work -- the GUI thread in the application -- with one of the `CHANGE_*`
    kinds. Nothing here waits: every read and check is a job on `runner`, and
    a newer job of a kind supersedes the older one through its slot.
    """

    def __init__(self, runner: JobRunner, ending: WizardEnding, on_change: Callable[[str], None]):
        self.runner = runner
        self.ending = ending
        self.on_change = on_change
        self.wizard: Optional[ImportTemplateWizard] = None
        self.message = ""
        self.other_samples: Tuple[str, ...] = ()
        self._preview: Optional[Tuple[tuple, WizardPreview]] = None
        self._fits: Tuple[Optional[ImportTemplate], tuple] = (None, ())
        self._fits_asked: Optional[ImportTemplate] = None
        self._duplicates: Tuple[Optional[ImportTemplate], tuple] = (None, ())
        self._duplicate_note = ""

    # ---- opening ----------------------------------------------------------------

    def open(self, sample_path: str, template: Optional[ImportTemplate] = None) -> None:
        """Reads the sample on a worker; `CHANGE_OPENED` when the wizard exists, then the first preview."""
        text_format = build_text_format(template) if template is not None else TextFormat()

        def opened(workbook) -> None:
            self.wizard = ImportTemplateWizard(workbook, template)
            self.on_change(CHANGE_OPENED)
            self.run_preview()

        self._read(sample_path, text_format, SAMPLE_SLOT_KEY, opened)

    # ---- choices ----------------------------------------------------------------

    def change(self, **fields) -> None:
        """Makes choices (any ImportTemplate fields, by name); the preview of them is `run_preview`'s."""
        if self.wizard is None:
            return
        self.wizard.change(**fields)
        self.on_change(CHANGE_TEMPLATE)

    def show_sheet(self, sheet: str) -> None:
        if self.wizard is not None:
            self.wizard.show_sheet(sheet)

    def add_metadata_source(self, source: str, row_above: int = 0) -> int:
        """Adds a text metadata is taken from; its number (-1 before the sample is read)."""
        if self.wizard is None:
            return -1
        number = self.wizard.add_metadata_source(source, row_above=row_above)
        self.on_change(CHANGE_TEMPLATE)
        return number

    def remove_metadata_source(self, number: int) -> None:
        if self.wizard is not None and 0 <= number < len(self.wizard.template.metadata):
            self.wizard.remove_metadata_source(number)
            self.on_change(CHANGE_TEMPLATE)

    def change_metadata_source(self, number: int, **options) -> None:
        """How source `number`'s text is split (`delimiters`, `drop_unknown`)."""
        if self.wizard is not None and 0 <= number < len(self.wizard.template.metadata):
            self.wizard.change_metadata_source(number, **options)
            self.on_change(CHANGE_TEMPLATE)

    def assign_piece(self, number: int, position: int, field: str, **rule) -> str:
        """One piece of source `number` made a field; a refusal is returned and said (`CHANGE_MESSAGE`)."""
        if self.wizard is None or not 0 <= number < len(self.wizard.template.metadata):
            return ""
        refusal = self.wizard.assign_piece(number, position, field, **rule)
        self.on_change(CHANGE_TEMPLATE)
        if refusal:
            self._say(refusal)
        return refusal

    def keep_duplicates(self, picks: Dict[int, int]) -> None:
        """Writes the duplicate choice (group number -> copy number kept) into the template, if the groups still hold."""
        groups = self.duplicate_groups
        if self.wizard is None or not groups:
            return
        self.wizard.keep_duplicates(groups, picks=picks)
        self._duplicates = (None, ())
        self._duplicate_note = "Saved in the template as the sheets and columns it reads."
        self.on_change(CHANGE_REWRITTEN)
        self.run_preview()

    # ---- the preview ------------------------------------------------------------

    def run_preview(self) -> None:
        """Previews the template as it stands; reads the shown sample again first when its text format changed."""
        if self.wizard is None:
            return
        text_format = self.wizard.resolve_text_format_to_read()
        if text_format is not None:
            path = self.wizard.workbook.path

            def reread(workbook) -> None:
                if self.wizard is None or workbook.path != self.wizard.workbook.path:
                    return      # another workbook is shown meanwhile
                self.wizard.replace_shown_sample(workbook)
                self.on_change(CHANGE_WORKBOOK)
                self.run_preview()

            self._read(path, text_format, SAMPLE_SLOT_KEY, reread)
            return
        if self._fits_asked != self.wizard.template:
            self.run_sample_fits()
        asked = self._preview_question()
        self.runner.submit(
            "Import wizard preview",
            steps=[job_step("Preview", build_wizard_preview, self.wizard.workbook, *asked[:2])],
            lane="interactive", slot_key=PREVIEW_SLOT_KEY, quiet=True,
            on_step=lambda preview, _index: self._land_preview(asked, preview),
            on_error=lambda message, _index: self._say(f"The preview failed: {message}"),
        )

    @property
    def preview(self) -> Optional[WizardPreview]:
        """The newest preview that landed, current or not."""
        return self._preview[1] if self._preview is not None else None

    def is_preview_current(self) -> bool:
        return self._preview is not None and self._preview[0] == self._preview_question()

    def resolve_action_problems(self) -> Dict[str, str]:
        """Each action the ending offers -> why it cannot be used now (blank: it can); a stale preview blocks all."""
        if self.wizard is None or self._preview is None:
            return {action: _STALE_PREVIEW for action in self.ending.resolve_actions()}
        current = self.is_preview_current()
        return {action: (self.ending.resolve_problem(action, self.wizard, self._preview[1]) if current
                         else _STALE_PREVIEW)
                for action in self.ending.resolve_actions()}

    # ---- further samples --------------------------------------------------------

    def add_other_samples(self, paths: Sequence[str]) -> None:
        """Lists further sample files and checks the template against them on a worker."""
        self.other_samples = tuple(dict.fromkeys(self.other_samples + tuple(paths)))
        self.run_sample_fits()

    def run_sample_fits(self) -> None:
        if self.wizard is None or not self.other_samples:
            return
        template = self._fits_asked = self.wizard.template

        def landed(fits) -> None:
            self._fits = (template, fits)
            self.on_change(CHANGE_FITS)

        self.runner.submit(
            "Check further sample files",
            steps=[job_step("Check", read_sample_fits, self.other_samples, template)],
            lane="interactive", slot_key=FITS_SLOT_KEY, quiet=True,
            on_step=lambda fits, _index: landed(fits),
            on_error=lambda message, _index: self._say(f"The check failed: {message}"),
        )

    @property
    def sample_fits(self) -> tuple:
        """The newest check of the further samples (`SampleFit` each), current or not."""
        return self._fits[1]

    def show_other_sample(self, path: str) -> None:
        """Reads a further sample on a worker and shows it in the preview."""
        if self.wizard is None:
            return
        self._read(path, build_text_format(self.wizard.template), OTHER_SAMPLE_SLOT_KEY, self._show_workbook)

    def show_first_sample(self) -> None:
        if self.wizard is not None:
            self.runner.cancel_slot(OTHER_SAMPLE_SLOT_KEY)
            self._show_workbook(self.wizard.sample)

    def _show_workbook(self, workbook) -> None:
        if self.wizard is None:
            return
        self.wizard.use_sample(workbook)
        self.on_change(CHANGE_WORKBOOK)
        self.run_preview()

    # ---- duplicates ---------------------------------------------------------------

    def run_duplicate_check(self) -> None:
        """Looks for duplicate curves in the first sample, on a worker (never at scan)."""
        if self.wizard is None:
            return
        asked = self.wizard.template
        self._duplicate_note = "Checking…"
        self.on_change(CHANGE_DUPLICATES)

        def landed(groups) -> None:
            self._duplicates = (asked, groups)
            self._duplicate_note = ""
            self.on_change(CHANGE_DUPLICATES)

        def failed(message) -> None:
            self._duplicate_note = f"The check failed: {message}"
            self.on_change(CHANGE_DUPLICATES)

        self.runner.submit(
            "Check the sample for duplicate curves",
            steps=[job_step("Check", build_duplicate_groups, self.wizard.sample, asked)],
            lane="interactive", slot_key=DUPLICATES_SLOT_KEY, quiet=True,
            on_step=lambda groups, _index: landed(groups),
            on_error=lambda message, _index: failed(message),
        )

    @property
    def duplicate_groups(self) -> tuple:
        """The duplicate groups found for the template as it stands; none once it changed."""
        asked, groups = self._duplicates
        return groups if self.wizard is not None and asked == self.wizard.template else ()

    @property
    def duplicate_note(self) -> str:
        """What the duplicate check says now, for the line under its table."""
        asked, groups = self._duplicates
        if self._duplicate_note or asked is None:
            return self._duplicate_note
        if not self.duplicate_groups:
            return "The template changed: check for duplicates again." if groups else "No duplicate curves in the sample."
        return f"{len(groups)} duplicated curve(s) found."

    # ---- the end --------------------------------------------------------------------

    def cancel(self) -> None:
        """Stops every job of the wizard; their results never land."""
        for key in _SLOT_KEYS:
            self.runner.cancel_slot(key)

    # ---- inside -------------------------------------------------------------------

    def _preview_question(self) -> tuple:
        return (self.wizard.template, self.wizard.shown_sheet, self.wizard.workbook.path)

    def _land_preview(self, asked: tuple, preview: WizardPreview) -> None:
        if self.is_preview_current() and asked != self._preview_question():
            return          # an older question's preview, landing after the current one
        self._preview = (asked, preview)
        self.on_change(CHANGE_PREVIEW)

    def _read(self, path: str, text_format: TextFormat, slot_key: str, landed: Callable) -> None:
        self.runner.submit(
            "Read the import wizard's sample",
            steps=[job_step("Read sample", read_workbook, path, None, None, text_format)],
            lane="interactive", slot_key=slot_key, quiet=True,
            on_step=lambda workbook, _index: landed(workbook),
            on_error=lambda message, _index: self._say(f"The sample cannot be read: {message}"),
        )

    def _say(self, message: str) -> None:
        self.message = message
        self.on_change(CHANGE_MESSAGE)
