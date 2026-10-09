"""Pure planning for loading cached result-set curves into a dock."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Collection, Iterable, List, Tuple

from core.block_kinds import KIND_ORDER_CUT, KINDS
from io_modules.project_store import project_folder
from selection.source_facets import sources_for_result_sets


@dataclass(frozen=True)
class ResultSetLoadPlan:
    """All decisions made before the GUI submits a result-set read job."""

    read_plan: Tuple[dict, ...] = ()
    estimated_curves: int = 0
    over_limit: bool = False
    messages: Tuple[str, ...] = ()


def _is_comparable_kind(kind: str) -> bool:
    """Return whether a result kind represents overlayable one-axis curves."""
    spec = KINDS.get(kind)
    return spec is not None and len(spec.axis_quantities) == 1


def _resolve_curves_per_channel(ref: Any) -> int:
    """Estimate how many curves reader will yield per channel for this result set."""
    if ref.kind == KIND_ORDER_CUT:
        orders = (getattr(ref, "params", None) or {}).get("orders_to_extract")
        if isinstance(orders, Collection) and not isinstance(orders, (str, bytes)):
            return len(orders)
    return 1


def plan_result_set_load(
    project: Any,
    project_path: str | None,
    ref_ids: Iterable[str],
    already_loaded: Iterable[str],
    curve_limit: int,
) -> ResultSetLoadPlan:
    """Plan loading new, readable, curve-shaped result sets.

    No cache contents are read.  The estimate is the number of matching
    channels multiplied by the expected curves per channel (e.g. order
    count for order cuts).
    """
    loaded = set(already_loaded or ())
    new_ids = [ref_id for ref_id in ref_ids if ref_id not in loaded]
    if not new_ids:
        return ResultSetLoadPlan()
    refs = [result_set for result_set in project.result_sets if result_set.id in new_ids]

    messages: List[str] = []
    comparable = [ref for ref in refs if _is_comparable_kind(ref.kind)]
    skipped_kinds = {ref.kind for ref in refs if not _is_comparable_kind(ref.kind)}
    if skipped_kinds:
        messages.append(
            "WARNING: Load Result Sets can only load curve results -- "
            f"skipping kind(s): {', '.join(sorted(skipped_kinds))}."
        )

    read_plan: List[dict] = []
    estimate = 0
    for ref in comparable:
        sources = sources_for_result_sets(project, [ref.id])
        if not sources:
            continue
        file_path = os.path.join(project_folder(project_path), ref.file) if project_path else ref.file
        if not os.path.exists(file_path):
            messages.append(
                f"WARNING: Load Result Sets skipped '{ref.label}' -- "
                "its result-cache file is missing on disk."
            )
            continue

        channel_matches = {source.id: list(source.channels.keys()) for source in sources}
        channel_count = sum(len(labels) for labels in channel_matches.values())
        estimate += channel_count * _resolve_curves_per_channel(ref)
        read_plan.append({
            "ref_label": ref.label,
            "ref_id": ref.id,
            "file_path": file_path,
            "channel_matches": channel_matches,
            "sources": {
                source.id: {
                    "relpath": source.relpath,
                    "channel_types": {
                        label: (source.channels.get(label, {}) or {}).get(
                            "type", "general_dynamic"
                        )
                        for label in channel_matches[source.id]
                    },
                }
                for source in sources
            },
        })

    if not read_plan:
        messages.append("SYSTEM: Load Result Sets -- nothing to read.")

    return ResultSetLoadPlan(
        read_plan=tuple(read_plan),
        estimated_curves=estimate,
        over_limit=bool(read_plan) and estimate > curve_limit,
        messages=tuple(messages),
    )
