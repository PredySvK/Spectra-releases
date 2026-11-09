"""
The import wizard's state (#1028): the samples, the answers the files
cannot give, the table as the user clicked it, and the name -- and the Import
template they make.

The wizard is linear: Samples and what it is, Table, Texts -> roles, Check and
save. Each step says why Next (or Save) is off (`resolve_step_problem`); the
problems of the earlier steps still count. Until the chips of the texts are
known the channel name is the whole header text (the heading cell, or the row
above it for X/Y pairs); then the roles of step 3 (#1031) are guessed from how
the chips change, and the user corrects them.
"""

import dataclasses
import fnmatch
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from core.import_template import (
    AMPLITUDE_FROM_HEADER, DATA_KIND_ORDER_CUT, DATA_KIND_SPECTRUM, DATA_KIND_TIME_SIGNAL,
    LAYOUT_SHARED_X, LAYOUT_SINGLE_CURVE, LAYOUT_XY_PAIRS, SOURCE_HEADER, ROLE_ORDER, ROLE_SAMPLE_RATE, SHEETS_ALL, ChipRef,
    ChipCut, ChipCuts, ImportTemplate, MetadataField, TextSource,
)
from core.units import get_compatible_options
from io_modules.import_template import (
    HZ_PER_UNIT, RPM_PER_UNIT, SECONDS_PER_UNIT, SampleRead, TextFormat, Workbook, build_text_format,
    read_builtin_templates, resolve_cell_text, resolve_chip_label, resolve_header_unit, resolve_heading_row, resolve_read_sheets,
    resolve_template_name_fit, resolve_text_source_label,
)
from io_modules.number_pairs import read_number_pairs
from view_models.import_template._chip_cuts import SourceCuts, apply_chip_cuts
from view_models.import_template._duplicates import DuplicateGroup, build_template_keeping, resolve_kept_copies
from view_models.import_template._sample_chips import (
    CHIP_ROLE_KINDS, SampleChips, SampleRoles, resolve_chip_anchor, resolve_chip_texts, resolve_order_role,
    resolve_role_suggestion,
)
from view_models.import_template._sample_preview import SamplePreview

_SPEED_UNITS = frozenset({"rpm", "Hz", "rad/s"})
_GUESS_ROWS = 60


def _is_number(cell) -> bool:
    return bool(read_number_pairs([(cell, 0)]).pairs)


def _is_reread_needed(workbook: Workbook, wanted: TextFormat) -> bool:
    """Whether a text sample was read with another format than `wanted` (an override, else its own detected)."""
    used, detected = workbook.text_format, workbook.detected_text_format
    if used is None or detected is None:
        return False
    return TextFormat(wanted.encoding or detected.encoding, wanted.delimiter or detected.delimiter,
                      wanted.decimal or detected.decimal) != used


def _guess_heading(rows: Sequence[tuple]) -> Optional[int]:
    """The first row with text in its first cell and a number below it."""
    for index in range(min(len(rows) - 1, _GUESS_ROWS)):
        first, below = rows[index], rows[index + 1]
        if first and below and resolve_cell_text(first[0]) and not _is_number(first[0]) and _is_number(below[0]):
            return index
    return None


def _guess_layout(heading: tuple) -> str:
    cells = [resolve_cell_text(cell).lower() for cell in heading]
    if len(cells) >= 4 and cells[0] and cells[2] == cells[0]:
        return LAYOUT_XY_PAIRS
    if sum(1 for cell in cells[1:] if cell) >= 2:
        return LAYOUT_SHARED_X
    return LAYOUT_SINGLE_CURVE


def resolve_library_save_problem(name: str, builtin_names: Optional[Iterable[str]] = None) -> str:
    """Why a template cannot go into the library under `name`, blank when it can: a built-in's name is refused."""
    name = name.strip()
    if not name:
        return "Give the template a name."
    names = builtin_names if builtin_names is not None else (t.name for t in read_builtin_templates())
    if name.lower() in {builtin.lower() for builtin in names}:
        return f"'{name}' is a built-in template; save under another name."
    return ""


def resolve_amplitude_unit_options(header_unit: str) -> List[str]:
    """
    The units offered for the amplitude: the header's own first (also one the
    program does not know), then the known ones, compatible first. Speed
    units are the X axis's, never an amplitude's.
    """
    known = [unit for unit in get_compatible_options(header_unit) if unit not in _SPEED_UNITS]
    own = [header_unit] if header_unit and header_unit != "unknown" and header_unit not in known else []
    return own + known


# The steps, in order.
STEP_SAMPLES, STEP_TABLE, STEP_ROLES, STEP_CHECK = range(4)

# The questions of step 1; one that does not apply to the data kind is hidden.
QUESTION_DATA_KIND = "data_kind"
QUESTION_ORIGIN = "origin"
QUESTION_VALUES = "values"
QUESTION_AMPLITUDE = "amplitude"
QUESTION_CHANNEL_TYPE = "channel_type"
QUESTION_TIME = "time"

# Where a time signal's time comes from: its first column, a fixed sample rate, or a text (a step 3 slot).
TIME_FROM_COLUMN = "column"
TIME_FIXED_RATE = "fixed_rate"
TIME_RATE_FROM_TEXT = "rate_from_text"
TIME_SOURCES = (TIME_FROM_COLUMN, TIME_FIXED_RATE, TIME_RATE_FROM_TEXT)

_STALE_PREVIEW = "The preview of the samples as they stand is still being read."


@dataclass(frozen=True)
class SampleAnswers:
    """
    What the user knows and the file cannot tell. `simulated` None and
    `amplitude` blank are unanswered: there is no default, a wrong one would
    change the numbers unnoticed. `amplitude` is one of FILE_AMPLITUDES.
    """

    data_kind: str = DATA_KIND_ORDER_CUT
    simulated: Optional[bool] = None
    amplitude: str = ""
    values_in_db: bool = False
    db_reference: float = 0.0
    channel_type: str = ""
    time_source: str = TIME_FROM_COLUMN
    sample_rate: float = 0.0


@dataclass(frozen=True)
class TableChoices:
    """
    Step 2: the heading row -- found by its first cell's text, or by its
    number when `find_by_number` -- where the data starts below it, the
    column layout, the sheets read, the units (blank: from the headings) and
    a text file's format (blank: detected).
    """

    heading_text: str = ""
    heading_number: int = 1
    find_by_number: bool = True
    data_offset: int = 1
    layout: str = LAYOUT_SINGLE_CURVE
    sheet_rule: str = SHEETS_ALL
    sheet_count: int = 1
    sheets: Tuple[str, ...] = ()
    x_unit: str = ""
    amplitude_unit: str = ""
    encoding: str = ""
    delimiter: str = ""
    decimal_separator: str = ""


def resolve_name_suggestion(paths: Sequence[str]) -> Tuple[str, str]:
    """
    The template name and file pattern the samples suggest: what their names
    share before and after the part that changes ("TEST", "TEST*NmA_H1.txt").
    One sample gives its own name and every file of its suffix.
    """
    if not paths:
        return "New template", "*"
    stems = [os.path.splitext(os.path.basename(path))[0] for path in paths]
    suffix = os.path.splitext(paths[0])[1].lower()
    if len(stems) == 1:
        return stems[0], f"*{suffix}"
    prefix = os.path.commonprefix(stems).rstrip("0123456789")
    tail = os.path.commonprefix([stem[::-1] for stem in stems])[::-1].lstrip("0123456789")
    return (prefix.strip(" _-") or stems[0]), f"{prefix}*{tail}{suffix}"


def _guess_data_kind(x_cell) -> str:
    """The data kind an X heading cell's unit suggests (s: time signal, Hz: spectrum, a speed: order cut), blank for none."""
    unit = resolve_header_unit(x_cell).lower()
    if unit in SECONDS_PER_UNIT:
        return DATA_KIND_TIME_SIGNAL
    if unit in HZ_PER_UNIT:
        return DATA_KIND_SPECTRUM
    return DATA_KIND_ORDER_CUT if unit in RPM_PER_UNIT else ""


class TemplateWizard:
    """
    The samples (`samples`, in order; every one has the first one's suffix),
    the step 1 `answers`, the step 2 `table` and the template they make
    (`template`). `revision` counts the changes of the samples, so a result
    computed on them can tell it still holds.
    """

    def __init__(self, reads: Sequence[SampleRead], more: Iterable[str] = (),
                 template: Optional[ImportTemplate] = None):
        self.samples: Tuple[Workbook, ...] = ()
        self.revision = 0
        self.refusals: Tuple[str, ...] = ()
        self.more_samples = tuple(more)
        self.answers = SampleAnswers()
        self.table = TableChoices()
        self.layout_guess = LAYOUT_SINGLE_CURVE
        self.data_kind_guess: Tuple[str, str] = ("", "")
        self._layout_chosen = False
        self.roles: Optional[SampleRoles] = None
        self._roles_chosen = False
        self.cuts: SourceCuts = ()
        self._name: Optional[Tuple[str, str]] = None
        # What the template carries and no step asks: the channels the duplicate check left out, the speed channel.
        self.skipped_columns: Tuple[Tuple[str, int], ...] = ()
        self.speed_channel = ""
        # The name of the template loaded for editing: Overwrite keeps it, Save as new leaves it.
        self.original_name = template.name if template is not None else ""
        self.add_samples(reads)
        if template is not None:
            self._apply_template(template)

    # ---- the samples ---------------------------------------------------------------

    @property
    def sample_paths(self) -> Tuple[str, ...]:
        return tuple(sample.path for sample in self.samples)

    @property
    def suffix(self) -> str:
        return os.path.splitext(self.samples[0].path)[1].lower() if self.samples else ""

    @property
    def is_single_sample(self) -> bool:
        """One file with one sheet: it cannot show what changes between files."""
        return len(self.samples) == 1 and len(self.samples[0].sheet_names) == 1

    @property
    def offered_samples(self) -> Tuple[str, ...]:
        """The further files of the first sample's kind in its folder, offered while there is one sample only."""
        if len(self.samples) != 1:
            return ()
        known = {os.path.normcase(path) for path in self.sample_paths}
        return tuple(path for path in self.more_samples if os.path.normcase(path) not in known)

    def resolve_added(self, paths: Sequence[str]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        """
        The files to read as further samples, and each refused one with why: a
        template has one file pattern and one text format, so every sample has
        the first one's suffix. A file that already is a sample is left out.
        """
        suffix = self.suffix or (os.path.splitext(paths[0])[1].lower() if paths else "")
        known = {os.path.normcase(path) for path in self.sample_paths}
        accepted, refused = [], []
        for path in paths:
            if os.path.normcase(path) in known:
                continue
            if os.path.splitext(path)[1].lower() != suffix:
                refused.append(f"{os.path.basename(path)}: not a {suffix} file like the first sample -- a template "
                               f"has one file pattern and one text format.")
                continue
            known.add(os.path.normcase(path))
            accepted.append(path)
        return tuple(accepted), tuple(refused)

    def refuse(self, refusals: Sequence[str]) -> None:
        self.refusals = tuple(refusals)

    def add_samples(self, reads: Sequence[SampleRead]) -> None:
        """Adds the samples read; one that could not be read is a refusal. The first sample is guessed on."""
        first = not self.samples
        known = {os.path.normcase(path) for path in self.sample_paths}
        added = [read.workbook for read in reads
                 if read.workbook is not None and os.path.normcase(read.path) not in known]
        self.refusals = self.refusals + tuple(f"{os.path.basename(read.path)} cannot be read: {read.problem}"
                                              for read in reads if read.workbook is None)
        if not added:
            return
        self.samples += tuple(added)
        self.revision += 1
        if first:
            self._guess()

    def remove_sample(self, path: str) -> str:
        """Removes a sample; why not (the last one stays), blank when it is removed."""
        if len(self.samples) <= 1:
            return "The wizard needs a sample: add another file before removing this one."
        self.samples = tuple(sample for sample in self.samples if os.path.normcase(sample.path) != os.path.normcase(path))
        self.revision += 1
        return ""

    def replace_samples(self, reads: Sequence[SampleRead]) -> None:
        """The samples read again with another text format; the choices are unchanged."""
        by_path = {os.path.normcase(read.path): read.workbook for read in reads if read.workbook is not None}
        self.samples = tuple(by_path.get(os.path.normcase(sample.path), sample) for sample in self.samples)
        self.revision += 1

    @property
    def detected_text_format(self) -> Optional[TextFormat]:
        """What the first text sample suggests for its encoding, delimiter and decimal separator; None for workbooks."""
        return next((sample.detected_text_format for sample in self.samples
                     if sample.detected_text_format is not None), None)

    def resolve_text_format_to_read(self) -> Optional[TextFormat]:
        """
        The text format to read the samples again with, None when every one was
        read with what the template says (an override, else its own detected).
        """
        wanted = build_text_format(self.template)
        return wanted if any(_is_reread_needed(sample, wanted) for sample in self.samples) else None

    def _guess(self) -> None:
        """The first guess on the first sample: heading row, column layout and data kind."""
        sample = self.samples[0]
        for sheet in sample.sheet_names:
            rows = sample.rows_of(sheet) or ()
            heading = _guess_heading(rows)
            if heading is None:
                continue
            text = resolve_cell_text(rows[heading][0])
            self.layout_guess = _guess_layout(rows[heading])
            self.table = dataclasses.replace(
                self.table, heading_text=text, heading_number=heading + 1,
                find_by_number=bool(self.resolve_anchor_problem(text)), layout=self.layout_guess)
            kind = _guess_data_kind(rows[heading][0])
            if kind:
                self.data_kind_guess = (kind, text)
                self.answers = dataclasses.replace(self.answers, data_kind=kind)
            return

    def _apply_template(self, template: ImportTemplate) -> None:
        """Makes every answer and choice the template's, so every step shows its choices."""
        timed = template.data_kind == DATA_KIND_TIME_SIGNAL
        rate_from_text = isinstance(template.sample_rate, ChipRef)
        time_source = (TIME_FROM_COLUMN if template.time_column
                       else TIME_RATE_FROM_TEXT if rate_from_text else TIME_FIXED_RATE)
        self.answers = SampleAnswers(
            data_kind=template.data_kind, simulated=template.simulated,
            amplitude=template.fixed_source_amplitude or AMPLITUDE_FROM_HEADER,
            values_in_db=template.values_in_db, db_reference=template.db_reference,
            channel_type=template.channel_type,
            time_source=time_source if timed else TIME_FROM_COLUMN,
            sample_rate=0.0 if rate_from_text else float(template.sample_rate))
        self.table = TableChoices(
            heading_text=template.anchor_text, heading_number=template.heading_row or 1,
            find_by_number=not template.anchor_text, data_offset=template.data_offset, layout=template.layout,
            sheet_rule=template.sheet_rule, sheet_count=template.sheet_count, sheets=template.sheets,
            x_unit=template.x_unit, amplitude_unit=template.amplitude_unit, encoding=template.encoding,
            delimiter=template.delimiter, decimal_separator=template.decimal_separator)
        self.layout_guess = template.layout
        self._layout_chosen = True
        ordered = template.data_kind == DATA_KIND_ORDER_CUT
        self.roles = SampleRoles(
            name=template.channel_name, axis=template.axis,
            order=template.order if isinstance(template.order, ChipRef) else None,
            fixed_order=float(template.order) if ordered and not isinstance(template.order, ChipRef) else 0.0,
            sample_rate=template.sample_rate if rate_from_text else None, fields=template.metadata_fields)
        self._roles_chosen = True
        self.cuts = tuple((source.key, chip) for source in template.texts for chip in source.cut_chips)
        self.skipped_columns, self.speed_channel = template.skipped_columns, template.speed_channel
        self._name = (template.name, template.file_pattern)

    # ---- step 1: what it is -----------------------------------------------------------

    def answer(self, **fields) -> None:
        """Answers step 1's questions: any SampleAnswers fields, by name."""
        self.answers = dataclasses.replace(self.answers, **fields)

    def resolve_questions(self) -> Set[str]:
        """The questions that apply to the data kind; a time signal is a measurement, read in its own amplitude."""
        if self.answers.data_kind == DATA_KIND_TIME_SIGNAL:
            return {QUESTION_DATA_KIND, QUESTION_CHANNEL_TYPE, QUESTION_TIME}
        return {QUESTION_DATA_KIND, QUESTION_ORIGIN, QUESTION_VALUES, QUESTION_AMPLITUDE, QUESTION_CHANNEL_TYPE}

    def resolve_unanswered_questions(self) -> Set[str]:
        """The applying questions still without an answer; each one keeps Next off."""
        answers = self.answers
        unanswered = {QUESTION_ORIGIN: answers.simulated is None, QUESTION_AMPLITUDE: not answers.amplitude,
                      QUESTION_TIME: answers.time_source == TIME_FIXED_RATE and answers.sample_rate <= 0}
        return {question for question in self.resolve_questions() if unanswered.get(question, False)}

    @staticmethod
    def resolve_header_amplitude_problem(preview: Optional[SamplePreview]) -> str:
        """Why "from the header" cannot be the amplitude answer, blank when every amplitude header says it."""
        if preview is None or not preview.bare_amplitude_headers:
            return ""
        cells = ", ".join(f"'{cell}'" for cell in preview.bare_amplitude_headers[:3])
        return f"the amplitude header {cells} does not say RMS, Peak or Peak-to-Peak"

    # ---- step 2: the table --------------------------------------------------------------

    def choose_table(self, **fields) -> None:
        """Step 2's choices: any TableChoices fields, by name. A layout chosen here is kept when the heading moves."""
        if "layout" in fields:
            self._layout_chosen = True
            self._roles_chosen = False
            self.cuts = ()
        self.table = dataclasses.replace(self.table, **fields)

    def resolve_anchor_problem(self, text: str) -> str:
        """Why the heading row cannot be found by this first-cell text in every sample, blank when it can."""
        if not text.strip():
            return "the row's first cell is blank"
        if _is_number(text):
            return f"the row's first cell '{text}' is a number"
        probe = dataclasses.replace(self._draft(), anchor_text=text, heading_row=0, sheet_rule=SHEETS_ALL)
        for sample in self.samples:
            if not any(resolve_heading_row(rows, probe) is not None for _, rows in sample.sheets):
                return f"no row of {os.path.basename(sample.path)} starts with '{text}'"
        return ""

    def choose_heading_row(self, path: str, sheet: str, row: int) -> str:
        """
        Makes row `row` (from 0) of a sample's sheet the heading row, the data
        right below it. It is found by its first cell's text when every sample
        has a row starting with it, else by its number. Why not, blank when made.
        """
        rows = self._rows(path, sheet)
        if not 0 <= row < len(rows):
            return f"Sheet '{sheet}' has no row {row + 1}."
        text = resolve_cell_text(rows[row][0]) if rows[row] else ""
        self._roles_chosen = False      # other header rows: other chips
        self.cuts = ()
        if not self._layout_chosen:
            self.layout_guess = _guess_layout(rows[row])
        self.table = dataclasses.replace(
            self.table, heading_text=text, heading_number=row + 1, find_by_number=bool(self.resolve_anchor_problem(text)),
            data_offset=1, layout=self.table.layout if self._layout_chosen else self.layout_guess)
        return ""

    def choose_data_row(self, path: str, sheet: str, row: int) -> str:
        """Makes row `row` (from 0) of a sample's sheet the first data row; why not, blank when made."""
        heading = resolve_heading_row(self._rows(path, sheet), self.template)
        if heading is None:
            return f"Sheet '{sheet}' has no heading row yet: make a row the heading row first."
        if row <= heading:
            return f"The data starts below the heading row (row {heading + 1})."
        self.table = dataclasses.replace(self.table, data_offset=row - heading)
        return ""

    def find_heading_by_number(self, by_number: bool) -> str:
        """Finds the heading row by its number, or by its first cell's text; why not, blank when made."""
        if not by_number:
            problem = self.resolve_anchor_problem(self.table.heading_text)
            if problem:
                return f"The heading row cannot be found by its text: {problem}."
        self.table = dataclasses.replace(self.table, find_by_number=by_number)
        return ""

    def resolve_unit_problems(self, preview: SamplePreview) -> Tuple[str, str]:
        """Why the X unit and the amplitude unit must be chosen (not found, or differing between samples); blank when not."""
        def problem(what: str, chosen: str, units_of) -> str:
            if chosen:
                return ""
            found = [(os.path.basename(units.path), units_of(units)) for units in preview.units if units_of(units)]
            missing = [name for name, units in found if "unknown" in units]
            if missing:
                return f"The {what} unit is not in the heading row of {missing[0]}: choose it."
            if len({frozenset(units) for _, units in found}) > 1:
                listed = "; ".join(f"{', '.join(units)} in {name}" for name, units in found)
                return f"The {what} unit differs between the samples ({listed}): choose it."
            return ""

        return (problem("X", self.table.x_unit, lambda units: units.x_units),
                problem("amplitude", self.table.amplitude_unit, lambda units: units.amplitude_units))

    # ---- step 3: the roles -------------------------------------------------------------------

    @property
    def is_rate_from_text(self) -> bool:
        return self.answers.data_kind == DATA_KIND_TIME_SIGNAL and self.answers.time_source == TIME_RATE_FROM_TEXT

    def resolve_role_kinds(self) -> Tuple[str, ...]:
        """The roles of step 3's slots: the order only for an order cut, the sample rate only when it is in a text."""
        ordered = self.answers.data_kind == DATA_KIND_ORDER_CUT
        return tuple(kind for kind in CHIP_ROLE_KINDS
                     if (kind != ROLE_ORDER or ordered) and (kind != ROLE_SAMPLE_RATE or self.is_rate_from_text))

    def apply_chip_suggestion(self, chips: SampleChips) -> bool:
        """
        Guesses the roles from how these chips change, until the user gave a
        role (the guess is redone when the heading row or layout changes).
        Whether the roles changed.
        """
        if self._roles_chosen or not chips.channels:
            return False
        roles = resolve_role_suggestion(chips, self.answers.data_kind == DATA_KIND_ORDER_CUT, self.is_rate_from_text)
        if self.roles is not None:
            roles = dataclasses.replace(roles, fixed_order=self.roles.fixed_order)
        changed, self.roles = roles != self.roles, roles
        return changed

    def set_chip_role(self, kind: str, ref: ChipRef, chips: SampleChips, channel: int = 0) -> None:
        """
        Gives the chip `ref` names in channel `channel`'s text a role (ROLE_NAME, ROLE_AXIS, ROLE_ORDER,
        ROLE_SAMPLE_RATE), counted from the start or from the end (resolve_chip_anchor); its other roles stay.
        """
        anchored = resolve_chip_anchor(chips, kind, ref, channel)
        self._chosen_roles(lambda roles: roles.with_role(kind, anchored, chips))

    def count_chip_from_other_end(self, kind: str, ref: ChipRef, chips: SampleChips, channel: int = 0) -> None:
        """The role `kind` takes its chip `ref` counted from the other end of its text (as in channel `channel`)."""
        flipped = chips.resolve_flipped(ref, channel)
        if flipped is not None:
            self._chosen_roles(lambda roles: roles.with_ref_replaced(kind, ref, flipped))

    def remove_chip_role(self, kind: str, ref: ChipRef) -> None:
        """Takes this one role off the chip."""
        self._chosen_roles(lambda roles: roles.without_role(kind, ref))

    def set_field(self, field: MetadataField) -> str:
        """
        A metadata field from a chip (a field of the same name from the same chip is edited). Why it is
        refused, blank when it is added: a field has one source only, and an order cut has its
        order from the Order slot, not from a field "Order" (§1.234).
        """
        name = field.field.strip()
        if not name:
            return "Give the field a name."
        if self.answers.data_kind == DATA_KIND_ORDER_CUT and name.casefold() == "order":
            return "An order cut takes its order from the Order slot, not from a field 'Order'."
        roles = self.roles if self.roles is not None else SampleRoles()
        other = next((found for found in roles.fields if found.field.casefold() == name.casefold()
                      and found.chip != field.chip), None)
        if other is not None:
            return (f"The field '{other.field}' already takes its value from {resolve_text_source_label(other.chip)}"
                    f" ({resolve_chip_label(other.chip)}): a field has one source. Take that one off first.")
        self._chosen_roles(lambda current: current.with_field(dataclasses.replace(field, field=name)))
        return ""

    def remove_field(self, name: str) -> None:
        """Takes the metadata field of this name off its chip."""
        self._chosen_roles(lambda roles: roles.without_field(name))

    def move_name_chip(self, index: int, to: int) -> None:
        """Moves name chip `index` to the place `to`: every channel's name changes, and the template keeps the order."""
        self._chosen_roles(lambda roles: roles.with_name_moved(index, to))

    def set_chip_cuts(self, key: Tuple[str, int], chip: int, cuts: Sequence[ChipCut],
                      chips: Optional[SampleChips] = None) -> None:
        """
        The own cuts of delimiter chip `chip` of a text source (none: uncut). Its pieces are other chips, so
        every role of the chip is taken off -- also one counting from the end, by the `chips` it was given
        on; the other chips keep theirs.
        """
        others = tuple((found, own) for found, own in self.cuts if (found, own.chip) != (key, chip))
        self.cuts = others + (((key, ChipCuts(chip, tuple(cuts))),) if cuts else ())
        if self.roles is not None:
            usual = chips.resolve_usual_chip_count(key) if chips is not None else 0
            self.roles = self.roles.without_chip(key, chip, usual)

    def resolve_chip_cuts(self, key: Tuple[str, int], chip: int) -> Tuple[ChipCut, ...]:
        return next((own.cuts for found, own in self.cuts if found == key and own.chip == chip), ())

    def fix_order(self, order: float) -> None:
        """One order for every channel (0: none), used while no chip is the order."""
        self._chosen_roles(lambda roles: dataclasses.replace(roles, fixed_order=max(0.0, order)))

    def _chosen_roles(self, change) -> None:
        self.roles = change(self.roles if self.roles is not None else SampleRoles())
        self._roles_chosen = True

    # ---- step 4: duplicates ------------------------------------------------------------------

    def keep_duplicates(self, groups: Sequence[DuplicateGroup], *, picks=None, source_amplitude: str = "") -> None:
        """
        Writes the duplicate choice into the template: one copy kept of each group (the one `picks` names,
        group number -> copy number, else the first with this Source amplitude), the others left out as the
        sheets and channels it reads. Decided on the first sample, the one the groups were found on.
        """
        if not self.samples:
            return
        kept = build_template_keeping(self.template, self.samples[0], groups,
                                      resolve_kept_copies(groups, picks, source_amplitude))
        self.table = dataclasses.replace(self.table, sheet_rule=kept.sheet_rule, sheets=kept.sheets)
        self.skipped_columns = kept.skipped_columns

    # ---- step 4: the name --------------------------------------------------------------------

    def name_template(self, name: str, file_pattern: str) -> None:
        """The template's name and file pattern as the user wrote them; until then they are suggested."""
        self._name = (name, file_pattern)

    @property
    def suggested_name(self) -> Tuple[str, str]:
        return resolve_name_suggestion(self.sample_paths)

    # ---- the template ----------------------------------------------------------------------------

    @property
    def template(self) -> ImportTemplate:
        """The Import template the answers and choices make."""
        draft = self._draft()
        row_above = 0
        if self.table.layout == LAYOUT_XY_PAIRS and self.samples:
            sample = self.samples[0]
            heading = next((found for found in (resolve_heading_row(sample.rows_of(sheet) or (), draft)
                                                for sheet in resolve_read_sheets(sample.sheet_names, draft))
                            if found is not None), None)
            row_above = 1 if heading else 0
        roles = self.roles
        if roles is not None:
            rate = roles.sample_rate if self.is_rate_from_text and roles.sample_rate is not None else draft.sample_rate
            return dataclasses.replace(draft, texts=apply_chip_cuts(resolve_chip_texts(roles), self.cuts), channel_name=roles.name,
                                       axis=roles.axis, order=resolve_order_role(roles, self.answers.data_kind),
                                       sample_rate=rate, metadata_fields=roles.fields)
        return dataclasses.replace(draft, texts=(TextSource(SOURCE_HEADER, row_above, delimiters=""),),
                                   channel_name=(ChipRef(SOURCE_HEADER, row_above, 0),))

    def _draft(self) -> ImportTemplate:
        answers, table = self.answers, self.table
        timed = answers.data_kind == DATA_KIND_TIME_SIGNAL
        explicit = "" if answers.amplitude in ("", AMPLITUDE_FROM_HEADER) or timed else answers.amplitude
        name, file_pattern = self._name if self._name is not None else self.suggested_name
        return ImportTemplate(
            name=name, file_pattern=file_pattern,
            anchor_text="" if table.find_by_number else table.heading_text,
            heading_row=table.heading_number if table.find_by_number else 0,
            data_offset=table.data_offset, layout=table.layout,
            sheet_rule=table.sheet_rule, sheet_count=table.sheet_count, sheets=table.sheets,
            x_unit=table.x_unit, amplitude_unit=table.amplitude_unit,
            encoding=table.encoding, delimiter=table.delimiter, decimal_separator=table.decimal_separator,
            channel_name=(ChipRef(SOURCE_HEADER),), texts=(TextSource(SOURCE_HEADER, delimiters=""),), order=1.0,
            data_kind=answers.data_kind,
            simulated=False if timed else answers.simulated is not False,
            source_amplitude=explicit, fixed_source_amplitude=explicit,
            values_in_db=answers.values_in_db and not timed, db_reference=answers.db_reference if not timed else 0.0,
            channel_type=answers.channel_type, skipped_columns=self.skipped_columns, speed_channel=self.speed_channel,
            time_column=not timed or answers.time_source == TIME_FROM_COLUMN,
            sample_rate=answers.sample_rate if timed and answers.time_source == TIME_FIXED_RATE else 0.0)

    def _rows(self, path: str, sheet: str) -> Tuple[tuple, ...]:
        sample = next((sample for sample in self.samples if os.path.normcase(sample.path) == os.path.normcase(path)),
                      None)
        return (sample.rows_of(sheet) or ()) if sample is not None else ()

    # ---- what stops Next and Save -------------------------------------------------------------------

    def resolve_step_problem(self, step: int, preview: Optional[SamplePreview],
                             builtin_names: Optional[Iterable[str]] = None) -> str:
        """
        Why Next (Save on the last step) is off on `step`, blank when it is not;
        the problems of the steps before it count too. `preview` is the current
        preview, None while it is being read.
        """
        if not self.samples:
            return "Add a sample file."
        problem = self._samples_problem(preview)
        if problem or step == STEP_SAMPLES:
            return problem
        if preview is None:
            return _STALE_PREVIEW
        problem = self._table_problem(preview)
        if problem or step == STEP_TABLE:
            return problem
        problem = self._roles_problem()
        if problem or step == STEP_ROLES:
            return problem
        return self._save_problem(preview, builtin_names)

    def _samples_problem(self, preview: Optional[SamplePreview]) -> str:
        answers = self.answers
        unanswered = self.resolve_unanswered_questions()
        if QUESTION_TIME in unanswered:
            return "Give the sample rate in Hz."
        missing = [what for question, what in ((QUESTION_ORIGIN, "Simulation or Measurement"),
                                               (QUESTION_AMPLITUDE, "the amplitude in the file"))
                   if question in unanswered]
        if missing:
            return (f"Choose {' and '.join(missing)}: the file cannot tell, and a wrong choice would change "
                    f"the numbers unnoticed.")
        if QUESTION_AMPLITUDE not in self.resolve_questions():
            return ""
        header = self.resolve_header_amplitude_problem(preview)
        if answers.amplitude == AMPLITUDE_FROM_HEADER and header:
            return f"'From the header' does not fit: {header}."
        return ""

    def _table_problem(self, preview: SamplePreview) -> str:
        if not preview.channels:
            return "No channel is read from the samples: click the row number of the heading row in the preview."
        return next((problem for problem in self.resolve_unit_problems(preview) if problem), "")

    def _roles_problem(self) -> str:
        roles = self.roles
        if roles is None:
            return "The texts are still being split into chips."
        if not roles.name:
            return "Pick a chip for the channel name: + Pick, then click a text in the preview."
        if (self.answers.data_kind == DATA_KIND_ORDER_CUT and roles.order is None
                and roles.fixed_order <= 0):
            return "Pick the chip the order is in, or give one order for all channels."
        if self.is_rate_from_text and roles.sample_rate is None:
            return "Pick the chip the sample rate is in."
        return ""

    def resolve_fit_problem(self, preview: SamplePreview) -> str:
        """Why the template cannot be kept whatever its name (every step's problems, the file pattern, the fit)."""
        return self.resolve_step_problem(STEP_CHECK, preview, ())

    def _save_problem(self, preview: SamplePreview, builtin_names: Optional[Iterable[str]]) -> str:
        template = self.template
        problem = resolve_library_save_problem(template.name, builtin_names)
        if problem:
            return problem
        if not template.file_pattern.strip():
            return "Give the template a file name pattern."
        missed = [os.path.basename(path) for path in self.sample_paths if not resolve_template_name_fit(path, template)]
        if missed:
            return f"The file pattern '{template.file_pattern}' does not match the sample {missed[0]}."
        if preview.misfits:
            path, reason = preview.misfits[0]
            return f"{os.path.basename(path)} does not fit: {reason}"
        bad = [channel for channel in preview.channels if channel.problem]
        if bad:
            return (f"{len(bad)} channel(s) do not fit, e.g. {bad[0].name or 'a channel'} of "
                    f"{os.path.basename(bad[0].path)}: {bad[0].problem}")
        try:
            ImportTemplate.from_dict(template.to_dict())
        except ValueError as error:
            return str(error)
        return ""
