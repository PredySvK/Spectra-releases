# =====================================================================
# FILE: session/result_sets.py
# =====================================================================
"""
Result-set lifecycle for ProjectSession: begin / commit / abort a batch write,
plus the label and duplicate bookkeeping around it.

Mixed into ProjectSession rather than built as a separate collaborator
(`session.result_sets.begin(...)`): the project rules name result sets, alongside
metadata, unit corrections and pool membership, as a project decision that
lives on ProjectSession. A collaborator would move that public surface off
the session and weaken the invariant; a mixin keeps every call site (and the
sentence in the project rules) unchanged while still splitting the file.

The disk side of a commit (where a draft is staged, the overwrite swap and
what is renamed back on failure) lives behind the io_modules.result_cache
facade (#172, #800): this module only decides the order -- manifest, project
model, project save -- and rolls the model back when the save fails.
"""

import os
from typing import Dict, List, Optional

from core.project_model import ResultSetRef
from io_modules.project_store import CACHE_DIR_NAME, cache_folder, names_a_cache_subfolder
from io_modules.result_cache import (
    create_draft, discard_draft, finish_swap_in, label_folder_exists, swap_in_draft,
    undo_swap_in, write_draft_manifest,
)

class ResultSetsMixin:
    """Result-set begin/commit/abort and label bookkeeping, mixed into ProjectSession."""

    # Counts commits, so a Save As copy plan can tell it went stale (#674).
    _result_set_commits = 0

    # ---- result sets ----------------------------------------------------

    def begin_result_set(self, kind: str, params: Dict, label: Optional[str] = None,
                         overwrite_result_set_id: Optional[str] = None,
                         compression: Optional[str] = None):
        """
        Opens a result set for writing and returns the draft to write into.

        Three calls rather than one (begin / write shards / commit) because a
        result set is written by many background steps, one measurement each
       : a spectrogram batch is gigabytes, so nothing may be held
        until the end. The draft is plain frozen data with no open handles, so
        it is safe to hand to workers; each of them calls
        write_result_shard with it.

        Requires an already-saved project: the cache lives in a folder next to
        the project file, so there is nowhere to put it before ensure_saved()
        has run.

        On overwrite the shards go to a staging folder and are swapped in by
        commit_result_set, so a failure part-way through leaves the existing
        result set exactly as it was.
        """
        if not self.has_file:
            raise ValueError("Project must be saved before a result set can be written.")

        from io_modules.result_cache import sanitize_result_set_label

        if overwrite_result_set_id:
            label = self._result_set_by_id(overwrite_result_set_id).label
        else:
            # The label is free user text (dialog QLineEdit) and becomes a
            # folder name a line below -- unsanitised it can escape the cache
            # dir or overwrite cache/scan/ (audit 02 finding 5.1). The dialogs
            # preview and block this, so a non-empty label that strips to
            # nothing here is a programming error, not a user typo.
            if label:
                clean = sanitize_result_set_label(label)
                if not clean:
                    raise ValueError(f"Result set name {label!r} has no usable characters.")
                label = clean
            label = self._unique_label(label) if label else self._next_result_set_label(kind)

        return create_draft(cache_folder(self._path), kind, label, params,
                            overwrite=bool(overwrite_result_set_id),
                            compression=compression)

    def commit_result_set(self, draft, entries: List[Dict], status: str = "complete",
                          all_channels: bool = False,
                          overwrite_result_set_id: Optional[str] = None) -> ResultSetRef:
        """
        Finishes a draft: writes its manifest, records it in the project, and
        saves -- as one unit.

        `entries` are the manifest entries the shard writes returned, in any
        order. `status` should be "partial" when some channels or sources
        failed while others succeeded: cache lookup refuses to treat a partial
        set as a hit, so mislabelling one "complete" would hand back coverage
        that was never computed.

        If the project save fails, everything is rolled back -- the result set
        is removed from the model again and the freshly written folder is
        deleted -- so a failure never leaves cache files on disk that the
        project does not know about, or vice versa.
        """
        write_draft_manifest(draft, entries, status, all_channels)
        self._result_set_commits = self._result_set_commits + 1

        source_ids = [entry.get("source_id", "") for entry in entries]
        if overwrite_result_set_id:
            result_set = self._commit_overwrite(
                overwrite_result_set_id, draft, status, all_channels, source_ids
            )
        else:
            result_set = ResultSetRef(
                label=draft.label, kind=draft.kind,
                file=os.path.join(CACHE_DIR_NAME, draft.label),
                params=dict(draft.params), params_hash=draft.params_hash,
                created_utc=draft.created_utc,
                status=status, source_ids=source_ids, all_channels=all_channels,
            )
            self._project.add_result_set(result_set)
            try:
                self._write()
            except Exception:
                self._project.result_sets.remove(result_set)
                undo_swap_in(draft)
                raise
        # Past the commit: the set is on disk and named in the
        # project file, so nothing that follows may undo it.
        after_write = [self._write_cache_index, self._remove_unreferenced_tab_cache]
        if overwrite_result_set_id:
            after_write.insert(0, lambda: finish_swap_in(draft))
        self._finish_write(*after_write)
        return result_set

    def _commit_overwrite(self, result_set_id: str, draft, status: str,
                          all_channels: bool, source_ids: List[str]) -> ResultSetRef:
        """
        Swaps a staged folder over the result set it replaces, then updates it.

        The label, id and file path are kept -- only the content, params_hash,
        source coverage and timestamp change -- so anything that already
        referenced this result set by id still finds it. The folder swap
        happens before the project save; if that save then fails, both are
        rolled back -- the model fields, and the folders (the retired set is
        renamed back and the staged data discarded) -- so the reverted ref
        names its own data again rather than the new numbers (#315). Should
        the folder restore itself fail, the swapped-in manifest still carries
        the new params_hash, and find_cached_result skips it as a mismatch.
        """
        existing = self._result_set_by_id(result_set_id)

        previous = (existing.params, existing.params_hash, existing.status,
                    existing.source_ids, existing.all_channels, existing.created_utc,
                    existing.file, existing.kind)

        existing.params = dict(draft.params)
        existing.params_hash = draft.params_hash
        existing.status = status
        existing.source_ids = source_ids
        existing.all_channels = all_channels
        existing.created_utc = draft.created_utc
        existing.kind = draft.kind
        existing.file = os.path.join(CACHE_DIR_NAME, existing.label)

        try:
            swap_in_draft(draft)
            self._write()
        except Exception:
            (existing.params, existing.params_hash, existing.status,
             existing.source_ids, existing.all_channels, existing.created_utc,
             existing.file, existing.kind) = previous
            undo_swap_in(draft)
            raise
        # The retired set is removed by the caller, after the commit.
        return existing

    def abort_result_set(self, draft) -> None:
        """
        Throws a draft away -- a cancelled batch, or one that produced nothing.

        Best-effort: a shard a reader still has open cannot be deleted on
        Windows, and a leftover folder with no manifest is inert (every reader
        treats a manifest-less folder as unreadable and the project never
        names it).
        """
        discard_draft(draft)

    def _write_cache_index(self) -> None:
        from io_modules.result_cache import build_cache_index, write_cache_index
        try:
            write_cache_index(self._path, build_cache_index(self._project, self._path))
        except OSError:
            pass    # the index is derived; a failure to write it costs a rebuild, not data

    def _result_set_by_id(self, result_set_id: str) -> ResultSetRef:
        existing = next((rs for rs in self._project.result_sets if rs.id == result_set_id), None)
        if existing is None:
            raise ValueError(f"No result set with id '{result_set_id}' to overwrite.")
        return existing

    def find_duplicate_result_set(self, params: Dict, kind: str = None) -> Optional[ResultSetRef]:
        """
        Looks for an existing result set of `kind` computed with exactly these
        settings, so the caller can offer to overwrite it instead of writing a
        near-duplicate. See
        io_modules.result_cache.find_duplicate_result_set for
        what "exactly" means.
        """
        from core.block_kinds import KIND_ORDER_CUT
        from io_modules.result_cache import find_duplicate_result_set as _find
        return _find(self._project, params, kind=kind or KIND_ORDER_CUT)

    def _label_is_taken(self, label: str) -> bool:
        """
        Whether a result set may not be written under this label.

        The cache folder is checked as well as the project's own list, because
        the label decides the folder name and the two can legitimately disagree:
        project_store creates the cache folder eagerly so a pre-computed cache
        can be copied in before anything has been calculated, and such a file
        is on disk without any ResultSetRef naming it. Going by the list alone,
        the first Calculate & Save Data would overwrite it.

        The cache's own subfolders are refused outright: scan caches live in
        `cache/scan/` (§1.22) and the Tab cache in `cache/tabs/` (§1.178), so
        a result set that happened to be labelled "scan" or "tabs" -- in any
        case, the folder names are case-insensitive on Windows -- would write
        its shards straight over them.
        """
        if names_a_cache_subfolder(label):
            return True
        if any(rs.label == label for rs in self._project.result_sets):
            return True
        if not self._path:
            return False
        return label_folder_exists(os.path.join(cache_folder(self._path), label))

    def _next_result_set_label(self, prefix: str) -> str:
        """First unused "{prefix}_vNN" label, so repeated saves auto-version."""
        n = 1
        while self._label_is_taken(f"{prefix}_v{n:02d}"):
            n += 1
        return f"{prefix}_v{n:02d}"

    def _unique_label(self, candidate: str) -> str:
        """
        Disambiguates a caller-supplied label that already exists, so saving
        the same selection twice never silently overwrites the first result
        set -- it appends "_2", "_3", ... instead.
        """
        if not self._label_is_taken(candidate):
            return candidate
        n = 2
        while self._label_is_taken(f"{candidate}_{n}"):
            n += 1
        return f"{candidate}_{n}"
