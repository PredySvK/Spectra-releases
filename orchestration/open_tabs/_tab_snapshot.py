"""A live dock's saved recipe: what a Save writes for one open tab."""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional

from core.evaluation import EvaluationConfig
from session.data_pool import DeadLink
from session.open_tabs import TabSpec, TraceSpec


def build_tab_spec(
    *,
    analysis_kind: str,
    dock_id: str,
    base: Optional[TraceSpec],
    dead_link: Optional[DeadLink],
    restored: Optional[TabSpec],
    awaiting_base: bool,
    overlays: List[TraceSpec],
    loaded_result_set_ids: List[str],
    filter_selections: Dict[str, dict],
    evaluation_config: EvaluationConfig,
) -> Optional[TabSpec]:
    """The ``TabSpec`` a dock is saved as, or None when there is nothing worth saving.

    ``base`` is the dock's live base curve (None for a dock with no run yet --
    the startup placeholder). ``restored`` is the recipe the tab was restored
    from; ``awaiting_base`` says its base curve has not landed on the dock yet.

    A tab restored from a recipe that never loaded (``dead_link``) holds none of
    its overlays or result sets, so the recipe is written back whole under the
    dock's current id (#385). A restored tab whose base is still on its way
    keeps the saved overlays and result sets merged with those loaded by hand
    meanwhile (#384).
    """
    if restored is not None and dead_link is not None:
        return dataclasses.replace(restored, dock_id=dock_id)
    if dead_link is not None:
        base = TraceSpec(source_id=dead_link.source_id, channel_name=dead_link.channel_name, is_base=True)
    if base is None:
        return None
    overlays = list(overlays)
    result_set_ids = set(loaded_result_set_ids)
    if restored is not None and awaiting_base:
        overlays += [o for o in restored.traces if not o.is_base and o not in overlays]
        result_set_ids |= set(restored.loaded_result_set_ids)
    return TabSpec(
        analysis_kind=analysis_kind,
        traces=[base, *overlays],
        dock_id=dock_id,
        filter_selections=filter_selections,
        loaded_result_set_ids=sorted(result_set_ids),
        evaluation_config=evaluation_config,
    )
