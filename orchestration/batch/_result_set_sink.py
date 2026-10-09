# =====================================================================
# FILE: orchestration/batch/_result_set_sink.py
# =====================================================================
"""
Where a batch's output goes once the workers have produced it
(ARCHITECTURE_DECISIONS §1.6 phase 6, §1.21).

There is one sink now, for every kind. Before §1.21 the result cache was
order-cut shaped, so a spectrum or spectrogram chain computed correctly and was
then dropped by a DiscardSink; the cache stores whatever core/block_kinds.py
registers, so that branch is gone and with it the idea that some results are
second-class.

The sink no longer carries data. Each background step writes its own
measurement's shard (ADR §1.21: the unit written whole is one measurement, so a
gigabyte-scale spectrogram batch is never held in memory) and returns only the
manifest entry; this collects those entries and, at the end, commits the draft
-- writing `_set.json`, registering the ResultSetRef and saving the project as
one unit.

Lives in orchestration/batch rather than in core/: it calls ProjectSession
persistence, which is application orchestration, not pure data. Log messages
are returned as data so the GUI runner owns their delivery. signal_processing/
stays free of it.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Any, Dict, List, Optional


class ResultSetSink:
    """
    Collects the manifest entries of a batch and commits them as one result set.

    `add` is called on the GUI thread once per finished measurement, with what
    that measurement's worker already wrote to disk. Nothing is buffered but
    names and numbers, so a cancelled batch costs the shards on disk (deleted by
    `abort`) rather than a lost heap of arrays.
    """

    def __init__(self, session, draft, all_channels: bool = False,
                 overwrite_result_set_id: Optional[str] = None,
                 what: str = "Run workflow"):
        self.session = session
        self.draft = draft
        self.all_channels = all_channels
        self.overwrite_result_set_id = overwrite_result_set_id
        self.what = what
        # What the committed set is actually called. Differs from the draft's
        # label on an overwrite, where the existing set keeps its own name.
        self.result_label: str = draft.label
        self._entries: List[tuple[int, Dict[str, Any]]] = []
        self._auto_index: int = 0
        # Files whose Overall Level F max was clipped to their Nyquist: one
        # summary line at the end, not one per file (§1.62 point 9, #131).
        self._f_stop_clipped_files: int = 0

    @property
    def label(self) -> str:
        return self.draft.label

    def add(self, entry: Optional[Dict[str, Any]], index: Optional[int] = None,
            f_stop_clipped: bool = False) -> None:
        """Records one written shard. `None` means the step produced nothing.

        If `index` is provided, entries are sorted by `index` upon `finish`,
        ensuring deterministic order regardless of thread completion timing (#375).
        `f_stop_clipped` says this file's F max was clipped to its Nyquist.
        """
        if entry:
            self._f_stop_clipped_files += bool(f_stop_clipped)
            if index is None:
                index = self._auto_index
                self._auto_index += 1
            self._entries.append((index, entry))

    def abort(self) -> None:
        """Throws the draft away -- a cancelled batch writes no result set."""
        self.session.abort_result_set(self.draft)

    def finish(self, status: str) -> tuple[bool, List[str]]:
        """
        Commits the result set. Returns whether anything was written and messages.

        A batch whose every file failed is aborted rather than committed: an
        empty result set would still show up in the Compare tab and in cache
        lookup as a set that exists and covers nothing.
        """
        if not self._entries:
            self.abort()
            return False, [
                f"WARNING: {self.what} produced no results -- nothing was written."
            ]

        entries = [entry for _, entry in sorted(self._entries, key=lambda item: item[0])]

        try:
            result_set = self.session.commit_result_set(
                self.draft, entries, status=status,
                all_channels=self.all_channels,
                overwrite_result_set_id=self.overwrite_result_set_id,
            )
        except (OSError, ValueError) as error:
            self.abort()
            return False, [f"ERROR: {self.what} failed to write: {error}"]

        self.result_label = result_set.label
        channel_count = sum(len(entry.get("channels") or []) for entry in entries)
        verb = "Overwrote" if self.overwrite_result_set_id else "Saved"
        suffix = " -- PARTIAL: some files failed, see log above." if status == "partial" else ""
        messages = [
            f"PROJECT: {verb} result set '{result_set.label}' ({len(entries)} file(s), "
            f"{channel_count} channel(s)).{suffix}"
        ]
        if self._f_stop_clipped_files:
            messages.append(
                f"WARNING: {self.what} -- Overall Level F max clipped to the file's "
                f"Nyquist in {self._f_stop_clipped_files} of {len(entries)} file(s)."
            )
        return True, messages

