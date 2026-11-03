# =====================================================================
# FILE: view_models/data_pool/_pool_tree_visibility.py
# =====================================================================
"""
Which Data Pool tree nodes the search and the Filter hide, without Qt.

Both are views of the pool, not changes to it: the tree is built once and this
only names the nodes to hide and the ones to open, so clearing the search box
or the Filter brings everything straight back without a rebuild.
"""

from dataclasses import dataclass
from typing import AbstractSet, Mapping, Optional, Set

from ._pool_tree import NODE_CHANNEL, NODE_UNREADABLE_FOLDER, PoolTree


@dataclass(frozen=True)
class PoolTreeVisibility:
    """
    Keys of the nodes to hide, and of the nodes to open because a hit is only
    inside them. A node under a hidden one is hidden with it whatever it says.
    """

    hidden: frozenset = frozenset()
    expanded: frozenset = frozenset()


def resolve_pool_tree_visibility(
    tree: PoolTree,
    search_text: str,
    allowed: Optional[Mapping[str, AbstractSet[str]]],
) -> PoolTreeVisibility:
    """
    What the search text and the Filter leave of `tree`.

    `allowed` maps a measurement's file path to the unique labels of the
    channels the Filter lets through (visible_pool_channels), or is None when
    the Filter is not narrowing the pool. A measurement matches the search on
    its own name or on any of its channels, a setup on any of its measurements,
    and a sheet like a measurement: searching for a channel should find the
    measurement it is in, not an empty heading. The two narrow independently,
    so a row has to survive both. Folders of Unreadable files are narrowed by
    the search only -- the Filter speaks about measurements.
    """
    needle = search_text.strip().lower()
    hidden: Set[tuple] = set()
    expanded: Set[tuple] = set()

    def matches(node) -> bool:
        text = node.text if node.search_text is None else node.search_text
        return needle in text.lower()  # an empty needle matches everything

    def resolve_channel(node, allowed_labels, parent_matches) -> bool:
        passes_filter = allowed_labels is None or node.unique_label in allowed_labels
        visible = passes_filter and (parent_matches or matches(node))
        if not visible:
            hidden.add(node.key)
        return visible

    def resolve_measurement(node, setup_matches) -> bool:
        allowed_labels = None if allowed is None else allowed.get(node.run.file_path)
        if allowed is not None and allowed_labels is None:
            hidden.add(node.key)
            return False

        run_matches = setup_matches or matches(node)
        any_channel_visible = False
        for child in node.children:
            if child.kind == NODE_CHANNEL:
                visible = resolve_channel(child, allowed_labels, run_matches)
            else:
                # A sheet heading: it matches like a measurement does (#639).
                sheet_matches = run_matches or matches(child)
                visible = False
                for channel in child.children:
                    visible = resolve_channel(channel, allowed_labels, sheet_matches) or visible
                if not visible:
                    hidden.add(child.key)
                elif not sheet_matches:
                    expanded.add(child.key)
            any_channel_visible = any_channel_visible or visible

        run_visible = any_channel_visible or (run_matches and not node.children)
        if not run_visible:
            hidden.add(node.key)
        elif any_channel_visible and not run_matches:
            # A hit on a channel is only useful if it can be seen.
            expanded.add(node.key)
        return run_visible

    def resolve_unreadable_folder(node):
        folder_matches = matches(node)
        any_row_visible = False
        for row in node.children:
            if folder_matches or matches(row):
                any_row_visible = True
            else:
                hidden.add(row.key)
        if not any_row_visible:
            hidden.add(node.key)

    for root in tree.roots:
        if root.kind == NODE_UNREADABLE_FOLDER:
            resolve_unreadable_folder(root)
            continue
        setup_matches = matches(root)
        any_run_visible = False
        for measurement in root.children:
            any_run_visible = resolve_measurement(measurement, setup_matches) or any_run_visible
        if not any_run_visible:
            hidden.add(root.key)
        elif not setup_matches:
            expanded.add(root.key)

    return PoolTreeVisibility(hidden=frozenset(hidden), expanded=frozenset(expanded))
