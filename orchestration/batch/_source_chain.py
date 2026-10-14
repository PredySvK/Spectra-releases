"""
The worker-thread half of a batch run: `_run_source_chain` reads one
measurement's channels off disk, runs the graph over each and writes that
measurement's shard into every save block it belongs to (ARCHITECTURE_DECISIONS
§1.21, §1.6.2). The ancestry rules that decide which save blocks a missing
mandatory bound channel blocks (`_blocked_save_blocks`, #331) live here with it.

`source_result_from` describes one measurement's results to the writer, shared
with the pre-existing tests of how a measurement is filed on disk.

No Qt, no window and no app_context.
"""
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Set

from core.block_kinds import resolve_clipped_f_stop
from core.jobs import CancelToken
from core.models import is_time_response
from core.workflow_graph import SaveSpec, Workflow
from io_modules.data_accessor import DataAccessor
from io_modules.measurement_files import file_stamp
from io_modules.result_cache.cache_writer import ChannelBlocks, SourceResult, write_result_shard
from selection.measurement_selection import resolve_run_channel_type, save_spec_allows_channel
from session.data_pool import run_from_entry
from signal_processing.workflow import (
    needed_block_ids, run_graph, save_block_ids, sole_input_block_id, spec_for,
)


@dataclass(frozen=True)
class _BlockSavePlan:
    """
    What one save block needs the workers to know: where its shards go, which
    measurements pass its metadata/range facet (decided in plan_batch(), against
    the schema), and the channel-level filter to apply per shard.

    Frozen plain data because it is handed to background steps. `source_ids` is
    the set of SourceEntry ids that survived this block's measurement facet; a
    file not in it contributes nothing to this block even if it feeds others.
    """
    block_id: str
    draft: object
    source_ids: Set[str]
    save: SaveSpec


def _block_bound_types(workflow_block) -> Dict[str, bool]:
    """A single block's bound channel types -> whether that port is mandatory."""
    if workflow_block.is_input:
        return {}
    spec = spec_for(workflow_block.block_type)
    optional_ports = {port.name for port in spec.inputs if port.optional}
    return {
        binding.channel_type: port_name not in optional_ports
        for port_name, binding in workflow_block.bindings.items()
    }


def _required_channel_types(workflow: Workflow) -> Dict[str, bool]:
    """
    Channel type -> whether at least one block needs it on a mandatory port.

    An optional port that is still bound (a time-mode spectrogram's tacho) is
    resolved when present and skipped when absent; a mandatory one missing
    used to fail the whole file -- now only the save blocks whose subgraph
    needs it (`_blocked_save_blocks`).
    """
    wanted: Dict[str, bool] = {}
    for workflow_block in workflow.blocks:
        for channel_type, required in _block_bound_types(workflow_block).items():
            wanted[channel_type] = wanted.get(channel_type, False) or required
    return wanted


def _read_bound_channels(entry, run, port_bound_types: Dict[str, bool]):
    """
    Read the channels that feed block ports (a spectrogram's or order cut's
    tacho). These are delivered to the graph through `bound_channels`, never as
    the primary input -- without that an all_channels selection paired with a
    typeless save spec ("Any type") slips the measurement's own tacho in as a
    vibration channel, order-tracks it against itself, and files the nonsense
    curve as a real channel (audit 02, finding S1/1.2).

    Returns (bound_channels, errors, missing_required). `missing_required` maps
    a *mandatory* port's channel type to the message when it is missing or
    unreadable -- the caller (`_run_source_chain`) turns that into per-block
    exclusion via `_blocked_save_blocks` rather than abandoning the whole file:
    a save block whose subgraph never binds that type still runs (#331).
    `errors` collects the same for an *optional* port (a time-mode
    spectrogram's tacho): the graph goes on without the channel, but silently
    dropping *why* it could not be read left the blocks reporting "no tacho"
    once per channel, which is both untrue and a dead end for whoever reads the
    log (audit 02, finding S1/1.5).
    """
    bound_channels = {}
    errors: List[str] = []
    missing_required: Dict[str, str] = {}
    for channel_type, required in port_bound_types.items():
        meta = next(
            (m for m in run.readable_channels() if m.type == channel_type), None
        )
        if meta is None:
            if required:
                missing_required[channel_type] = f"{entry.relpath}: no '{channel_type}' channel"
            continue
        try:
            bound_channels[channel_type] = DataAccessor.fetch_channel_data(run, meta)
        except Exception as error:
            message = f"{entry.relpath}: {channel_type}: {error}"
            if required:
                missing_required[channel_type] = message
            else:
                errors.append(message)
    return bound_channels, errors, missing_required


def _ancestry_mandatory_types(workflow: Workflow, block_id: str) -> Set[str]:
    """The mandatory bound channel types of `block_id` and everything upstream of it."""
    types: Set[str] = set()
    for current in needed_block_ids(workflow, {block_id}):
        types |= {
            channel_type for channel_type, required
            in _block_bound_types(workflow.block(current)).items() if required
        }
    return types


def _blocked_save_blocks(workflow: Workflow,
                        missing_required: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """
    Save block id -> {channel type: message} for the missing mandatory channel
    types that block it -- because it or a block upstream of it needs that type
    on a mandatory bound port.

    A save block absent from the result is unaffected: its subgraph never binds
    the missing type, so it runs and is saved even though a sibling branch of
    the same file cannot (#331) -- the same class of fix audit 02 S1/1.11
    already made for a failed channel via `block_errors`, extended here to a
    missing bound channel, which used to abandon the whole file via `fatal`.
    """
    if not missing_required:
        return {}
    blocked: Dict[str, Dict[str, str]] = {}
    for save_id in save_block_ids(workflow):
        hit = _ancestry_mandatory_types(workflow, save_id) & missing_required.keys()
        if hit:
            blocked[save_id] = {channel_type: missing_required[channel_type] for channel_type in hit}
    return blocked


def _run_source_chain(entry, directory: str, channel_labels: Sequence[str],
                      workflow: Workflow, save_plan: Dict[str, _BlockSavePlan],
                      cancel: Optional[CancelToken] = None,
                      progress_fn: Optional[Callable[[int, int], None]] = None):
    """
    Worker-thread body: read this file's channels, run the graph over each, and
    write this measurement's shard into every save block it belongs to.

    The write happens out here, not in the GUI-thread callback, for two reasons
    (ADR §1.21): a spectrogram shard is tens of megabytes, so writing it on the
    GUI thread would stutter the window; and returning the manifest entries
    instead of the blocks means what crosses back to the GUI thread is names
    and numbers, not the arrays that were just persisted.

    No logging and no Qt here -- returns
    (manifest_by_block, errors, block_errors, clipped_blocks). `manifest_by_block`
    maps a save block id to its shard's manifest entry; a block this file
    contributed nothing to is simply absent. `errors` are the failures that hit every save block alike (the
    file, an optional bound channel, a channel this file does not have);
    `block_errors` maps a save block id to the failures only its own set
    suffered -- a bad channel, or a missing *mandatory* bound channel that only
    that block's subgraph needs (`_blocked_save_blocks`) -- so one block's failure
    cannot mark a sibling set "partial", and a partial set never matches a cache
    lookup again (audit 02, finding S1/1.11; #331 for the bound-channel case).
    `clipped_blocks` are the save blocks whose Overall Level F max this file
    clipped to its Nyquist, for the sink's summary line (§1.62 point 9).
    The size/mtime stamp is taken after the reads so it describes what was
    actually read, matching OrderBatchSaveController.
    """
    errors: List[str] = []
    # Per save block: the failures that belong to that block alone.
    block_errors: Dict[str, List[str]] = {}
    # Per save block: the (channel meta, blocks) pairs this file contributes.
    per_block: Dict[str, List[tuple]] = {block_id: [] for block_id in save_plan}
    clipped_blocks: Set[str] = set()

    run = run_from_entry(entry, directory)
    if run is None:
        return {}, [f"{entry.relpath}: not scanned yet"], {}, set()

    input_block_id = sole_input_block_id(workflow)
    # One bag for this measurement, shared by every channel of it: order
    # tracking's TrackingPlan comes off the tacho and the sweep settings, so
    # without this it would be re-derived per channel (run_graph's docstring
    # carries the measurement).
    scratch: Dict[str, object] = {}

    port_bound_types = _required_channel_types(workflow)
    bound_channels, bound_errors, missing_required = _read_bound_channels(
        entry, run, port_bound_types
    )
    errors.extend(bound_errors)

    # A save workflow blocked by a missing mandatory bound channel (a file with no
    # tacho, on a graph that also saves a branch that never touches it) is
    # excluded from `run_graph`'s roots below rather than aborting the whole
    # file: its own message lands in its own block_errors, and the sibling save
    # block still gets this file (#331).
    blocked = _blocked_save_blocks(workflow, missing_required)
    for block_id, by_type in blocked.items():
        block_errors.setdefault(block_id, []).extend(by_type.values())
    active_root_ids = {block_id for block_id in save_plan if block_id not in blocked}
    if not active_root_ids:
        return {}, errors, block_errors, set()

    for position, label in enumerate(channel_labels):
        if cancel is not None:
            cancel.raise_if_cancelled()
        # Channels finished so far, skipped ones included; the last one is
        # counted when the step returns, after the shard is written (#469).
        if progress_fn is not None and position:
            progress_fn(position, len(channel_labels))
        meta = run.available_channels.get(label)
        if meta is None:
            # Every channel-level message carries the file it came from: a batch
            # over forty files otherwise logged the same bare line three times
            # with no way to tell which files it meant (audit 02, S1/1.6).
            errors.append(f"{entry.relpath}: {label}: not found in this file")
            continue

        if not is_time_response(meta.func_type):
            continue

        if meta.type in port_bound_types:
            continue    # fed to the graph as a bound channel, not a primary input

        # Which save blocks would keep this channel, decided *before* the graph
        # runs. A channel no block saves produces nothing on disk and the graph
        # has no other side effect, so running it is pure waste -- and for a
        # selection resolved with all_channels that includes the tacho, which
        # would otherwise be order-tracked against itself. The type is the one
        # the plan resolved this channel by (the stored one, ADR §1.97), not the
        # reader's: judged twice by two types, a planned channel was skipped here.
        # Port binding above stays on the reader's type -- it is about which
        # signal the file holds, not about which channels were asked for.
        channel_type = resolve_run_channel_type(entry, meta)
        targets = [
            block_id for block_id, plan in save_plan.items()
            if entry.id in plan.source_ids
            and save_spec_allows_channel(plan.save, meta.name, channel_type)
        ]
        if not targets:
            continue

        try:
            vib_block = DataAccessor.fetch_channel_data(run, meta)
            outputs = run_graph(workflow, {input_block_id: vib_block}, bound_channels,
                                cancel, scratch=scratch, roots=active_root_ids)
        except Exception as error:
            for block_id in targets:
                block_errors.setdefault(block_id, []).append(
                    f"{entry.relpath}: {label}: {error}"
                )
            continue
        for block_id in targets:
            blocks = outputs.get(block_id)
            if blocks:
                per_block[block_id].append((meta, blocks))
                if any(resolve_clipped_f_stop(block) for block in blocks):
                    clipped_blocks.add(block_id)

    if not any(per_block.values()):
        return {}, errors, block_errors, set()

    stamp = file_stamp(run.file_path)
    manifest_by_block: Dict[str, Optional[dict]] = {}
    for block_id, results in per_block.items():
        if not results:
            continue
        source = source_result_from(entry, results, stamp)
        manifest_by_block[block_id] = write_result_shard(save_plan[block_id].draft, source)
    return manifest_by_block, errors, block_errors, clipped_blocks


def source_result_from(entry, results: List[tuple], stamp: Optional[dict]) -> SourceResult:
    """
    One measurement's results as the writer's SourceResult.

    Shared with OrderBatchSaveController so the two batch paths cannot disagree
    about how a measurement is described on disk -- which stamp wins, and under
    which channel name the results are filed.

    Two channels of one file can share a name (an ASC export with two "Mic"
    columns). A shard keys its channel groups by name, so both are filed
    under the name plus their channel index instead -- neither claims the bare
    name, so a lookup by that name misses rather than guessing which one it
    meant (#320).
    """
    names = [meta.name for meta, blocks in results if blocks]
    clashing = {name for name, count in Counter(names).items() if count > 1}
    return SourceResult(
        source_id=entry.id, relpath=entry.relpath,
        size_bytes=stamp["size"] if stamp else entry.size_bytes,
        mtime_ns=stamp["mtime_ns"] if stamp else entry.mtime_ns,
        excel_metadata=dict(entry.excel_metadata),
        channels=[
            ChannelBlocks(channel_name=_filed_channel_name(meta, clashing), blocks=blocks)
            for meta, blocks in results if blocks
        ],
    )


def _filed_channel_name(meta, clashing: Set[str]) -> str:
    name = meta.name
    return f"{name} #{meta.index}" if name in clashing else name
