"""
Data pool orchestration: what an ingest reads, in what order, and what it
means -- plus which pool directories still need registration with the project.

The ingest use case (`PoolIngestUseCase`) runs one `IngestRequest` at a time --
an **Add**, a **Refresh** or a **Template edit** (`IngestKind`), the one concept
every difference between runs follows from. It plans the run on a worker,
submits one step per folder through a `JobRunner`, folds each folder into the
pool as it lands, and reports the run as data: a `FolderReport` per folder and
one `IngestOutcome` at the end. The project is not changed before the reading
starts, so a cancelled question leaves it as it was.
The questions go to the shell through `IngestAskers`. Before reading a run asks
the **Source amplitude** question (RMS or Peak) once per Imported-result reader
that has files in the plan; an Add with a library template that differs from
the project's copy asks whether to replace the copy, before planning; a file that fits several **Import templates** is asked about the same
way, and a file that fits none of the templates its name belongs to comes back
as a **Misfit** in the run's outcome instead of being left out silently.
The order of an Import template edit -- the misfit report, the wizard, the
consequence summary, the library offer -- is here too (`plan_template_edit`,
`plan_follow_up`); it ends in one run that replaces the project's copy and
re-reads only the files that copy reads. When an ingest finishes it starts the `MissingMeasurementCheck`,
which also runs after a project's pool is restored and tells the pool which
of its measurements are Missing measurements, on a worker.
`unregistered_pool_directories` answers the separate question of which pooled
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
    plan_ingest_run,
    plan_pool_ingest,
    plan_pool_refresh,
)
from orchestration.data_pool._ingest_request import (
    EditedTemplate,
    IngestAskers,
    IngestKind,
    IngestRequest,
)
from orchestration.data_pool._missing_measurement_check import (
    MissingCheckOutcome,
    MissingMeasurementCheck,
)
from orchestration.data_pool._source_amplitude import (
    SourceAmplitudeAsker,
    SourceAmplitudeQuestion,
)
from orchestration.data_pool._template_assignment import (
    ImportTemplateAsker,
    Misfit,
    TemplateQuestion,
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
    "EditedTemplate",
    "FolderReport",
    "IngestAskers",
    "IngestKind",
    "IngestOutcome",
    "IngestRequest",
    "ImportTemplateAsker",
    "IngestPlan",
    "Misfit",
    "MissingCheckOutcome",
    "MissingMeasurementCheck",
    "PoolIngestUseCase",
    "SourceAmplitudeAsker",
    "SourceAmplitudeQuestion",
    "TemplateQuestion",
    "plan_ingest_run",
    "plan_pool_ingest",
    "plan_pool_refresh",
    "save_metadata_schema",
    "run_pool_registration",
    "unregistered_pool_directories",
]
