"""
What the Evaluation card shows and when the focused dock's Evaluation must run
(ADR §1.64 point 5, §1.255 point 5, §1.259 point 6).

The card is fed events -- a dock gained focus, the user chose an Evaluation or
edited its parameters, the dock's curves changed, the card became visible, a
run landed or failed -- and answers each with whether the Evaluation must run
now. It holds the focused dock's EvaluationConfig, whether a hidden card is
stale, and either the last table or the message shown in its place. The
widget only draws that and reports the events; reading and writing its
parameter widgets stays with it (§1.112).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from core.evaluation import EvaluationConfig, EvaluationTable
from signal_processing.evaluation import EVALUATIONS


NO_DOCK_MESSAGE = "No graph is open."
UNSUPPORTED_MESSAGE = "This dock has no curves Evaluation supports."
EVALUATING_MESSAGE = "Evaluating…"

# Shown in place of a table that holds no row for the current Amplitude.
_EMPTY_TABLE_MESSAGES = {
    "typed_orders": "No orders specified or found.",
    "dominant_orders": "No dominant orders found in the selected range.",
}
_EMPTY_TABLE_MESSAGE = "No evaluation results for the current parameters."

# Shown in place of the table while the parameters the user typed are invalid.
_INVALID_PARAMS_MESSAGES = {
    "typed_orders": (
        "Invalid orders: enter positive numbers with a decimal dot (.), "
        "separated by commas or semicolons."
    ),
}
_INVALID_PARAMS_MESSAGE = "Invalid parameters."


@dataclass(frozen=True)
class EvaluationRun:
    """One run the card asked for: which dock, which Evaluation, with what
    parameters. A result is accepted only for the run's own dock."""
    dock_id: str
    evaluation_name: str
    params: Dict[str, Any]


class EvaluationCardState:
    """The Evaluation card's state, without Qt. Every event that may need a
    run returns True when it must run now; a hidden card marks itself stale
    instead and runs when shown (§1.64 point 5)."""

    def __init__(self) -> None:
        self._dock_id: Optional[str] = None
        self._config: Optional[EvaluationConfig] = None
        self._stale = False
        self._params_invalid = False
        self._table: Optional[EvaluationTable] = None
        self._message: Optional[str] = NO_DOCK_MESSAGE

    # ---- what the card shows -----------------------------------------------

    @property
    def dock_id(self) -> Optional[str]:
        return self._dock_id

    @property
    def config(self) -> Optional[EvaluationConfig]:
        """The focused dock's EvaluationConfig as the card has changed it;
        None without a dock."""
        return self._config

    @property
    def evaluation_name(self) -> Optional[str]:
        return self._config.evaluation_name if self._config is not None else None

    @property
    def is_known(self) -> bool:
        """Whether this version knows the focused dock's Evaluation (§1.259 point 3)."""
        return self.evaluation_name in EVALUATIONS

    @property
    def stale(self) -> bool:
        return self._stale

    @property
    def table(self) -> Optional[EvaluationTable]:
        """The table to show, None while the card shows a message."""
        return self._table if self._message is None else None

    def message_for(self, amplitude_mode: str) -> Optional[str]:
        """The message the card shows in place of the table when its
        Amplitude switch is `amplitude_mode`; None when it shows the table."""
        if self._message is not None:
            return self._message
        if self._table is None or not self._table.rows_in(amplitude_mode):
            return _EMPTY_TABLE_MESSAGES.get(self.evaluation_name or "", _EMPTY_TABLE_MESSAGE)
        return None

    # ---- events --------------------------------------------------------------

    def focus(self, dock_id: Optional[str], config: Optional[EvaluationConfig], *, visible: bool) -> bool:
        """A dock gained focus; `dock_id` None means no dock the card can use."""
        if dock_id is None or config is None:
            self._dock_id = None
            self._config = None
            self._params_invalid = False
            self._stale = False
            self._show(NO_DOCK_MESSAGE)
            return False
        if dock_id != self._dock_id:
            # The previous dock's table must not stay copyable while this
            # dock's Evaluation still runs (§1.255 point 5).
            self._show(EVALUATING_MESSAGE)
        self._dock_id = dock_id
        self._config = config
        self._params_invalid = False
        if not self.is_known:
            self._stale = False
            self._show(self._unknown_message())
            return False
        return self._wants_run(visible)

    def choose_evaluation(self, evaluation_name: str, *, visible: bool) -> bool:
        """The user chose `evaluation_name`; it runs on this dock's remembered
        parameters for it, or its defaults (§1.259 point 1)."""
        if self._config is None:
            return False
        self._config = replace(self._config, evaluation_name=evaluation_name)
        self._params_invalid = False
        # The table of the Evaluation left behind is not what is now set.
        self._show(EVALUATING_MESSAGE)
        return self._wants_run(visible)

    def edit_params(self, params: Optional[Mapping[str, Any]], *, visible: bool) -> bool:
        """The user edited the selected Evaluation's parameters; None means
        what they typed is invalid. Invalid parameters keep the config as it
        was and show a message instead of the table (§1.259 point 4)."""
        if self._config is None or not self.is_known:
            return False
        if params is None:
            self._params_invalid = True
            self._show(_INVALID_PARAMS_MESSAGES.get(self.evaluation_name or "", _INVALID_PARAMS_MESSAGE))
            return False
        self._params_invalid = False
        self._config = self._config.with_params(params)
        return self._wants_run(visible)

    def set_respect_trace_filter(self, respect: bool, *, visible: bool) -> bool:
        if self._config is None:
            return False
        self._config = replace(self._config, respect_trace_filter=respect)
        return self._wants_run(visible)

    def set_metadata_columns(self, columns: Tuple[str, ...]) -> None:
        """Only the table's columns change; nothing runs."""
        if self._config is not None:
            self._config = replace(self._config, metadata_columns=tuple(columns))

    def content_changed(self, dock_id: Optional[str], *, visible: bool) -> bool:
        """`dock_id`'s curves or Trace-filter mask changed; only the focused
        dock's matter."""
        if dock_id is None or dock_id != self._dock_id:
            return False
        return self._wants_run(visible)

    def shown(self) -> bool:
        """The card became visible: runs when something changed while hidden."""
        return self._stale

    # ---- runs ----------------------------------------------------------------

    def resolve_run(self, block_kinds: Iterable[str]) -> Optional[EvaluationRun]:
        """The run to start for the focused dock whose curves have
        `block_kinds`, or None with the reason shown as the card's message."""
        self._stale = False
        if self._config is None or self._dock_id is None:
            self._show(NO_DOCK_MESSAGE)
            return None
        if not self.is_known:
            self._show(self._unknown_message())
            return None
        if self._params_invalid:
            return None
        accepted = EVALUATIONS[self._config.evaluation_name].accepted_block_kinds
        if not any(kind in accepted for kind in block_kinds):
            self._show(UNSUPPORTED_MESSAGE)
            return None
        return EvaluationRun(self._dock_id, self._config.evaluation_name, self._config.params)

    def land_table(self, run: EvaluationRun, table: EvaluationTable) -> bool:
        """`run` finished; True when the card now shows its table."""
        if not self._accepts(run):
            return False
        self._table = table
        self._message = None
        return True

    def land_failure(self, run: EvaluationRun, message: str) -> bool:
        """`run` failed; True when the card now shows the failure."""
        if not self._accepts(run):
            return False
        self._show(f"Evaluation failed: {message}")
        return True

    # ---- private -------------------------------------------------------------

    def _accepts(self, run: EvaluationRun) -> bool:
        return (
            run.dock_id == self._dock_id
            and run.evaluation_name == self.evaluation_name
            and not self._params_invalid
        )

    def _wants_run(self, visible: bool) -> bool:
        if not visible:
            self._stale = True
            return False
        return True

    def _show(self, message: str) -> None:
        self._table = None
        self._message = message

    def _unknown_message(self) -> str:
        return (
            f"Unknown Evaluation '{self.evaluation_name}': this version cannot run it. "
            "Choose another Evaluation."
        )
