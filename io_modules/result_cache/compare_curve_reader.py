# =====================================================================
# FILE: io_modules/result_cache/compare_curve_reader.py
# =====================================================================
"""
The disk-bound half of gui.handlers.result_content.
ResultContentHandler.load_into_dock: given a plan of which result sets, sources and
channels to read (all resolved from the in-memory project on the GUI thread),
open each one and pull the matching curves.

Curve-shaped kinds only -- one axis, one line per stored block. A spectrogram
is two-dimensional and has no meaning as an overlay, so the caller filters it
out before building the plan (result_content).

Runs whole on a background worker -- a comparison spanning many result sets on
a slow network share used to walk this loop synchronously on the GUI thread
and freeze the window. Emits nothing and logs nothing: warnings come back in
the return value for the caller to log on the GUI thread.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from core.block_kinds import KIND_ORDER_CUT, KIND_SPECTRUM, PARAM_COMPUTATION, PARAM_ORDER
from selection.source_facets import order_matches
from io_modules.result_cache.block_io import block_from_stored
from io_modules.result_cache.cache_reader import ResultCacheReader

# One item per checked result set that had at least one matching channel:
#     {
#       "ref_label": str,     # only used in warning text -- not the legend,
#                             # see read_result_curves
#       "ref_id": str,        # result-set id; passed through untouched so the
#                             # GUI on_step can stamp Trace.result_set_id and
#                             # dock membership per set (result_content)
#       "file_path": str,     # already resolved and verified to exist by the caller
#       "channel_matches": {source_id: [label, ...]},
#       "sources": {source_id: {"relpath": str, "channel_types": {label: str}}},
#     }
ReadPlanItem = Dict[str, Any]


def _build_compute_spec_for_stored(block) -> Dict[str, Any]:
    """
    ``Trace.compute_spec`` for a curve read off disk -- the processing settings
    the block was written with (``block.meta["processing"]``, already flat) plus
    whatever identity params the block carries (``block.params``, e.g. the order
    an order cut was extracted at). Without the order in here, a loaded order-cut
    curve can be drawn but never projected onto frequency (core.axis_projections
    needs it) or matched by an Order mask -- see ARCHITECTURE_DECISIONS §1.30.
    """
    spec = dict((block.meta or {}).get("processing") or {})
    spec.update(block.params or {})
    # Not a setting the Parameter Set signature is built from (#428).
    spec.pop(PARAM_COMPUTATION, None)
    return spec


def read_result_curves(
    read_plan: List[ReadPlanItem], order_selection: Optional[List[float]] = None
) -> Tuple[List[dict], int, List[str]]:
    """
    Returns (curves, matched_channel_count, warnings).

    Each curve dict carries `x`/`y`/`label`/`unit`/`meta` (drawn straight onto a
    dock, see gui.handlers.result_content). `label` is the stored
    block's own name (e.g. "1D Spectrum(Ch1_X)", "Order 2 [Ch1_X]") -- the same
    identity a live compute gives its result -- so plot_model_builder turns it
    into the exact legend shape a live curve gets, and the Filter panel's
    Channel facet resolves the same bare channel name either way. Plus `kind`, `x_quantity` and
    `compute_spec` -- what gui.workspace.plot_model.Trace needs to take part in
    axis projection (core.axis_projections) and an Order/Result-Kind mask, read
    straight off the stored block rather than re-derived from the legend text --
    and `result_set_id` (item["ref_id"], passed through untouched) so the GUI
    can stamp Trace.result_set_id and unload the set later (§1.31). `source_id`
    and `channel_name` name the measurement and channel the curve is of.

    Each read_plan item:
        {
          "ref_label": str,
          "file_path": str,
          "channel_matches": {source_id: [label, ...]},
          "sources": {source_id: {"relpath": str, "channel_types": {label: str}}},
        }

    `order_selection` narrows order-cut sets to the chosen orders; it does not
    apply to other kinds, which have no order to select.
    """
    curves: List[dict] = []
    warnings: List[str] = []
    matched_channel_count = 0

    for item in read_plan:
        ref_label = item["ref_label"]
        ref_id = item.get("ref_id", "")
        sources = item["sources"]

        try:
            reader_cm = ResultCacheReader(item["file_path"])
            with reader_cm as reader:
                kind = reader.kind
                channel_names_by_source = {
                    info.source_id: set(info.channel_names) for info in reader.list_sources()
                }

                for source_id, wanted_labels in item["channel_matches"].items():
                    source = sources.get(source_id)
                    if source is None:
                        continue
                    present = channel_names_by_source.get(source_id, set())
                    file_display_name = os.path.basename(source["relpath"])

                    for label in wanted_labels:
                        if label not in present:
                            continue
                        try:
                            blocks = reader.read_blocks(source_id, label)
                        except KeyError:
                            # list_sources() found this name (possibly via its
                            # backward-compat attribute fallback) but the group
                            # it points to is gone -- a cache file written
                            # before a layout change. Skip, do not crash Apply.
                            warnings.append(
                                f"Apply skipped '{file_display_name}' · {label} -- "
                                "unreadable in this result-cache file (old format)."
                            )
                            continue

                        channel_type = source["channel_types"].get(label, "general_dynamic")
                        meta = {"file_name": file_display_name, "channel_type": channel_type}
                        for block in blocks:
                            if kind == KIND_ORDER_CUT and order_selection is not None:
                                order = block.params.get(PARAM_ORDER)
                                if order is None or not order_matches(order, order_selection):
                                    continue

                            # A stored spectrum block holds canonical bin energy
                            # (g^2), never the Format the "Compute Result Set"
                            # dialog showed at creation time -- spectrum_format /
                            # amplitude_mode are display_only_params (ADR §1.60),
                            # applied when a block is rendered, not when it is
                            # cached. build_spectrum_model applies the same
                            # linear/rms default to a live curve; skipping it
                            # here left a loaded curve in g^2 next to live curves
                            # in g, incompatible units that forced it onto the
                            # secondary axis.
                            display_y, display_unit = block.values, block.value_unit
                            # Rebuilt for every comparable kind, not just
                            # KIND_SPECTRUM/KIND_OVERALL_LEVEL: the Evaluation
                            # card's dock adapter (ADR §1.64 point 3, issue
                            # #136) reads a Trace's `.block`, whatever curve
                            # kind loaded it onto a dock -- an order cut
                            # loaded from the Result Pool needs one exactly
                            # as much as a live-computed one does, even
                            # though nothing else here derives display values
                            # from it for that kind.
                            full_block = block_from_stored(block, kind)
                            if kind == KIND_SPECTRUM and full_block.is_canonical:
                                display_y, display_unit = full_block.to_display_values(
                                    spectrum_format="linear", amplitude_mode="rms",
                                )
                            # KIND_OVERALL_LEVEL also carries full_block through so
                            # the GUI side (result_content) can build the
                            # "OAL ..." legend and RMS/Peak rescaling the same way
                            # a live compute or a channel drop does
                            # (build_overall_level_model / _overall_level_overlay_
                            # trace) instead of the generic "[file] channel" legend
                            # every other loaded curve gets (ADR §1.62 point 13,
                            # #128) -- already covered by the line above.

                            curves.append({
                                "x": block.axes[0].values, "y": display_y,
                                # block.name is the same wrapped identity a live
                                # compute gives its result ("1D Spectrum(Ch1_X)",
                                # "Order 2 [Ch1_X]") -- plot_model_builder already
                                # knows how to turn that plus meta["file_name"]
                                # into the same legend shape a live curve gets
                                # (generate_dynamic_legend_text / _channel_identity_
                                # source). A cache-specific "[ref_label] file ·
                                # channel" string here made the legend and the
                                # Filter panel's Channel facet show the result-set
                                # label and the file name where a live curve shows
                                # neither -- see read_result_curves test module.
                                "label": block.name or label,
                                "unit": display_unit, "meta": meta,
                                "kind": kind, "x_quantity": block.axes[0].quantity,
                                "compute_spec": _build_compute_spec_for_stored(block),
                                "result_set_id": ref_id,
                                "block": full_block,
                                # Which measurement and channel the curve is
                                # of, as the project names them (#116).
                                # `label` is the name the shard files the channel
                                # under, "Mic #1" when two of a file's channels
                                # share a name -- the block keeps the real name and
                                # the index that tells them apart.
                                "source_id": source_id,
                                "channel_name": full_block.source.channel_name or label,
                                "channel_index": full_block.source.channel_index,
                                "computation": dict(block.params.get(PARAM_COMPUTATION) or {}),
                            })
                        matched_channel_count += 1
        except OSError as error:
            warnings.append(f"Apply skipped '{ref_label}' -- its result-cache file could not be read: {error}")

    return curves, matched_channel_count, warnings
