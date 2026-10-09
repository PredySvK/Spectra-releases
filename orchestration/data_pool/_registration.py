"""
Data Pool directory registration (audit 02 finding S1/1.3).

Finds the pool folders the project has not registered yet and registers them,
reading the disk in one JobRunner step so the GUI thread never does.
"""
import os
from dataclasses import replace
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.jobs import JobState, job_step
from core.project_model import DataRoot, SourceEntry
from io_modules.measurement_files import canonical_path
from io_modules.project_store import (
    DirectoryIndex,
    build_sources_by_path,
    read_file_listing,
    read_root_directories,
)

REGISTRATION_SLOT_KEY = "pool_registration"


def unregistered_pool_directories(
    pool_directories: Iterable[str],
    known_paths: Iterable[str],
) -> List[str]:
    """
    Return the pool directories that have no known source paths registered in the project.

    The check is performed per directory, not as a single global check over the
    whole pool: a project that already contains folder A must still catch up
    freshly pool-added folder B (audit 02, finding S1/1.3).
    """
    canonical_known = [canonical_path(p) for p in known_paths]
    unregistered: List[str] = []
    for directory in pool_directories:
        prefix = canonical_path(directory).rstrip(os.sep) + os.sep
        if any(path.startswith(prefix) for path in canonical_known):
            continue
        unregistered.append(directory)
    return unregistered


def _read_pool_registration(
    project_path: Optional[str],
    roots: Sequence[DataRoot],
    sources: Sequence[SourceEntry],
    pool_directories: Sequence[str],
) -> Tuple[Mapping[str, Optional[str]], Dict[str, DirectoryIndex]]:
    """Worker step: resolve the roots, then index every pool folder the
    project's sources do not reach."""
    root_directories = read_root_directories(project_path, roots)
    known = build_sources_by_path(roots, sources, root_directories)
    return root_directories, {
        directory: DirectoryIndex(read_file_listing(directory), root_directories)
        for directory in unregistered_pool_directories(pool_directories, known)
    }


def run_pool_registration(session, runner, pool_directories: Sequence[str], *,
                          on_ready: Callable[[dict], None],
                          log: Callable[[str], None]):
    """
    Registers the pool folders `session`'s project lacks, then calls
    `on_ready(sources_by_path)`. A failed read, or a project that changed
    meanwhile, is logged instead; a cancelled or superseded job ends quietly.
    """
    project = session.project
    project_path = session.path
    roots = tuple(replace(root) for root in project.data_roots)
    sources = tuple(replace(entry) for entry in project.sources)
    read = []

    def registered(record):
        if record.state != JobState.DONE or record.errors:
            return
        if session.project is not project or session.path != project_path:
            log("SYSTEM: Folder registration dropped -- the project changed while "
                "its folders were being read. Start the run again.")
            return
        root_directories, indexes = read[0]
        for directory, index in indexes.items():
            log(f"PROJECT: Registering '{directory}' with this project "
                f"before computing -- it was not part of it yet.")
            session.add_data_directory(directory, index=index)
        on_ready(session.sources_by_path(root_directories))

    return runner.submit(
        "Register Data Pool folders",
        [job_step("Register folders", _read_pool_registration,
                  project_path, roots, sources, tuple(pool_directories))],
        lane="batch", slot_key=REGISTRATION_SLOT_KEY, max_parallel=1,
        on_step=lambda payload, index: read.append(payload),
        on_error=lambda message, index: log(f"ERROR: Pool registration failed: {message}"),
        on_done=registered,
    )
