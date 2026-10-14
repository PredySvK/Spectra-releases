"""
Data pool orchestration: what an ingest reads, in what order, and what it
means -- plus which pool directories still need registration with the project.

The ingest use case (`PoolIngestUseCase`) submits one step per folder through
a `JobRunner`, folds each folder into the pool as it lands, and reports the
run as data: a `FolderReport` per folder and one `IngestOutcome` at the end.
Before reading it asks the **Source amplitude** question (RMS or Peak) once per
Imported-result reader that has files in the plan, through a callback the shell
supplies. `unregistered_pool_directories` answers the separate question of which pooled
directories the project does not know yet, and `save_metadata_schema` stores an
edited metadata schema in the project without committing other unsaved edits.

What does not belong here: Qt widgets, progress dialogs or prompt dialogs
(gui/), the application shell effects of an integration (`AppContext`,
ADR §1.69), pool state and project mutation themselves (session/), or raw file
scanning (io_modules/).
"""

from orchestration.data_pool._ingest import (
    INGEST_SLOT_KEY,
    FolderReport,
    IngestOutcome,
    IngestPlan,
    PoolIngestUseCase,
    plan_pool_ingest,
    plan_pool_refresh,
)
from orchestration.data_pool._source_amplitude import (
    SourceAmplitudeAsker,
    SourceAmplitudeQuestion,
)
from orchestration.data_pool._metadata_schema import save_metadata_schema
from orchestration.data_pool._registration import (
    REGISTRATION_SLOT_KEY,
    run_pool_registration,
    unregistered_pool_directories,
)

__all__ = [
    "INGEST_SLOT_KEY",
    "REGISTRATION_SLOT_KEY",
    "FolderReport",
    "IngestOutcome",
    "IngestPlan",
    "PoolIngestUseCase",
    "SourceAmplitudeAsker",
    "SourceAmplitudeQuestion",
    "plan_pool_ingest",
    "plan_pool_refresh",
    "save_metadata_schema",
    "run_pool_registration",
    "unregistered_pool_directories",
]
