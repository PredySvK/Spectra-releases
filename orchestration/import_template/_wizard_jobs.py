"""
`TemplateWizardJobs`: the import wizard's background work on the `JobRunner`
port -- reading the samples (at opening, when files are added, and again when
the text format changes), the further files of the first sample's kind, and the
preview of every sample -- and the one rule for whether the preview still holds.

The preview is kept with the question it answers (the template and the
samples' revision); it holds while the wizard asks the same question. One that
lands after the question changed is kept but is not current, and an older one
never replaces the current one. The preview also splits every channel's texts
into chips on the worker; when the current one lands, the roles of step 3 are
guessed from them (until the user gave one), and the guess is previewed at once.

A template opened for editing is read with its own text format and
its answers and choices are the wizard's from the start. The ending (library,
misfit report, project) says which actions the last step offers and why one
cannot be used yet (`resolve_action_problems`); the optional duplicate check
runs on the first sample on a worker, never at scan, and its choice is written
into the template (`keep_duplicates`).
"""

from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from core.import_template import ChipCut, ChipRef, ImportTemplate, MetadataField
from core.jobs import job_step
from io_modules.import_template import TextFormat, build_text_format, read_more_samples, read_samples
from orchestration.jobs import JobRunner
from view_models.import_template import (
    SamplePreview, TemplateWizard, WizardEnding, build_duplicate_groups, build_sample_preview,
)

SAMPLES_SLOT_KEY = "import_template_samples"
ADDED_SLOT_KEY = "import_template_added_samples"
SAMPLE_PREVIEW_SLOT_KEY = "import_template_sample_preview"
SAMPLE_DUPLICATES_SLOT_KEY = "import_template_sample_duplicates"
_SLOT_KEYS = (SAMPLES_SLOT_KEY, ADDED_SLOT_KEY, SAMPLE_PREVIEW_SLOT_KEY, SAMPLE_DUPLICATES_SLOT_KEY)
_STALE_PREVIEW = "The preview of the samples as they stand is still being read."

# What `on_change` says changed; the listener reads the rest from `TemplateWizardJobs`.
SAMPLES_OPENED = "opened"        # the samples were read: `wizard` exists
SAMPLES_CHANGED = "samples"      # a sample was added, removed or read again (refusals too)
SAMPLES_CHOICE = "choice"        # an answer or a choice changed the template; preview it after a pause
SAMPLES_PREVIEW = "preview"      # a preview landed
SAMPLES_ROLES = "roles"          # step 3's roles were guessed from the landed chips; their preview is on its way
SAMPLES_MESSAGE = "message"      # `message` is news for the status line
SAMPLES_DUPLICATES = "duplicates"    # the duplicate check started, landed or failed


def _read_opening(paths: Sequence[str], text_format: TextFormat) -> Tuple[tuple, Tuple[str, ...]]:
    """The samples the wizard opens on, and the further files of the first one's kind in its folder (a worker)."""
    return read_samples(paths, text_format), read_more_samples(paths[0])


class TemplateWizardJobs:
    """
    "Read and preview the wizard's samples, and tell me what still holds."

    `on_change(kind)` runs on the thread that called the method that started
    the work -- the GUI thread in the application -- with one of the
    `SAMPLES_*` kinds. Nothing here waits: every read is a job on `runner`,
    and a newer job of a kind supersedes the older one through its slot.
    """

    def __init__(self, runner: JobRunner, on_change: Callable[[str], None], ending: Optional[WizardEnding] = None):
        self.runner = runner
        self.on_change = on_change
        self.ending = ending if ending is not None else WizardEnding()
        self.wizard: Optional[TemplateWizard] = None
        self.message = ""
        self._preview: Optional[Tuple[tuple, SamplePreview]] = None
        self._duplicates: Tuple[Optional[ImportTemplate], tuple] = (None, ())
        self._duplicate_note = ""

    # ---- the samples --------------------------------------------------------------

    def open(self, paths: Sequence[str], template: Optional[ImportTemplate] = None) -> None:
        """
        Reads the samples (each with the first one's suffix) and the first one's folder on a worker; then previews.
        With a `template` the samples are read with its text format and the wizard shows its choices.
        """
        paths = tuple(paths)
        if not paths:
            self.wizard = TemplateWizard((), (), template)
            self.on_change(SAMPLES_OPENED)
            return
        taken, refused = TemplateWizard(()).resolve_added(paths)

        def opened(landed) -> None:
            reads, more = landed
            self.wizard = TemplateWizard(reads, more, template)
            self.wizard.refuse(self.wizard.refusals + refused)
            self.on_change(SAMPLES_OPENED)
            self.run_preview()

        self.runner.submit(
            "Read the import wizard's samples",
            steps=[job_step("Read samples", _read_opening, taken,
                            build_text_format(template) if template is not None else TextFormat())],
            lane="interactive", slot_key=SAMPLES_SLOT_KEY, quiet=True,
            on_step=lambda landed, _index: opened(landed),
            on_error=lambda message, _index: self._say(f"The samples cannot be read: {message}"))

    def add_samples(self, paths: Iterable[str]) -> None:
        """Reads further samples on a worker; a file of another suffix is refused with the reason at once."""
        if self.wizard is None:
            return
        accepted, refused = self.wizard.resolve_added(tuple(paths))
        self.wizard.refuse(refused)
        self.on_change(SAMPLES_CHANGED)
        if not accepted:
            return
        text_format = build_text_format(self.wizard.template)

        def landed(reads) -> None:
            if self.wizard is None:
                return
            self.wizard.add_samples(reads)
            self.on_change(SAMPLES_CHANGED)
            self.run_preview()

        self.runner.submit(
            "Read further samples",
            steps=[job_step("Read samples", read_samples, accepted, text_format)],
            lane="interactive", slot_key=ADDED_SLOT_KEY, quiet=True,
            on_step=lambda reads, _index: landed(reads),
            on_error=lambda message, _index: self._say(f"The samples cannot be read: {message}"))

    def remove_sample(self, path: str) -> None:
        if self.wizard is None:
            return
        problem = self.wizard.remove_sample(path)
        if problem:
            self._say(problem)
            return
        self.wizard.refuse(())
        self.on_change(SAMPLES_CHANGED)
        self.run_preview()

    # ---- choices ----------------------------------------------------------------------

    def answer(self, **fields) -> None:
        """Answers step 1's questions (SampleAnswers fields); the preview of them is `run_preview`'s."""
        if self.wizard is not None:
            self.wizard.answer(**fields)
            self.on_change(SAMPLES_CHOICE)

    def choose_table(self, **fields) -> None:
        """Step 2's choices (TableChoices fields)."""
        if self.wizard is not None:
            self.wizard.choose_table(**fields)
            self.on_change(SAMPLES_CHOICE)

    def choose_heading_row(self, path: str, sheet: str, row: int) -> None:
        self._choose(lambda wizard: wizard.choose_heading_row(path, sheet, row))

    def choose_data_row(self, path: str, sheet: str, row: int) -> None:
        self._choose(lambda wizard: wizard.choose_data_row(path, sheet, row))

    def find_heading_by_number(self, by_number: bool) -> None:
        self._choose(lambda wizard: wizard.find_heading_by_number(by_number))

    def name_template(self, name: str, file_pattern: str) -> None:
        if self.wizard is not None:
            self.wizard.name_template(name, file_pattern)
            self.on_change(SAMPLES_CHOICE)

    def set_chip_role(self, kind: str, ref: ChipRef, channel: int = 0) -> None:
        """Step 3: gives the chip `ref` names in channel `channel`'s text a role, on the chips of the newest preview."""
        self._change_roles(lambda wizard: wizard.set_chip_role(kind, ref, self.preview.chips, channel))

    def count_chip_from_other_end(self, kind: str, ref: ChipRef, channel: int = 0) -> None:
        """Step 3: the role's chip counted from the other end of its text."""
        self._change_roles(lambda wizard: wizard.count_chip_from_other_end(kind, ref, self.preview.chips, channel))

    def remove_chip_role(self, kind: str, ref: ChipRef) -> None:
        self._change_roles(lambda wizard: wizard.remove_chip_role(kind, ref))

    def move_name_chip(self, index: int, to: int) -> None:
        self._change_roles(lambda wizard: wizard.move_name_chip(index, to))

    def fix_order(self, order: float) -> None:
        self._change_roles(lambda wizard: wizard.fix_order(order))

    def set_field(self, field: MetadataField) -> None:
        """Step 3: a metadata field from a chip; a refusal (a second source, "Order" of an order cut) is the message."""
        if self.wizard is None or self.preview is None:
            return
        refusal = self.wizard.set_field(field)
        if refusal:
            self._say(refusal)
            return
        self.on_change(SAMPLES_CHOICE)

    def set_chip_cuts(self, key: Tuple[str, int], chip: int, cuts: Sequence[ChipCut]) -> None:
        """Step 3: splits a chip by its own cuts (none: whole again); the chips are split again on the worker."""
        chips = self.preview.chips if self.preview is not None else None
        self._choose(lambda wizard: wizard.set_chip_cuts(key, chip, cuts, chips) or "")

    def remove_field(self, name: str) -> None:
        self._change_roles(lambda wizard: wizard.remove_field(name))

    def _change_roles(self, change: Callable[[TemplateWizard], None]) -> None:
        if self.wizard is None or self.preview is None:
            return
        change(self.wizard)
        self.on_change(SAMPLES_CHOICE)

    def _choose(self, choice: Callable[[TemplateWizard], str]) -> None:
        if self.wizard is None:
            return
        refusal = choice(self.wizard)
        if refusal:
            self._say(refusal)
            return
        self.on_change(SAMPLES_CHOICE)
        self.run_preview()

    # ---- the preview ----------------------------------------------------------------------

    def run_preview(self) -> None:
        """Previews the template on every sample; reads the samples again first when their text format changed."""
        if self.wizard is None:
            return
        text_format = self.wizard.resolve_text_format_to_read()
        if text_format is not None:
            revision = self.wizard.revision

            def reread(reads) -> None:
                if self.wizard is None or self.wizard.revision != revision:
                    return      # the samples changed meanwhile; their own preview follows
                self.wizard.replace_samples(reads)
                self.on_change(SAMPLES_CHANGED)
                self.run_preview()

            self.runner.submit(
                "Read the import wizard's samples again",
                steps=[job_step("Read samples", read_samples, self.wizard.sample_paths, text_format)],
                lane="interactive", slot_key=SAMPLES_SLOT_KEY, quiet=True,
                on_step=lambda reads, _index: reread(reads),
                on_error=lambda message, _index: self._say(f"The samples cannot be read: {message}"))
            return
        asked = self._question()
        self.runner.submit(
            "Import wizard preview",
            steps=[job_step("Preview", build_sample_preview, self.wizard.samples, asked[0], asked[2])],
            lane="interactive", slot_key=SAMPLE_PREVIEW_SLOT_KEY, quiet=True,
            on_step=lambda preview, _index: self._land_preview(asked, preview),
            on_error=lambda message, _index: self._say(f"The preview failed: {message}"))

    @property
    def preview(self) -> Optional[SamplePreview]:
        """The newest preview that landed, current or not."""
        return self._preview[1] if self._preview is not None else None

    def is_preview_current(self) -> bool:
        return self.wizard is not None and self._preview is not None and self._preview[0] == self._question()

    def resolve_step_problem(self, step: int, builtin_names: Optional[Iterable[str]] = None) -> str:
        """Why Next (Save on the last step) is off on `step`; a stale preview counts as none."""
        if self.wizard is None:
            return "The samples are still being read."
        current = self.preview if self.is_preview_current() else None
        return self.wizard.resolve_step_problem(step, current, builtin_names)

    @property
    def template(self) -> Optional[ImportTemplate]:
        return self.wizard.template if self.wizard is not None else None

    def resolve_action_problems(self) -> Dict[str, str]:
        """Each action the ending offers -> why it cannot be used now (blank: it can); a stale preview blocks all."""
        actions = self.ending.resolve_actions()
        if self.wizard is None:
            return {action: "The samples are still being read." for action in actions}
        if not self.is_preview_current():
            return {action: _STALE_PREVIEW for action in actions}
        return {action: self.ending.resolve_problem(action, self.wizard, self._preview[1]) for action in actions}

    # ---- duplicates -----------------------------------------------------------------------------

    def run_duplicate_check(self) -> None:
        """Looks for duplicate curves in the first sample, on a worker (never at scan)."""
        if self.wizard is None or not self.wizard.samples:
            return
        asked = self.wizard.template
        self._duplicate_note = "Checking…"
        self.on_change(SAMPLES_DUPLICATES)

        def landed(groups) -> None:
            self._duplicates = (asked, groups)
            self._duplicate_note = ""
            self.on_change(SAMPLES_DUPLICATES)

        def failed(message) -> None:
            self._duplicate_note = f"The check failed: {message}"
            self.on_change(SAMPLES_DUPLICATES)

        self.runner.submit(
            "Check the first sample for duplicate curves",
            steps=[job_step("Check", build_duplicate_groups, self.wizard.samples[0], asked)],
            lane="interactive", slot_key=SAMPLE_DUPLICATES_SLOT_KEY, quiet=True,
            on_step=lambda groups, _index: landed(groups),
            on_error=lambda message, _index: failed(message))

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

    def keep_duplicates(self, picks: Dict[int, int]) -> None:
        """Writes the duplicate choice (group number -> copy number kept) into the template, if the groups still hold."""
        groups = self.duplicate_groups
        if self.wizard is None or not groups:
            return
        self.wizard.keep_duplicates(groups, picks=picks)
        self._duplicates = (None, ())
        self._duplicate_note = "Saved in the template as the sheets and columns it reads."
        self.on_change(SAMPLES_CHOICE)
        self.on_change(SAMPLES_DUPLICATES)
        self.run_preview()

    # ---- the end ------------------------------------------------------------------------------

    def cancel(self) -> None:
        """Stops every job of the wizard; their results never land."""
        for key in _SLOT_KEYS:
            self.runner.cancel_slot(key)

    # ---- inside -------------------------------------------------------------------------------

    def _question(self) -> tuple:
        return (self.wizard.template, self.wizard.revision, self.wizard.cuts)

    def _land_preview(self, asked: tuple, preview: SamplePreview) -> None:
        if self.is_preview_current() and asked != self._question():
            return          # an older question's preview, landing after the current one
        self._preview = (asked, preview)
        self.on_change(SAMPLES_PREVIEW)
        if self.is_preview_current() and self.wizard.apply_chip_suggestion(preview.chips):
            self.on_change(SAMPLES_ROLES)
            self.run_preview()

    def _say(self, message: str) -> None:
        self.message = message
        self.on_change(SAMPLES_MESSAGE)
