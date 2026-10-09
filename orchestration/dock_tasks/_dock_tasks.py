# =====================================================================
# FILE: orchestration/dock_tasks/_dock_tasks.py
# =====================================================================
"""
`DockTasks`: runs a dock's background work on the `JobRunner` port and
delivers the result only while it is still wanted.
"""

import itertools
from typing import Callable, Dict, Optional, Set

from core.jobs import job_step
from orchestration.jobs import JobRunner

# What a dock task is for. Two tasks on one dock supersede each other only when
# they share a purpose, so the list is the answer to "which of a dock's tasks
# may cancel which".
#
# compute    -- open, refresh and cache lookup of the dock's own curve; also
#               the bulk overlay tab's first read
# drop       -- channels dropped onto the dock (and Refresh Last N, which
#               re-drops); never superseded, see _ADDITIVE_PURPOSES
# evaluation -- the Evaluation card's table over the dock's curves
PURPOSE_COMPUTE = "compute"
PURPOSE_DROP = "drop"
PURPOSE_EVALUATION = "evaluation"
_PURPOSES = (PURPOSE_COMPUTE, PURPOSE_DROP, PURPOSE_EVALUATION)

# Purposes whose tasks add to the dock rather than replace what it shows: a
# second drop is more curves, not a newer version of the first drop, so each
# task gets a slot of its own and only closing the dock stops it (#286).
_ADDITIVE_PURPOSES = (PURPOSE_DROP,)


def _slot_key(dock_id: str, purpose: str) -> str:
    return f"dock:{purpose}:{dock_id}"


class DockTasks:
    """
    "Run this for that dock, and hand me the result if it still matters."

    Two things make the answer "it does not": a newer task with the same
    purpose was started for the same dock (the runner supersedes the older
    job through its slot and drops its result -- except for a drop, where
    every task is delivered), or the dock is no longer open
    (`is_open(dock_id)` is false when the result lands). In either case
    neither `on_success` nor `on_error` is called.

    `on_success` / `on_error` run on the thread that called `run` -- the GUI
    thread in the application -- so they may draw and log; `fn` runs on the
    runner's thread and must take and return data only (§1.54).
    """

    def __init__(self, runner: JobRunner, is_open: Callable[[str], bool]):
        self._runner = runner
        self._is_open = is_open
        self._task_numbers = itertools.count()
        # Slots of additive tasks still in flight, per dock -- what `cancel`
        # has to reach once they no longer share one slot.
        self._additive_slots: Dict[str, Set[str]] = {}

    def run(self, dock_id: str, fn: Callable, *args, purpose: str,
            on_success: Callable[[object], None],
            on_error: Callable[[str], None],
            job_label: Optional[str] = None, progress_units: int = 1,
            **kwargs) -> None:
        """
        `progress_units` > 1 is a bulk task (several channels in one drop): it
        is loud, named `job_label`, and `fn` gets a `progress_fn(done, total)`
        that moves the job's counter channel by channel (#469).
        """
        if purpose not in _PURPOSES:
            raise ValueError(f"unknown dock task purpose {purpose!r}; expected one of {_PURPOSES}")

        slot_key = _slot_key(dock_id, purpose)
        if purpose in _ADDITIVE_PURPOSES:
            slot_key = f"{slot_key}:{next(self._task_numbers)}"
            self._additive_slots.setdefault(dock_id, set()).add(slot_key)

        def _landed():
            slots = self._additive_slots.get(dock_id)
            if slots is not None:
                slots.discard(slot_key)
                if not slots:
                    del self._additive_slots[dock_id]

        def _delivered(payload, _index):
            _landed()
            if self._is_open(dock_id):
                on_success(payload)

        def _failed(message, _index):
            _landed()
            if self._is_open(dock_id):
                on_error(message)

        # Quiet and on the interactive lane: a dock read is a click's worth of
        # work, not a batch -- it must not queue behind one (§1.13) and must
        # not put a status-bar line up for every tab switch.
        bulk = progress_units > 1
        self._runner.submit(
            job_label or f"Dock {purpose}",
            [job_step(f"{purpose} {dock_id}", fn, *args, **kwargs)],
            lane="interactive", slot_key=slot_key, quiet=not bulk,
            on_step=_delivered, on_error=_failed,
            **({"progress_keyword": "progress_fn", "step_sizes": [progress_units]}
               if bulk else {}),
        )

    def cancel(self, dock_id: str) -> None:
        """Stops every task still running for a dock that is being closed."""
        for purpose in _PURPOSES:
            if purpose not in _ADDITIVE_PURPOSES:
                self._runner.cancel_slot(_slot_key(dock_id, purpose))
        for slot_key in self._additive_slots.pop(dock_id, set()):
            self._runner.cancel_slot(slot_key)
