"""`TabCacheFiles`: the Tab cache file of every curve of an open tab -- its name and its write."""

import dataclasses
from typing import Callable, Dict, Iterable, Optional, Tuple

from io_modules.tab_cache import build_tab_cache_name, write_tab_cache_file
from orchestration.tab_cache._held_writes import HeldTabCacheWrite, HeldTabCacheWrites
from orchestration.tab_cache._tab_cache_plan import TabCacheWrite, plan_tab_cache_write
from session.open_tabs import TraceSpec
from session.tab_cache import build_referenced_tab_cache_names


@dataclasses.dataclass(frozen=True)
class TabCacheCurve:
    """
    "This curve of this tab": the tab's `dock_id` plus, for a dropped
    channel, its `channel_key` (`build_channel_key` of its file and channel
    index); no `channel_key` is the tab's base curve. One key for a curve's
    Tab cache file name and for its held write.
    """
    dock_id: str
    channel_key: Optional[Tuple[str, int]] = None


class TabCacheFiles:
    """
    The one home of the Tab cache lifecycle of the open tabs' curves.

    Names: a name is stored the moment its write starts (so a Save made
    meanwhile already names it), kept when a curve is shown from its file,
    and taken by the capture of the open tabs for a Save.

    Writes: with a project folder a curve's file is planned and written on a
    dock task at once; an Untitled project has no folder, so the write is
    held (a newer result of the same curve replaces it) until the first
    Save, which writes only the curves the saved project names. A failed
    write forgets the name unless a newer write replaced it, marks the
    project as changed when the saved project names the file, and logs a
    warning. Closing a tab drops its names and held writes.

    Ports: `start_write(dock_id, fn, *args, on_error)` runs `fn` as a dock
    task of purpose Tab cache; `writes_in_flight()` counts those not landed
    yet; `project_path()` is None while Untitled; `saved_open_tabs()` is the
    saved project's open tabs (None without a session);
    `mark_view_changed()`; `log(text)`; `is_open(dock_id)` tells a closed
    tab; `write_file(path, blocks, recipe)` is the file write itself.
    """

    def __init__(self, *, start_write: Callable, writes_in_flight: Callable[[], int],
                 project_path: Callable[[], Optional[str]],
                 saved_open_tabs: Callable[[], Optional[Iterable[dict]]],
                 mark_view_changed: Callable[[], None], log: Callable[[str], None],
                 is_open: Callable[[str], bool],
                 write_file: Callable = write_tab_cache_file):
        self._names: Dict[TabCacheCurve, str] = {}
        self._held = HeldTabCacheWrites()
        self._start_write = start_write
        self._writes_in_flight = writes_in_flight
        self._project_path = project_path
        self._saved_open_tabs = saved_open_tabs
        self._mark_view_changed = mark_view_changed
        self._log = log
        self._is_open = is_open
        self._write_file = write_file

    def name(self, curve: TabCacheCurve) -> Optional[str]:
        """The name of `curve`'s Tab cache file; None when it has none."""
        return self._names.get(curve)

    def store(self, curve: TabCacheCurve, name: Optional[str]) -> None:
        """`curve` names `name` from now on, replacing an older name; None forgets it."""
        if name:
            self._names[curve] = name
        else:
            self._names.pop(curve, None)

    def forget(self, curve: TabCacheCurve, name: str) -> None:
        """`curve` stops naming `name` -- a file that was not written -- unless
        a newer name has replaced it meanwhile."""
        if self._names.get(curve) == name:
            del self._names[curve]

    def keep(self, curve: TabCacheCurve, *, channel_name: str, blocks, recipe: Optional[dict],
             from_tab_cache: bool = False, saved_name: Optional[str] = None) -> None:
        """
        `curve` landed a result. Shown from its Tab cache file, it keeps
        `saved_name` and writes nothing; otherwise the result is written (or
        held while Untitled) and its name is stored at once. `saved_name` is
        also the name a restored curve saved but whose file could not be
        read: the write takes it over.
        """
        if from_tab_cache:
            self.store(curve, saved_name)
            return
        write = plan_tab_cache_write(
            self._project_path(), curve.dock_id, channel_name, saved_name=saved_name)
        # An Untitled project names the file in the shape a written one has,
        # so the first Save already names it.
        name = write.name if write is not None else build_tab_cache_name(curve.dock_id, channel_name)
        held = HeldTabCacheWrite(
            dock_id=curve.dock_id, name=name, channel_name=channel_name, blocks=tuple(blocks),
            recipe=recipe, on_failed=lambda failed: self.forget(curve, failed))
        self.store(curve, name)
        if write is None:
            self._held.hold(curve, held)
        else:
            self._start(write, held)

    def write_held(self) -> None:
        """After a Save: what the project held while it was Untitled goes to
        disk now -- only the curves the saved project names, and not those of
        a tab that was closed."""
        project_path = self._project_path()
        if not project_path or not len(self._held):
            return
        names = build_referenced_tab_cache_names(self._saved_open_tabs() or ())
        for held in self._held.take(names):
            if not self._is_open(held.dock_id):
                continue
            write = plan_tab_cache_write(
                project_path, held.dock_id, held.channel_name, saved_name=held.name)
            if write is not None:
                self._start(write, held)

    def has_writes_in_flight(self) -> bool:
        """Whether a Tab cache write has not landed yet."""
        return bool(self._writes_in_flight())

    def restore_tab(self, dock_id: str, traces: Iterable[TraceSpec]) -> None:
        """
        A tab rebuilt from its saved `traces`: its base curve names the file
        it was saved with. A dropped channel's name comes back with its
        re-drop (`TAB_CACHE_KEY` of its descriptor), which knows its channel
        key.
        """
        base = next((trace for trace in traces if trace.is_base), None)
        self.store(TabCacheCurve(dock_id), base.tab_cache_file if base is not None else None)

    def dropped_channel_names(self, dock_id: str) -> Dict[Tuple[str, int], str]:
        """The Tab cache file names of the channels dropped on the tab, by channel key."""
        return {curve.channel_key: name for curve, name in self._names.items()
                if curve.dock_id == dock_id and curve.channel_key is not None}

    def close_tab(self, dock_id: str) -> None:
        """Forgets every name and held write of a tab that was closed."""
        self._held.discard_dock(dock_id)
        for curve in [curve for curve in self._names if curve.dock_id == dock_id]:
            del self._names[curve]

    def _start(self, write: TabCacheWrite, held: HeldTabCacheWrite) -> None:
        self._start_write(
            held.dock_id, self._write_file, write.path, held.blocks, held.recipe,
            on_error=lambda message: self._write_failed(
                held.channel_name, write.name, message, held.on_failed))

    def _write_failed(self, channel_name: str, name: str, message: str,
                      on_failed: Callable[[str], None]) -> None:
        """The curve stops naming the file that was not written; when a Save
        already named it, the saved project is now behind and is marked so --
        the next Save drops the name instead of keeping a missing file."""
        on_failed(name)
        if name in build_referenced_tab_cache_names(self._saved_open_tabs() or ()):
            self._mark_view_changed()
        self._log(
            f"WARNING: tab cache for {channel_name} not written "
            f"({message}); the tab will be computed again when the project is reopened.")
