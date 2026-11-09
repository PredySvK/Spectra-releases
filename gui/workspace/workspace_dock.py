# =====================================================================
# FILE: gui/workspace/workspace_dock.py
# =====================================================================
"""
WorkspaceDock: everything Workspace may ask of a dock it holds as a tab.

Workspace used to probe each tab with ``hasattr`` before calling it, so a
renamed or misspelt method was a branch that silently never ran (#899).
Every dock now derives from this class, and Workspace calls the contract
directly; a tab that is not a WorkspaceDock (the Home placeholder) is
simply not a dock.

Two kinds of methods:

- **Required** -- every dock has a Cursor and units, so each subclass must
  implement them; the base raises ``NotImplementedError`` so a missing or
  misspelt override fails loudly instead of doing nothing.
- **Optional** -- a feature only some docks have (Highlight, Band RMS and
  viewport clipping exist on GraphDock only). The base does nothing on
  purpose: a SpectrogramDock deliberately has no Highlight, so being told
  to clear it is a no-op, not an error.

The attributes are part of the contract as well, read directly rather than
through ``getattr(..., default)`` -- a default would swallow a misspelt name
just as ``hasattr`` did (#971, #972). ``dock_id``, ``analysis_kind`` and what
the dock shows (``run_index``, ``channel_meta``, ``tacho_block``,
``plot_widget``) and its ``evaluation_config`` are only declared: each subclass
sets them while it is built, so one that forgets fails on the first read.
``custom_tab_label``, ``dead_link`` and ``compute_failed`` have their empty
value here -- no dock is born with a user-assigned label, a Dead link or a
failed compute. The Tab label is built from them (#900).

What only one kind of dock has (``GraphDock.curves``, a ``SpectrogramDock``'s
``vib_block``, ``spectrogram`` and ``canonical_block``) is not declared here:
code that may hold either kind branches on ``isinstance`` and reads it directly.

The signals are part of the contract too: Workspace connects all of them on
every dock, and a dock that never emits one (a spectrogram never adds a
trace) simply leaves it silent. The mixins emit them; they are only ever
mixed into a WorkspaceDock.
"""

from typing import Optional

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from core.data_block import NVHDataBlock
from core.evaluation import EvaluationConfig
from core.models import ChannelMetadata, MeasurementRunIndex
from session.data_pool import DeadLink


class WorkspaceDock(QWidget):
    """Base class of every dock Workspace holds as a tab (#899)."""

    # Identifies the dock across asynchronous work and saved state; set by
    # each subclass in __init__.
    dock_id: str
    # The dock's Analysis kind (view_models.analysis_kinds); set by each
    # subclass in __init__, and Workspace may re-assign it.
    analysis_kind: str
    # Which channel the dock shows, and the tacho it holds; each None until
    # known. Set by each subclass in __init__, re-assigned as channels land.
    run_index: Optional[MeasurementRunIndex]
    channel_meta: Optional[ChannelMetadata]
    tacho_block: Optional[NVHDataBlock]
    # The plot the dock draws on; set by each subclass as it builds its UI.
    plot_widget: pg.PlotWidget
    # The dock's Evaluation configuration, saved with its tab; set by each subclass.
    evaluation_config: EvaluationConfig
    # The user-assigned Tab label, or None for the built one.
    custom_tab_label: Optional[str] = None
    # Why this dock's saved recipe could not be brought back, or None. Lasts
    # until the project is opened again; Save writes the recipe back whole.
    dead_link: Optional[DeadLink] = None
    # A restored dock whose file read but whose compute failed, until a later
    # compute lands.
    compute_failed: bool = False

    # A channel drag dropped on the dock: the list of channel descriptors
    # (ChannelDropTargetMixin), routed by Workspace.route_channel_drop.
    sig_channels_dropped = Signal(list)
    # A Selection dragged out of the Explorer and dropped on the dock: its name.
    sig_selection_dropped = Signal(str)

    # The dock's own shortcuts for the app-level Cursor / Pin / Highlight
    # switches; Workspace owns the switches and flips them.
    sig_cursor_toggle_requested = Signal()
    sig_cursor_pin_requested = Signal()
    sig_highlight_toggle_requested = Signal()
    # The `T` shortcut for the app-level Track cursor switch, likewise owned by Workspace.
    sig_track_cursor_toggle_requested = Signal()

    # Fired the first time this dock's model goes from empty to holding a
    # base trace. Workspace uses it to re-run the Local filter's
    # focus-change routing (FilterRoutingHandler.dock_focus_changed): that
    # routing already runs once at build_shell/tab-focus time, but a fresh
    # dock's model is still None then, so a Local filter's Channel facet
    # comes back empty and never gets a chance to default itself onto this
    # dock's own (still nonexistent) channel -- see gui/handlers/
    # filter_routing.py._apply_mask_filter predicate, which then hides the base trace
    # the moment it actually renders. Not emitted on later renders (unit
    # change, refresh): those don't change which channels this dock offers.
    sig_first_trace_rendered = Signal()

    # Fired every time a trace is appended to an already-rendered dock (a
    # second/third channel dropped in, an overlay curve; once per coalesced
    # batch that added curves). A Local filter's Channel facet is built from this dock's own
    # traces (filter_routing.refresh_filter_panel), and that only
    # gets re-run on a dock-focus or profile-focus change -- so a channel
    # added to the dock that already has focus left the panel showing the
    # stale trace count until something else (Configure Filters' Apply,
    # switching tabs and back) happened to re-trigger it.
    sig_trace_added = Signal()

    # Fired every time this dock's drawn content or its Trace-filter mask
    # could have changed: after every drawn change (a mask change via
    # set_trace_filter, a full model rebuild, a curve removed, a curve appended).
    # The Evaluation card is the one
    # listener -- one signal at this chokepoint instead of a recompute call
    # threaded through every action that can add/remove/hide a curve
    # (channel drop, overlay, live compute, Result Pool load/unload).
    sig_content_or_mask_changed = Signal()

    # --- required -------------------------------------------------------

    def hide_cursor_box(self) -> None:
        """Hide the Cursor Box, pinned or not (Cursor or Pin switched off)."""
        raise NotImplementedError

    def refresh_cursor_box(self) -> None:
        """Redraw the Cursor Box from the current content and Cursor Settings."""
        raise NotImplementedError

    def apply_unit_preferences(self) -> None:
        """Follow changed global unit preferences -- the dock does every step itself."""
        raise NotImplementedError

    def apply_x_axis_unit(self) -> None:
        """Redraw for a changed global X axis unit (a display rescale)."""
        raise NotImplementedError

    def visible_traces(self) -> list:
        """The curves Evaluation reads, Trace filter mask applied."""
        raise NotImplementedError

    def all_traces(self) -> list:
        """The curves Evaluation reads with the Trace filter mask skipped."""
        raise NotImplementedError

    # --- optional: deliberately nothing here ----------------------------

    def clear_highlight(self) -> None:
        """Restore every highlighted curve's pen; nothing to do without Highlight."""

    def refresh_highlight(self) -> None:
        """Re-apply the Highlight opacity; nothing to do without Highlight."""

    def set_highlight_preview(self, percent) -> None:
        """Show an Auto apply preview of the other curves' opacity; nothing to do without Highlight."""

    def refresh_band_rms_cursors(self) -> None:
        """Follow the global Band RMS switch; nothing to do without Band RMS."""

    def refresh_track_cursor(self) -> None:
        """Follow the global Track cursor switch; nothing to do without curves (a spectrogram)."""

    def set_track_preview(self, config, opacity=None) -> None:
        """Show Track cursor Settings' Auto apply preview; nothing to do without curves (a spectrogram)."""

    def apply_track_cursor_pin(self) -> None:
        """Follow the global Track cursor pin; nothing to do without curves (a spectrogram)."""

    def refresh_track_cursor_highlight(self) -> None:
        """Follow the global Track cursor highlight switch; nothing to do without curves (a spectrogram)."""

    def apply_viewport_clipping(self) -> None:
        """Re-run the clip / downsample sweep; nothing to do without 1D curves."""
