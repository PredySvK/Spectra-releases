# gui/file_explorer/actions/edit_unit.py
"""
Service Action: Handles standalone and bulk physical hardware unit tag fixes.

A unit correction is a statement about the measurement, not part of it, so it
is recorded in the project and never written back into the file or into the
folder cache. The cache stays a pure re-scannable copy of what the files say;
ProjectSession.apply_unit_overrides restates the corrections over it on every
load. Deleting the cache therefore costs a re-scan and nothing else.

The in-memory ChannelMetadata is still updated so the tree and any open plot
reflect the change immediately -- it is the copy the rest of the session reads.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtWidgets import QInputDialog
from core.units import get_compatible_options
from session.project import apply_unit_override, channel_label_for


def _report(app_context, explorer_widget, changed: int, unstored: int, unit: str, scope: str):
    explorer_widget.rebuild_tree_view()
    if not changed:
        return

    app_context.log(
        f"SYSTEM: {scope} unit fix success. Modified {changed} channel(s) to [{unit}]."
    )
    if unstored:
        # Without a data folder registered there is no source to attach the
        # correction to, so it holds for this session only. Saying so is better
        # than letting it disappear at the next load.
        app_context.log(
            f"WARNING: {unstored} correction(s) could not be stored in the project "
            f"and will not survive a reload."
        )


def _resolve_unit_choices(current_unit: str) -> tuple[list, int]:
    """Prepares options list and selects current_unit, prepending it if not present."""
    options = get_compatible_options(current_unit)
    if current_unit not in options:
        options.insert(0, current_unit)
    return options, options.index(current_unit)


def execute_fix_unit(app_context, explorer_widget, run_index, channel_meta):
    """Fix Unit: corrects one channel and records it in the project."""
    allowed_options, current_idx = _resolve_unit_choices(channel_meta.unit)

    selected_unit, ok = QInputDialog.getItem(
        explorer_widget,
        "Fix Unit (Single Channel)",
        f"Select physical unit tag for [{channel_meta.name}]:",
        allowed_options,
        current_idx,
        editable=False
    )

    if ok and selected_unit:
        selected_unit = selected_unit.strip()
        label = channel_label_for(run_index, channel_meta)
        stored = apply_unit_override(app_context.project_session, run_index, channel_meta, label, selected_unit)
        _report(app_context, explorer_widget, 1, 0 if stored else 1, selected_unit, "Single-channel")


def execute_bulk_fix_unit(app_context, explorer_widget, run_index, target_channel_type: str, current_unit_str: str):
    """
    Fix Unit for a whole file: corrects every channel of one type in one run.

    Scoped to the run the right-clicked channel belongs to, not the pool. The
    old form walked app_context.pool.loaded_runs unconditionally, so from a pool of
    several folders it rewrote the unit of sensors the user had not seen and
    could not undo except by hand -- and the menu already said "in this file".
    """
    allowed_options, current_idx = _resolve_unit_choices(current_unit_str)

    selected_unit, ok = QInputDialog.getItem(
        explorer_widget,
        "Fix Unit (All Matching Channels in File)",
        f"Select new physical unit tag for all {target_channel_type.upper()} channels "
        f"in [{run_index.file_name}]:",
        allowed_options,
        current_idx,
        editable=False
    )

    if ok and selected_unit:
        selected_unit = selected_unit.strip()
        changed = 0
        unstored = 0

        # Collected first: apply_unit_override rewrites the type that is being matched on,
        # so deciding while iterating would depend on dictionary order.
        targets = [(label, meta) for label, meta in run_index.available_channels.items()
                   if meta.type == target_channel_type]

        for label, channel_meta in targets:
            if not apply_unit_override(app_context.project_session, run_index, channel_meta, label, selected_unit):
                unstored += 1
            changed += 1

        _report(app_context, explorer_widget, changed, unstored, selected_unit, "File-wide")


def execute_selected_fix_unit(app_context, explorer_widget, selected_channels: list):
    """
    Fix Selected Units: corrects every highlighted channel row at once.

    Takes payloads -- (run_index, channel_meta, label) tuples pulled off the
    tree BEFORE any dialog opens -- not QTreeWidgetItem references. A pool
    rescan (settle timer, ingest step) runs during menu.exec / QInputDialog and
    calls rebuild_tree_view, which deletes the items underneath us; reading
    item.data() back afterwards raised "Internal C++ object already deleted".
    """
    if not selected_channels:
        return

    validated = [p for p in selected_channels
                 if isinstance(p, tuple) and len(p) >= 3]
    if not validated:
        return

    first_ch_meta = validated[0][1]
    allowed_options, current_idx = _resolve_unit_choices(first_ch_meta.unit)

    selected_unit, ok = QInputDialog.getItem(
        explorer_widget,
        "Fix Unit (Selected Channels)",
        f"Select matching physical unit tag for all {len(validated)} selected items:",
        allowed_options,
        current_idx,
        editable=False
    )

    if ok and selected_unit:
        selected_unit = selected_unit.strip()
        changed = 0
        unstored = 0

        for run_index, channel_meta, label in validated:
            if not apply_unit_override(app_context.project_session, run_index, channel_meta, label, selected_unit):
                unstored += 1
            changed += 1

        _report(app_context, explorer_widget, changed, unstored, selected_unit, "Multi-selection")

