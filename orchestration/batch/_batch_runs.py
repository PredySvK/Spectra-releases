"""
The Batch run computing now and the ones waiting behind it.

A Batch run is everything one click started: a series of `WorkflowChainBatch`,
planned in full at the click. A new one never stops the running one by itself;
the caller asks the user first and says `wait` or not:

- `wait` while a Batch run computes or waits: the new one goes to the end of
  the line, whole;
- otherwise the running one is interrupted (its job ends SUPERSEDED and writes
  nothing), every waiting one is dropped, and the new one starts at once.

This is not a second job runner: it holds only what has not been handed to the
job runner yet and hands each series, when its turn comes, to the same batch
slot through `run_chain_batches`. Nothing here reads the disk or plans again:
a waiting Batch run computes exactly the plans it was given. The one check at
its turn is the project -- a waiting Batch run of another project is dropped,
each of its runs reporting "not started -- the project changed".

The waiting ones are listed for the Jobs panel (`waiting`, #966): they are not
jobs yet, so the job runner does not know them. One can be cancelled on its
own; the others keep their place.

The result sets they will write are listed too (`upcoming_result_sets`, #967),
so the Overwrite question of a new click can offer them. A Batch run told to
overwrite one gets that set's id at its start -- the id that very run reported
it wrote (`BatchOutcome.written_ids`); none written means it saves as a new set.

New, Open, Save As and closing the window ask Wait / Interrupt / Cancel too
(#968). Wait hands the action to `run_when_idle`: it runs once the whole line
has finished -- Batch runs put to wait after it included. Only one action
waits; a later one replaces it, and `interrupt` drops it.
"""
import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Optional, Sequence, TYPE_CHECKING

from core.jobs import CancelToken, JobState
from orchestration.jobs import JobRunner
from ._chains import (
    _PROJECT_CHANGED_WHY, _SUPERSEDED_WHY, WorkflowChainBatch, _ProjectStamp, _report_unstarted,
    build_upcoming_result_sets, resolve_upcoming_overwrites, run_chain_batches,
)
from ._overwrite import NOTE_COMPUTING, NOTE_WAITING, UpcomingResultSet, UpcomingTarget
from ._workflow_run import BatchOutcome, supersede_running_batch

#: Why a waiting run never started when the user cancelled it in the Jobs panel.
_CANCELLED_WHY = "cancelled while it waited"

if TYPE_CHECKING:
    from session.project import ProjectSession


@dataclass
class _Series:
    """One Batch run, frozen at the click: its plans, its project and its settings."""
    chains: tuple[WorkflowChainBatch, ...]
    session: "ProjectSession"
    started_under: _ProjectStamp
    compression: Any
    on_started: Optional[Callable[[], None]]
    on_finished: Optional[Callable[[BatchOutcome], None]]
    key: int = 0
    cancel: CancelToken = field(default_factory=CancelToken)
    unended: Deque[int] = field(default_factory=deque)
    ended: set = field(default_factory=set)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(chain.batch.label for chain in self.chains if chain.batch.runnable)

    def plan_report_order(self) -> None:
        """
        Expect its outcomes in the order a submitted series reports them
        (§1.238): the refused runs first, then the runnable ones in order.
        """
        indices = range(len(self.chains))
        self.unended = deque([i for i in indices if not self.chains[i].batch.runnable]
                             + [i for i in indices if self.chains[i].batch.runnable])

    def take_ended(self) -> int:
        """The index of the run whose outcome just arrived."""
        index = self.unended.popleft()
        self.ended.add(index)
        return index

    @property
    def name(self) -> str:
        return ", ".join(f"'{label}'" for label in self.labels)


@dataclass(frozen=True)
class WaitingBatchRun:
    """
    One waiting Batch run as a list shows it: `key` to cancel it by, and the
    labels of the runs it will compute, in order.
    """
    key: int
    labels: tuple[str, ...]

    @property
    def job_label(self) -> str:
        """Named like the job it becomes (`BatchPlan.job_label`), all its runs listed."""
        return "Compute " + ", ".join(f"'{label}'" for label in self.labels)


class BatchRuns:
    """
    The one line of Batch runs of a window: the running one and the waiting
    ones, in click order. `on_finished` hears one `BatchOutcome` per run of
    every series, a dropped one included. `on_waiting_changed`
    hears every change of `waiting`.
    """

    def __init__(self, job_runner: JobRunner, *,
                 on_message: Optional[Callable[[str], None]] = None,
                 on_finished: Optional[Callable[[BatchOutcome], None]] = None,
                 on_waiting_changed: Optional[Callable[[], None]] = None):
        self._job_runner = job_runner
        self._on_message = on_message
        self._on_finished = on_finished
        self._on_waiting_changed = on_waiting_changed
        self._running: Optional[_Series] = None
        self._waiting: Deque[_Series] = deque()
        self._keys = itertools.count(1)
        # The set id each ended run's save block wrote, for a waiting Batch
        # run told to overwrite it (#967); emptied once the line is idle.
        self._written: Dict[UpcomingTarget, str] = {}
        # The project or window action told to wait for the line (#968).
        self._when_idle: Optional[Callable[[], None]] = None

    @property
    def busy(self) -> bool:
        """Whether a Batch run computes or waits -- the moment to ask Wait / Interrupt."""
        return self._running is not None or bool(self._waiting)

    @property
    def waiting(self) -> tuple[WaitingBatchRun, ...]:
        """The waiting Batch runs, the next to start first."""
        return tuple(WaitingBatchRun(series.key, series.labels) for series in self._waiting)

    @property
    def upcoming_result_sets(self) -> tuple[UpcomingResultSet, ...]:
        """
        The result sets the running Batch run (its runs not ended yet) and the
        waiting ones will write, in line order -- for the Overwrite question of
        a new click (#967).
        """
        running = self._running
        upcoming = () if running is None else build_upcoming_result_sets(
            running.chains, series=running.key, note=NOTE_COMPUTING, ended=frozenset(running.ended))
        for series in self._waiting:
            upcoming += build_upcoming_result_sets(series.chains, series=series.key, note=NOTE_WAITING)
        return upcoming

    def cancel_waiting(self, key: int) -> bool:
        """
        Drop one waiting Batch run: each of its runs reports "not started --
        cancelled while it waited" (§1.238); the running one and the other
        waiting ones keep their place. False when `key` no longer waits --
        its turn came, or it was dropped already.
        """
        series = next((series for series in self._waiting if series.key == key), None)
        if series is None:
            return False
        self._waiting.remove(series)
        self._waiting_changed()
        _report_unstarted(series.chains, JobState.CANCELLED, _CANCELLED_WHY,
                          lambda outcome: self._report(series, outcome))
        return True

    def run_when_idle(self, name: str, action: Callable[[], None]) -> None:
        """
        Run `action` once no Batch run computes or waits any more -- the Wait
        answer of New, Open, Save As or closing the window (#968). `name` says
        what waits in the System Log, as an imperative ("close Spectra"). It replaces an action that
        waited already; with the line idle it runs at once.
        """
        if not self.busy:
            action()
            return
        if self._when_idle is not None:
            self._say("SYSTEM: The action that waited for the Batch runs was replaced.")
        self._when_idle = action
        self._say(f"SYSTEM: Waiting to {name} -- once every Batch run has finished.")

    def interrupt(self) -> None:
        """
        Stop the running Batch run and drop every waiting one -- the Interrupt
        answer of New, Open, Save As or closing the window (#968). Nothing they
        computed is written; each run reports one outcome (§1.238). An action
        waiting for the line is dropped too: the user chose to act now.
        """
        if self.busy:
            self._say("SYSTEM: Batch runs interrupted.")
        self._interrupt()

    def start(self, chains: Sequence[WorkflowChainBatch], session: "ProjectSession", *, wait: bool,
              compression=None, on_started: Optional[Callable[[], None]] = None,
              on_finished: Optional[Callable[[BatchOutcome], None]] = None) -> None:
        """
        Start a planned Batch run: at once, or behind the others when `wait` and
        something computes or waits. `on_started` is called right before the
        series is handed to the job runner -- now or when its turn comes --
        and so before any of its runs reports. `on_finished` hears the outcome
        of each of its own runs, after the line's listener -- also when the
        series is dropped before it ever started -- so a status line never has
        to tell its runs from others by label.

        A series with nothing runnable reports its runs at once and touches
        neither the running Batch run nor the waiting ones (§1.264).
        """
        series = _Series(tuple(chains), session, _ProjectStamp.of(session), compression,
                         on_started, on_finished, key=next(self._keys))
        if not any(chain.batch.runnable for chain in series.chains):
            if on_started is not None:
                on_started()
            run_chain_batches(series.chains, session, self._job_runner, compression=compression,
                              on_message=self._on_message,
                              on_finished=lambda outcome: self._report(series, outcome))
            return
        if wait and self.busy:
            self._waiting.append(series)
            self._waiting_changed()
            self._say(f"SYSTEM: Batch run {series.name} waiting -- it starts once the Batch runs before it finish.")
            return
        self._interrupt()
        self._submit(series)

    def _interrupt(self) -> None:
        """Stop the running Batch run and drop every waiting one, and the action waiting for them."""
        if self._when_idle is not None:
            self._when_idle = None
            self._say("SYSTEM: The action that waited for the Batch runs was dropped -- they were interrupted.")
        dropped = list(self._waiting)
        self._waiting.clear()
        if dropped:
            self._waiting_changed()
        running, self._running = self._running, None
        if running is not None:
            # The token keeps its chains not yet submitted from starting; the
            # slot stops its job. `run_batch` empties the slot again before the
            # new run opens a draft (§1.71).
            running.cancel.cancel()
            supersede_running_batch(self._job_runner)
        for series in dropped:
            _report_unstarted(series.chains, JobState.SUPERSEDED, _SUPERSEDED_WHY,
                              lambda outcome, series=series: self._report(series, outcome))

    def _submit(self, series: _Series) -> None:
        # The sets it was to overwrite while a run ahead still wrote them get
        # their ids now -- the one thing settled at the start, not the click.
        series.chains, messages = resolve_upcoming_overwrites(series.chains, self._written)
        for message in messages:
            self._say(message)
        self._running = series
        series.plan_report_order()
        if series.on_started is not None:
            series.on_started()
        run_chain_batches(series.chains, series.session, self._job_runner, compression=series.compression,
                          on_message=self._on_message, on_finished=lambda outcome: self._finished(series, outcome),
                          cancel=series.cancel)

    def _finished(self, series: _Series, outcome: BatchOutcome) -> None:
        index = series.take_ended()
        for block_id, result_set_id in outcome.written_ids:
            self._written[UpcomingTarget(series.key, index, block_id)] = result_set_id
        try:
            self._report(series, outcome)
        finally:
            # A late end of an interrupted series is no longer the running one.
            if not series.unended and self._running is series:
                self._running = None
                self._start_next()
            if not self.busy:
                # Nothing waits that could still be aimed at a set written so far.
                self._written.clear()
                self._run_idle_action()

    def _start_next(self) -> None:
        if not self._waiting:
            return
        try:
            while self._waiting:
                series = self._waiting.popleft()
                if series.started_under.changed_in(series.session):
                    _report_unstarted(series.chains, JobState.CANCELLED, _PROJECT_CHANGED_WHY,
                                      lambda outcome, series=series: self._report(series, outcome))
                    continue
                self._say(f"SYSTEM: Batch run {series.name} started -- its turn came.")
                self._submit(series)
                return
        finally:
            # Last, so a broken list listener cannot keep the next one from starting.
            self._waiting_changed()

    def _run_idle_action(self) -> None:
        action, self._when_idle = self._when_idle, None
        if action is not None:
            action()

    def _report(self, series: _Series, outcome: BatchOutcome) -> None:
        """The line's listener, then the series' own; a broken first one does not silence the second."""
        try:
            if self._on_finished is not None:
                self._on_finished(outcome)
        finally:
            if series.on_finished is not None:
                series.on_finished(outcome)

    def _waiting_changed(self) -> None:
        if self._on_waiting_changed is not None:
            self._on_waiting_changed()

    def _say(self, message: str) -> None:
        if self._on_message is not None:
            self._on_message(message)
