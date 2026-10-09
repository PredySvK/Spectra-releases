"""Background preparation of ordinary drops for paired order curves."""

from core.block_kinds import KIND_ORDER_CUT, KIND_TIME_RESPONSE, PARAM_ORDER
from core.models import resolve_channel_block_kind
from io_modules.data_accessor import DataAccessor
from orchestration.open_tabs import build_drop_descriptor
from selection.companion_curves import CompanionCurve, resolve_companion_curves
from session.data_pool import ResolvedTrace
from session.project import ProjectSession


def run_companion_curves(project_session, runs, plotted, channel_pairs):
    """Return (plotted identity, partner descriptor) rows; all I/O is here.

    Imported channels must be read to discover their order. First selecting
    with the requested orders restricts those reads to explicitly paired
    channels; waveforms are candidates for each requested order.
    """
    by_path = project_session.sources_by_path()
    channels = {}
    for run in runs:
        source = ProjectSession.entry_for_run(run, by_path)
        if source is None:
            continue
        for label, meta in run.available_channels.items():
            channels[(run.file_path, meta.index)] = (source.id, label, run, meta)

    origins = {}
    for identity in plotted:
        path, index, order = identity
        channel = channels.get((path, index))
        if channel is not None:
            origins[identity] = CompanionCurve(channel[0], channel[1], order)
    orders = {curve.order for curve in origins.values() if curve.order is not None}
    available = {}
    for source_id, label, run, meta in channels.values():
        if resolve_channel_block_kind(meta) not in (KIND_TIME_RESPONSE, KIND_ORDER_CUT):
            continue
        for order in orders:
            available[CompanionCurve(source_id, label, order)] = (run, meta, label)
    possible = resolve_companion_curves(origins.values(), available, channel_pairs)
    verified = {}
    imported_orders = {}
    for curve in possible:
        run, meta, label = available[curve]
        if resolve_channel_block_kind(meta) == KIND_ORDER_CUT:
            key = (run.file_path, meta.index)
            if key not in imported_orders:
                try:
                    block = DataAccessor.fetch_channel_data(run, meta)
                    imported_orders[key] = block.provenance.params.get(PARAM_ORDER)
                except Exception:
                    # An optional companion never prevents the user's curve
                    # from being shown, including an unavailable paired file.
                    imported_orders[key] = None
            if imported_orders[key] != curve.order:
                continue
        verified[curve] = build_drop_descriptor(ResolvedTrace(run, meta))
    result = []
    for identity, origin in origins.items():
        for curve in resolve_companion_curves([origin], verified, channel_pairs):
            descriptor = dict(verified[curve])
            descriptor["orders_to_extract"] = (curve.order,)
            result.append((identity, descriptor))
    return result
