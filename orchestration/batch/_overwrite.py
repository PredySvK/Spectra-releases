# =====================================================================
# FILE: orchestration/batch/_overwrite.py
# =====================================================================
"""
Finding overwrite candidates for save blocks in a workflow.

Pure lookup over the session: for every save block in a workflow graph, checks
whether a result set with identical parameters already exists in the project
-- or will, once a running or waiting Batch run has written it (#967, ADR
§1.268). Such an upcoming set has no id yet; a block told to overwrite it is
pointed at the set its key names when its own Batch run starts.

Enforces the invariant that a single existing result set can be claimed by at
most one save block (audit S1/1.1), avoiding multiple drafts staging into the
same result set folder where subsequent commits overwrite each other.

All internal documentation strings and variable labels are standardly written
in English.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Set, Tuple, TYPE_CHECKING

from core.workflow_graph import Workflow
from io_modules.result_cache import params_hash, result_params_from_block
from signal_processing.workflow import save_block_ids, spec_for

if TYPE_CHECKING:
    from session.project import ProjectSession

#: The note a set still to be written carries in the Overwrite question (#967).
NOTE_COMPUTING = "computing"
NOTE_WAITING = "waiting"


@dataclass(frozen=True)
class UpcomingTarget:
    """
    Which set a running or waiting Batch run will write: its Batch run's key,
    the run's place in that series and the save block. Once the run ends, its
    `BatchOutcome.written_ids` says which set id that is -- or that there is none.
    """
    series: int
    run: int
    block_id: str


@dataclass(frozen=True)
class UpcomingResultSet:
    """
    A result set a running or waiting Batch run will write: the key a duplicate
    is matched by (its kind and params hash, as for a saved set), the label it
    is planned under, whether its Batch run computes or waits, and `target`,
    which run writes it.
    """
    kind: str
    params_hash: str
    label: str
    note: str
    target: UpcomingTarget


@dataclass(frozen=True)
class OverwriteCandidate:
    """
    What a save block could overwrite: a saved result set (`result_set_id`), or
    one a Batch run ahead of it will write (`upcoming`, with `note` saying
    whether that Batch run computes or waits) -- its id is only known once that
    run has ended, so it is filled in when this one starts.
    """
    label: str
    result_set_id: Optional[str] = None
    note: Optional[str] = None
    upcoming: Optional[UpcomingTarget] = None

    @property
    def prompt_label(self) -> str:
        """The label as the Overwrite question lists it: "<label> (computing)" for one still to be written."""
        return f"{self.label} ({self.note})" if self.note else self.label


def _save_key(workflow: Workflow, block_id: str) -> Tuple[str, Dict]:
    """A save block's kind and params: what a duplicate is matched by."""
    return spec_for(workflow.block(block_id).block_type).produces, result_params_from_block(workflow, block_id)


def find_overwrite_candidates_by_workflow(
        session: "ProjectSession", workflows: Tuple[Workflow, ...],
        upcoming: Sequence[UpcomingResultSet] = ()) -> Tuple[Dict[str, OverwriteCandidate], ...]:
    """
    For every save block of each workflow, the result set with identical
    parameters it could overwrite, one `{block_id: candidate}` dict per workflow
    in `workflows`' order -- kept apart because runs may share block ids, as the
    result sets of one Compute Result Set over several Selections do.

    A saved set comes first (`session.find_duplicate_result_set`). Only when
    there is none is a set of `upcoming` -- one a running or waiting Batch run
    will write -- offered, in line order (#967).

    If two save blocks share identical parameters, both lookups point to the
    same result set. Letting both claim it would direct both drafts to the same
    result set folder, where the second commit would wipe the first's shards
    (audit 02, finding S1/1.1). Therefore a set -- saved or upcoming -- is
    claimed at most once across all workflows: the first save block gets it.
    """
    claimed: Set[str] = set()
    claimed_upcoming: Set[UpcomingTarget] = set()
    by_workflow = []
    for chain in workflows:
        duplicates: Dict[str, OverwriteCandidate] = {}
        for block_id in save_block_ids(chain):
            kind, params = _save_key(chain, block_id)
            existing = session.find_duplicate_result_set(params, kind=kind)
            if existing is not None:
                if existing.id not in claimed:
                    duplicates[block_id] = OverwriteCandidate(existing.label, existing.id)
                    claimed.add(existing.id)
                continue
            key_hash = params_hash(params) if upcoming else None
            found = next((candidate for candidate in upcoming
                          if candidate.target not in claimed_upcoming
                          and (candidate.kind, candidate.params_hash) == (kind, key_hash)), None)
            if found is not None:
                duplicates[block_id] = OverwriteCandidate(found.label, note=found.note, upcoming=found.target)
                claimed_upcoming.add(found.target)
        by_workflow.append(duplicates)
    return tuple(by_workflow)
