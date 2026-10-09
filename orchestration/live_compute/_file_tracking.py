"""Each source file's own tacho block and TrackingPlan bag inside one worker call."""

from io_modules.data_accessor import DataAccessor


class FileTracking:
    """
    The per-file tracking context one batch worker carries across its channels.

    A dropped or overlaid batch routinely spans several files. Tracking file B's
    vibration against file A's speed profile is silently wrong rather than an
    error (compute_order_cuts only checks sample count, which files from one
    test campaign share), so the tacho is read once PER FILE and never lent to
    another. The scratch bag is per file for the same reason: its channels
    build one TrackingPlan between them (#99), and another file builds its own.

    Lives for one worker call only, so it keeps every file it met -- unlike
    LiveOrderMemo's cross-job bag, which keeps only the latest (ADR §1.117).
    """

    def __init__(self):
        self._tacho_by_path: dict = {}
        self._scratch_by_path: dict = {}

    def seed_tacho(self, file_path, tacho_block) -> None:
        """Reuse a tacho block the dock already holds for `file_path`."""
        if tacho_block is not None:
            self._tacho_by_path[file_path] = tacho_block

    def tacho_for(self, file_path, run, tacho_meta):
        """`file_path`'s own tacho block, read from `run` the first time it is asked for."""
        tacho_block = self._tacho_by_path.get(file_path)
        if tacho_block is None:
            tacho_block = DataAccessor.fetch_channel_data(run, tacho_meta)
            self._tacho_by_path[file_path] = tacho_block
        return tacho_block

    def scratch_for(self, file_path) -> dict:
        """The TrackingPlan bag every channel of `file_path` shares."""
        return self._scratch_by_path.setdefault(file_path, {})
