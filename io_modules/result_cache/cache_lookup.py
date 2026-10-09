# =====================================================================
# FILE: io_modules/result_cache/cache_lookup.py
# =====================================================================
"""
Finds an already-computed result that satisfies a live request, so the
workspace does not recompute what a batch (or an earlier save) already wrote to
disk. Generic over block kinds since ADR §1.21 -- a spectrum or spectrogram is
looked up exactly the way an order cut is.

A cache hit requires:
  - a result set of the requested `kind` that references this file's source id
  - status "complete" -- a "partial" set is missing coverage for some
    channel/source it was asked to compute (see ProjectSession.commit_result_set),
    so it must never be handed back as if it satisfied the whole request
  - computed by the algorithm version this build has for that kind (see
    DSP_ALGORITHM_VERSIONS) -- a result set predating an algorithm change
    would otherwise look identical to a fresh one
  - the shape parameters matching exactly (cache_layout.shape_signature) --
    each kind's `cache_exempt_params` are excluded: a live view asking for
    order 2 should still hit a result set saved with orders "1, 2, 4.5"
  - the source file itself unchanged: matched by byte count only. Not mtime,
    since a redownloaded or copied-to-another-machine file keeps its byte
    count but not its timestamp; and not relpath either, because which
    SourceEntry this is was already decided by source id, and project_store's
    index pass deliberately follows a renamed file to the same entry -- so
    comparing names here threw away every cached result the moment a file was
    renamed, which is exactly what IndexReport promises does not happen
  - the requested channel, and every requested block (e.g. every requested
    order), actually present in that file
  - the stored blocks computed in the unit the channel has now: a unit
    correction made after the set was saved (SourceEntry.unit_overrides)
    changes what a live compute would return -- a set computed while the file
    still said "g" for data really in m/s^2 is 9.81x off -- yet it changes
    neither the params nor the source file, so nothing above would notice
  - when the caller knows which channel of the file it means (`channel_index`),
    the stored blocks came from that same channel: one file can hold two
    channels with the same name (an ASC export with two "Mic" columns), and
    the name alone would hand one column's result back for the other

Among several matching candidates, an "All channels" result set always wins
over a narrower one, even an older one -- it is the one meant to be the
project's standing cache, while a one-off single-channel save is more likely
a throwaway look. Recency only breaks ties within the same tier.

Candidates come from `cache_index` first, so a miss usually costs one small
JSON read rather than opening every candidate .h5; only a survivor is opened,
and then only that measurement's shard.

Lives beside cache_reader.py/cache_writer.py rather than in gui/workspace/:
this is pure lookup logic over the project model plus an HDF5 read, with no
Qt and no AppContext, so it is unit-testable the same way as the rest of
result_cache/.
"""
import os
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

from core.block_kinds import KIND_ORDER_CUT
from core.data_block import NVHDataBlock
from core.dsp_configs import DSP_ALGORITHM_VERSIONS
from core.project_model import NVHProject, ResultSetRef, SourceEntry, normalize_result_kind
from core.units import sanitize_unit_string, strip_amplitude_suffix
from io_modules.project_store import project_folder
from io_modules.result_cache import cache_index, cache_layout
from selection.parameter_sets import shape_signature
from io_modules.result_cache.block_io import StoredBlock, block_from_stored
from io_modules.result_cache.cache_reader import ResultCacheReader


@dataclass
class CachedResult:
    """What a hit returns: the stored blocks, and which set they came from."""
    blocks: List[StoredBlock]
    result_set_label: str
    kind: str = ""


def shape_matches(kind: str, cached_params: Dict, live_params: Dict) -> bool:
    """Whether two params dicts describe the same computation for `kind`."""
    return (shape_signature(kind, cached_params)
            == shape_signature(kind, live_params))


def _version_matches(kind: str, cached_params: Dict) -> bool:
    # Each kind is checked against its own algorithm version: a bump to order
    # tracking's math must not invalidate every saved spectrum set, and vice
    # versa (audit 02 / 1.7). Missing key means a result set saved before this
    # field existed -- treated as version 1 rather than an automatic miss, so
    # shipping this check does not invalidate every cache already on disk.
    # Subscript, not .get: an unregistered kind is a programming error, not a
    # data one -- fail loudly rather than turn every set of that kind into a
    # silent permanent miss.
    expected = DSP_ALGORITHM_VERSIONS[normalize_result_kind(kind)]
    return cached_params.get("algorithm_version", 1) == expected


def _ranked_candidates(project: NVHProject, project_path: str, kind: str,
                       source_entry: SourceEntry, channel_name: str,
                       live_params: Dict, write_index: bool = True) -> List[ResultSetRef]:
    """Result sets that could hold this result, best first, without opening any."""
    entries = cache_index.entries_for(project, project_path, persist=write_index)
    allowed_ids = {
        entry.get("result_set_id")
        for entry in cache_index.candidates(entries, kind, source_entry.id, channel_name)
        # A known byte count that disagrees is a certain miss; an unknown one
        # (format 1, which the index cannot see into) is checked after opening.
        if entry.get("source_size_bytes") in (None, source_entry.size_bytes)
    }

    candidates = [
        rs for rs in project.result_sets
        if rs.id in allowed_ids and rs.kind == kind and rs.status == "complete"
        and source_entry.id in rs.source_ids
        and shape_matches(kind, rs.params, live_params)
        and _version_matches(kind, rs.params)
    ]
    # Stable sort, so within each tier (all-channels vs. not) the previous
    # recency ordering is preserved -- only the tier itself takes priority.
    candidates.sort(key=lambda rs: rs.created_utc, reverse=True)
    candidates.sort(key=lambda rs: rs.all_channels, reverse=True)
    return candidates


def find_cached_result(
    project: NVHProject, project_path: Optional[str], source_entry: SourceEntry,
    channel_name: str, kind: str, live_params: Dict,
    wanted_block_params: Optional[List[Dict[str, Any]]] = None,
    write_index: bool = True, channel_index: Optional[int] = None,
) -> Optional[CachedResult]:
    """
    Returns the freshest matching result set's blocks for one channel, or None.

    `wanted_block_params`, if given, additionally requires a stored block
    matching each entry (e.g. `[{"order": 1.0}, {"order": 2.0}]`) before a
    candidate counts as a match -- a result set that only covers some of the
    request is treated as a miss, not a partial hit, so the caller falls back to
    computing the whole request the ordinary way instead of stitching cached and
    fresh data together. The returned blocks are then in the requested order.

    `write_index=False` (a view-only session, or a worker thread) forbids
    persisting a rebuilt cache/index.json into the project folder.

    `channel_index`, if given, is the live channel's index within its file
    (ChannelMetadata.index); a candidate whose stored blocks record a different
    one is a miss.
    """
    if not project_path:
        return None  # nothing can have been saved before the project had a file

    kind = normalize_result_kind(kind)
    for rs in _ranked_candidates(project, project_path, kind, source_entry,
                                 channel_name, live_params, write_index):
        path = os.path.join(project_folder(project_path), rs.file)
        if not os.path.exists(path):
            continue
        try:
            with ResultCacheReader(path) as reader:
                # The candidate was picked by matching the ResultSetRef in the
                # project model; verify the file it points at still carries that
                # identity. _commit_overwrite swaps folders before saving the
                # project, so a failed save leaves cache/X holding freshly
                # recomputed numbers while the model reverted its params_hash --
                # without this check the stale request would open that file and
                # get the wrong curve back under the old identity. Empty on
                # either side is tolerated (a set predating the attribute).
                if (rs.params_hash and reader.params_hash
                        and reader.params_hash != rs.params_hash):
                    continue
                source_info = next(\
                    (s for s in reader.list_sources() if s.source_id == source_entry.id), None
                )
                if source_info is None:
                    continue
                if source_info.size_bytes != source_entry.size_bytes:
                    continue  # source file changed since this result set was written
                if channel_name not in source_info.channel_names:
                    continue

                blocks = reader.read_blocks(source_entry.id, channel_name)
                selected = _select_blocks(blocks, wanted_block_params)
                if selected is None:
                    continue
                if not _channel_index_matches(selected, channel_index):
                    continue  # a same-named channel of this file, not this one
                if not _unit_matches(source_entry, channel_name, selected):
                    continue  # the channel's unit was corrected after this set was saved
                return CachedResult(blocks=selected, result_set_label=rs.label, kind=kind)
        except (OSError, KeyError):
            # KeyError covers a cache file whose on-disk layout predates a
            # later format change (e.g. the channel_group_key hashing) --
            # such a file just misses as a candidate rather than crashing
            # the caller that was hoping for a fast cache hit.
            continue

    return None


def _corrected_unit(source_entry: SourceEntry, channel_name: str) -> Optional[str]:
    """
    The unit the user corrected this channel to, or None if it was not corrected.

    A correction is filed under whatever key the run had in hand when it was
    made -- the plain name or the reader's "Set #N: " / "Col #N: " label (see
    correct_run_channel) -- so both forms are accepted here.
    The stripped-name fallback only fires when the name is unique among this
    source's channels: two same-named columns (#423) must not let a
    correction filed under one column's exact label leak onto the other.
    """
    overrides = source_entry.unit_overrides
    if channel_name in overrides:
        return overrides[channel_name]
    from selection.channel_identity import is_channel_name_unique, strip_reader_label_prefix

    clean_target = strip_reader_label_prefix(channel_name)
    identities = (
        (label, facts.get("name", "")) for label, facts in source_entry.channels.items()
    )
    if not is_channel_name_unique(clean_target, identities):
        return None
    return next(
        (unit for label, unit in overrides.items()
         if strip_reader_label_prefix(label) == clean_target),
        None,
    )


def _unit_matches(source_entry: SourceEntry, channel_name: str,
                  blocks: List[StoredBlock]) -> bool:
    """
    Whether the stored blocks were computed in the channel's current unit.

    Only a correction can make them disagree: without one the channel still
    has the unit the file declares, which is what the set was computed from
    (and a changed file is already a miss by byte count). The stored value
    unit carries the spectral suffix ("g RMS", "(g)^2/Hz"), so it is peeled
    back to the physical unit before comparing.
    """
    corrected = _corrected_unit(source_entry, channel_name)
    if corrected is None:
        return True
    return all(
        sanitize_unit_string(strip_amplitude_suffix(block.value_unit))
        == sanitize_unit_string(corrected.strip())
        for block in blocks
    )


def _channel_index_matches(blocks: List[StoredBlock],
                           channel_index: Optional[int]) -> bool:
    """
    Whether the stored blocks came from the requested channel of the file.

    An index the block does not know (-1, or a set written before blocks
    recorded one) is not held against it -- only a known, different index is
    proof the blocks belong to another channel that shares this name.
    """
    if channel_index is None:
        return True
    for block in blocks:
        stored = (block.meta.get("source") or {}).get("channel_index", -1)
        if stored is not None and stored >= 0 and stored != channel_index:
            return False
    return True


def _select_blocks(blocks: List[StoredBlock],
                   wanted: Optional[List[Dict[str, Any]]]) -> Optional[List[StoredBlock]]:
    """The requested blocks in the requested order, or None if any is missing."""
    if wanted is None:
        return blocks

    selected = []
    for request in wanted:
        match = next(
            (b for b in blocks if cache_layout.block_params_match(request, b.params)), None
        )
        if match is None:
            return None
        selected.append(match)
    return selected


def find_cached_result_background(
    project: NVHProject, project_path: Optional[str], source_entry: SourceEntry,
    channel_name: str, kind: str, live_params: Dict,
    wanted_block_params: Optional[List[Dict[str, Any]]] = None,
    channel_index: Optional[int] = None,
) -> Optional[CachedResult]:
    """
    The worker-thread entry point to the cache (ADR §1.54).

    Same lookup as `find_cached_result`, but there is deliberately no
    `write_index` parameter: a background thread may read the `NVHProject` as a
    GIL-benign exception, yet it must never persist a rebuilt `cache/index.json`
    -- that stays a GUI-thread-only write via `ProjectSession._save_with_index()`
    at result-set commit time. `write_index` is hardcoded `False` here, so
    `write_index=True` cannot reach the cache from a worker even by mistake.
    """
    return find_cached_result(
        project, project_path, source_entry, channel_name, kind, live_params,
        wanted_block_params, write_index=False, channel_index=channel_index,
    )


def find_cached_block_background(
    project: NVHProject, project_path: Optional[str], source_entry: SourceEntry,
    channel_name: str, kind: str, live_params: Dict,
    wanted_block_params: Optional[List[Dict[str, Any]]] = None,
    channel_index: Optional[int] = None,
) -> Optional[NVHDataBlock]:
    """
    Returns the freshest matching result set's block reconstructed as a ready,
    plottable NVHDataBlock on a hit, or None on a miss.

    Worker-thread entry point (ADR §1.54): composes `find_cached_result_background`
    with `block_io.block_from_stored` so callers that need a single plottable
    block (such as 1D spectrum docks) do not have to stitch the lookup and
    reconstruction together or read the raw channel from disk.
    """
    cached = find_cached_result_background(
        project, project_path, source_entry, channel_name, kind, live_params,
        wanted_block_params=wanted_block_params, channel_index=channel_index,
    )
    if cached is None or not cached.blocks:
        return None

    try:
        block = block_from_stored(cached.blocks[0], kind)
    except ValueError:
        return None

    if cached.result_set_label:
        meta = dict(block.metadata)
        meta.setdefault("result_set_label", cached.result_set_label)
        block = replace(block, metadata=meta)

    return block


def find_duplicate_result_set(
    project: NVHProject, params: Dict, kind: str = KIND_ORDER_CUT,
) -> Optional[ResultSetRef]:
    """
    Finds an existing result set computed with exactly these parameters
    (full params hash, including the kind's exempt params -- not just the shape
    signature), so a batch can offer to overwrite it instead of writing a
    second file that differs only by an auto-incremented label.

    Channel selection is deliberately not considered: two batches with the
    same settings are a duplicate in spirit even if one covers more channels
    than the other -- it is up to the user to decide, via the resulting
    dialog, whether overwriting (and so replacing that file's channel
    coverage with the new batch's) is what they want.

    Returns the newest match, or None if this exact combination has never
    been saved before.
    """
    kind = normalize_result_kind(kind)
    target_hash = cache_layout.params_hash(params)
    candidates = [
        rs for rs in project.result_sets
        if rs.kind == kind and rs.params_hash == target_hash
    ]
    candidates.sort(key=lambda rs: rs.created_utc, reverse=True)
    return candidates[0] if candidates else None
