# =====================================================================
# FILE: core/project_model.py
# =====================================================================
"""
In-memory model of an NVH project.

A project owns everything the user decides about a set of measurements --
which folders they live in, the metadata typed against each run, per-channel
unit corrections, the analysis parameters, and which result sets have been
computed. It never owns sample data: the raw files stay where they are and
computed results live in HDF5 files beside the project.

The point of keeping this here, in core/, is that it is pure data. No file
access, no Qt, no numpy. io_modules/project_store.py does the reading and
writing; this module only describes the shape and can be tested without
touching a disk.

All internal documentation strings and variable labels are standardly written
in English.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import os.path
import uuid

from core.block_kinds import KIND_ORDER_CUT, KIND_SPECTROGRAM
from core.filter_card_config import FilterCardConfig
from core.measurement_selection import MeasurementSelection
from core.models import ChannelIdentity
from core.workflow_graph import Workflow


# Bumped only when a change cannot be read by an older build. Additive fields
# do not need a bump, because from_dict() defaults anything it does not find.
#
# 2 (§1.32, ticket #40): `filter_cards`. Additive in shape, but the bump is
# deliberate -- a Filter card's column configuration is now a project decision,
# and a project saved with cards the user arranged must not be silently opened
# and re-saved by an older build that drops the field.
PROJECT_FORMAT_VERSION = 2
OLDEST_READABLE_PROJECT_FORMAT_VERSION = 1
# On an incompatible format change, raise both limits together (ADR §1.140).

PROJECT_EXTENSION = ".nvhproject"

# What a result set's `kind` used to be spelled as, before §1.21 made it the
# same vocabulary as the blocks stored inside it. Read-side only: to_dict()
# always writes the block kind, so a project rewrites itself on first save.
_LEGACY_RESULT_KINDS = {
    "order_cuts": KIND_ORDER_CUT,
    "waterfall": KIND_SPECTROGRAM,
}


def normalize_result_kind(kind: Optional[str]) -> str:
    """A result set's kind as a core.block_kinds key, translating old spellings."""
    kind = (kind or KIND_ORDER_CUT).strip()
    return _LEGACY_RESULT_KINDS.get(kind, kind)


def utc_now() -> str:
    """Timestamp format used everywhere in the project file."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _compare_path(value: Optional[str]) -> str:
    """
    Folds one path spelling into the form used to decide whether two paths mean
    the same folder. Comparison key only -- never store or reopen the result,
    the same rule io_modules.measurement_files.canonical_path lives by.

    An empty path stays empty rather than becoming normpath's ".", so a root
    with no relpath does not compare equal to one rooted at the project folder.
    """
    if not value:
        return ""
    return os.path.normcase(os.path.normpath(value))


@dataclass
class DataRoot:
    """
    A folder the project draws measurements from.

    Two paths are kept on purpose. `relpath` is resolved against the project
    file's own folder and is what makes a project survive being copied to
    another machine; `absolute_fallback` is what the folder was when the root
    was added, and is only consulted when the relative form does not exist.
    Without the fallback a project moved off its original drive would lose its
    data with no way to explain what it was looking for.
    """
    id: str = field(default_factory=lambda: _new_id("root"))
    relpath: str = ""
    absolute_fallback: str = ""
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "relpath": self.relpath,
            "absolute_fallback": self.absolute_fallback,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DataRoot":
        return cls(
            id=data.get("id") or _new_id("root"),
            relpath=data.get("relpath", ""),
            absolute_fallback=data.get("absolute_fallback", ""),
            label=data.get("label", ""),
        )


@dataclass
class SourceEntry:
    """
    One measurement file, as the project sees it.

    `metadata` and `unit_overrides` are the reason this class exists. Both are
    user decisions about a file that must never be written back into the file
    itself -- the raw measurement is evidence and stays untouched. Keeping them
    here means they travel with the project, survive a restart, and can be
    handed to a colleague.

    `size_bytes` and `mtime_ns` are the same cheap identity the folder cache
    already uses (io_modules.measurement_files.file_stamp). They serve two
    jobs: telling a stale result set from a current one, and recognising a file
    that has only been renamed.
    """
    id: str = field(default_factory=lambda: _new_id("src"))
    root_id: str = ""
    relpath: str = ""
    size_bytes: int = 0
    mtime_ns: int = 0

    # Whether this measurement is currently in the Data Pool -- the working
    # set the user has lined up, as opposed to everything the project has ever
    # indexed. Removing a file from the pool clears this rather than deleting
    # the entry, because the entry is where its metadata, unit corrections and
    # test setup live and every result set refers to it by id. Defaults to
    # True so a project written before the pool existed opens with everything
    # it indexed, which is what it used to show.
    in_pool: bool = True

    # Which hardware configuration or test state this measurement belongs to.
    # A user decision, and the top level of the Data Pool tree, so it has to
    # survive a restart -- a grouping that only existed in the tree widget
    # would be lost the moment the window closed. Blank means the file has not
    # been assigned to one and shows under the default setup.
    setup_label: str = ""

    # Free-form run-level metadata. Values stay strings for now; typing them
    # is deferred until the comparator needs to filter on them numerically.
    metadata: Dict[str, str] = field(default_factory=dict)

    # channel label -> corrected unit, for channels whose file-declared unit
    # is wrong (a tacho recorded as volts, an accelerometer as dimensionless).
    unit_overrides: Dict[str, str] = field(default_factory=dict)

    # The Level 2 Excel row linked to this file (see io_modules.metadata_schema),
    # re-synced automatically on every scan. Kept separate from `metadata` above,
    # which is a manual per-field decision the user typed in the app -- an
    # auto-synced row would otherwise silently overwrite that on the next scan.
    excel_metadata: Dict[str, Any] = field(default_factory=dict)

    # Level 1 facts discovered straight from the file itself (id1..id5 today;
    # whatever a future reader for another file type adds besides, since
    # core.models.MeasurementRunIndex.file_level_facts() dumps dynamically).
    # Re-synced on every scan, same as excel_metadata.
    file_metadata: Dict[str, Any] = field(default_factory=dict)

    # excel_metadata / file_metadata parsed once to the schema's typed `kind`
    # (int/float/date/str), keyed by schema field name -- so the comparator can
    # filter "speed 2000..4000" numerically instead of on "10000" < "9000" as
    # text (ADR §1.1). Derived: rebuilt on every scan by
    # ProjectSession.sync_source_metadata from the raw dicts above and the
    # project schema. Dates are stored as ISO "YYYY-MM-DD" strings (JSON-native,
    # chronologically sortable); selection.source_facets parses them back.
    parsed_metadata: Dict[str, Any] = field(default_factory=dict)

    # channel label -> core.models.ChannelMetadata.to_dict() snapshot, so a
    # channel's sampling rate, unit, type etc. are known without the data root
    # being mounted -- the comparator's channel filter reads this, not a live
    # scan. Re-synced on every scan, same as excel_metadata.
    channels: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def stamp_matches(self, size_bytes: int, mtime_ns: int) -> bool:
        """Whether the file on disk is still the one this entry was built from."""
        return self.size_bytes == size_bytes and self.mtime_ns == mtime_ns

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "root_id": self.root_id,
            "relpath": self.relpath,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "in_pool": self.in_pool,
            "setup_label": self.setup_label,
            "metadata": dict(self.metadata),
            "unit_overrides": dict(self.unit_overrides),
            "excel_metadata": dict(self.excel_metadata),
            "file_metadata": dict(self.file_metadata),
            "parsed_metadata": dict(self.parsed_metadata),
            "channels": {label: dict(facts) for label, facts in self.channels.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceEntry":
        return cls(
            id=data.get("id") or _new_id("src"),
            root_id=data.get("root_id", ""),
            relpath=data.get("relpath", ""),
            size_bytes=int(data.get("size_bytes", 0)),
            mtime_ns=int(data.get("mtime_ns", 0)),
            in_pool=bool(data.get("in_pool", True)),
            setup_label=data.get("setup_label", ""),
            metadata=dict(data.get("metadata") or {}),
            unit_overrides=dict(data.get("unit_overrides") or {}),
            excel_metadata=dict(data.get("excel_metadata") or {}),
            file_metadata=dict(data.get("file_metadata") or {}),
            parsed_metadata=dict(data.get("parsed_metadata") or {}),
            channels={label: dict(facts) for label, facts in (data.get("channels") or {}).items()},
        )


@dataclass
class ResultSetRef:
    """
    A named, computed set of results -- the project's view of one HDF5 file.

    This is deliberately only a reference. Everything needed to interpret the
    results is also written into the HDF5 file's own root attributes, so a
    result file handed over without its project still explains itself. What
    lives here is what the project needs to list, label and compare them
    without opening every file.

    `params_hash` is a fingerprint of the parameters actually used. The label
    ("order_v01") is what the user reads and chooses between; the hash is the
    safety net that catches a set whose parameters are not what its label
    suggests.

    `kind` is a block kind from core/block_kinds.py -- the same vocabulary the
    blocks inside the file use. It used to be a second, parallel one
    ("order_cuts" here vs. "order_cut" on the block), which nothing mapped
    between; from_dict() normalises the old spelling so projects written before
    §1.21 keep working.

    `format_version` says what `file` points at: 1 = a single .h5 holding the
    whole set (pre-§1.21), 2 = a folder with one .h5 shard per measurement plus
    a _set.json manifest. Recorded rather than sniffed from the filesystem, so
    listing a project's result sets never has to stat anything.
    """
    id: str = field(default_factory=lambda: _new_id("rs"))
    label: str = ""
    kind: str = "order_cut"         # a key of core.block_kinds.KINDS
    file: str = ""                  # relative to the project folder
    params: Dict[str, Any] = field(default_factory=dict)
    params_hash: str = ""
    created_utc: str = field(default_factory=utc_now)
    format_version: int = 1

    def __post_init__(self):
        # Normalised here rather than only in from_dict, so a ref built in code
        # with the old spelling cannot slip past either -- one place decides
        # what a kind is called, and every comparison against KINDS holds.
        self.kind = normalize_result_kind(self.kind)

    # complete | partial | failed. A cancelled or crashed batch leaves
    # "partial", which is a resumable state rather than an error.
    status: str = "partial"
    source_ids: List[str] = field(default_factory=list)

    # True when this set was written by "All channels" mode rather than an
    # explicit channel pick -- cache lookup prefers these over a narrower
    # set with the same FFT settings, regardless of which one is newer.
    all_channels: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "file": self.file,
            "params": dict(self.params),
            "params_hash": self.params_hash,
            "created_utc": self.created_utc,
            "format_version": self.format_version,
            "status": self.status,
            "source_ids": list(self.source_ids),
            "all_channels": self.all_channels,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResultSetRef":
        return cls(
            id=data.get("id") or _new_id("rs"),
            label=data.get("label", ""),
            kind=data.get("kind") or KIND_ORDER_CUT,     # normalised in __post_init__
            file=data.get("file", ""),
            params=dict(data.get("params") or {}),
            params_hash=data.get("params_hash", ""),
            created_utc=data.get("created_utc") or utc_now(),
            format_version=int(data.get("format_version", 1) or 1),
            status=data.get("status", "partial"),
            source_ids=list(data.get("source_ids") or []),
            all_channels=bool(data.get("all_channels", False)),
        )


@dataclass
class FilterSelection:
    """
    One filter profile's checked state, for one target -- the whole app for a
    "global" profile, one dock for a "local" one (FilterPanel is what decides
    which target applies; this dataclass just holds the five fields that used
    to live directly on FilterProfile before scope stopped being a property
    of the profile *object* and became a property of *where its state lives*.
    See FilterProfile's own docstring, and
    plans/2026-09-05_filtre-maska-nad-kazdym-grafom.md T1.
    """
    checked_metadata_values: Dict[str, Set[str]] = field(default_factory=dict)
    # Built-in Identity facets other than Channel (Direction, Channel type, File
    # name, Data Pool label, Result set): column key (core.filter_card_config
    # COLUMN_*) -> checked string values. Gated the §1.29 "offered ∧ unchecked
    # ⇒ hide" way, same as Channel -- they are Identity columns like it, not
    # metadata (whose empty selection imposes nothing). See ARCHITECTURE_DECISIONS
    # §1.33.
    checked_identity_values: Dict[str, Set[str]] = field(default_factory=dict)
    checked_channel_identities: Set[ChannelIdentity] = field(default_factory=set)
    checked_orders: Set[float] = field(default_factory=set)
    # Parameter Set checks keyed by the set's settings signature
    # (selection.parameter_sets.parameter_signature), not its "Parameter Set N"
    # number: that number is re-derived every round from whatever the dock or
    # project currently holds, so it moves when curves or result sets come and
    # go (#349). Compared float-tolerantly (signatures_match), never with `in`.
    checked_parameter_set_signatures: Set[Tuple] = field(default_factory=set)
    # Result Kind facet (plan F4): which core.block_kinds kinds a Local dock's
    # own traces are allowed to show, gated the same §1.29 way as Channel/Order
    # rather than Metadata/Parameter Set's "empty means no constraint".
    checked_result_kinds: Set[str] = field(default_factory=set)
    # Numeric/date facets (ARCHITECTURE_DECISIONS §1.32): field key -> (lo, hi)
    # in the field's own type. A key's *presence* here is the "user has moved
    # this range" flag -- an untouched range imposes no constraint and its
    # bounds are recomputed from the live pool on every rebuild, so there is
    # nothing to store for it until the user actually drags it.
    checked_ranges: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)
    # The "(Empty)" bucket per gating facet (ADR §1.56): the set of tokens whose
    # value-less traces stay visible. A token is a GATING_FACETS family name for
    # the scalar families (`order`, `result_kind`, `parameter_set`) and the
    # column key for the keyed ones (Identity columns, metadata fields). Gated
    # the same §1.29 way as every other value -- offered and unchecked hides the
    # value-less trace; unchecking "(Empty)" in Order is what finally hides a
    # time record on a mixed dock.
    checked_empty_buckets: Set[str] = field(default_factory=set)


@dataclass
class FilterProfile:
    """
    A named filter profile -- one tab in the Filter panel's tab bar.

    Identity only, not state: `scope` decides whether this profile's checked
    state is one value shared by the whole app ("global") or one value per
    dock ("local"). Unlike before T1, that state does not live on this
    dataclass at all -- FilterPanel keeps it in two dicts keyed by profile id
    (global) or (profile id, dock id) (local), so the same profile shows the
    same tab in every dock's tab bar regardless of scope; only the content
    behind a "local" tab differs by dock. See
    plans/2026-09-05_filtre-maska-nad-kazdym-grafom.md T1 for why the previous
    `dock_id` field (and the whole "unclaimed until a dock focuses" dance that
    went with it) is gone.

    `builtin` marks the two fixed tabs ("Global filter", "Local filter") that
    FilterPanel always creates and that cannot be deleted or have their scope
    flipped -- see FilterPanel._add_profile.

    `owner_dock_id` is set only on a custom "local" profile and drives only
    which dock's tab bar shows its tab -- see ARCHITECTURE_DECISIONS §1.37 for
    why that is not a return of the pre-T1 `dock_id` field.

    Not wired into NVHProject's own to_dict/from_dict -- it is small, purely
    UI-side state (like the rest of `ui_state`), so it round-trips through
    `gui.filter_panel.filter_panel.FilterPanel.serialize_profile_identities`/
    `restore_profile_identities` into `ui_state["compare_filters"]["profiles"]`
    instead (T5) -- selections live under separate keys, see that module's
    docstring.
    """
    id: str = field(default_factory=lambda: _new_id("filter"))
    name: str = "Filter"
    scope: str = "local"  # "global" | "local"
    builtin: bool = False
    owner_dock_id: Optional[str] = None


@dataclass
class NVHProject:
    """
    The whole project document.

    Held in memory by AppContext and serialised to a .nvhproject file by
    io_modules.project_store. Mutating methods here keep the internal indexes
    consistent; callers should not append to the lists directly.
    """
    # What the file held when it was read -- informational only.
    # io_modules.project_store.save_project always writes the current build's
    # PROJECT_FORMAT_VERSION regardless of this value, so a project opened at
    # an older format and re-saved is correctly marked as no longer safe for
    # that older build to open (issue #343).
    format_version: int = PROJECT_FORMAT_VERSION
    name: str = "Untitled Project"
    created_utc: str = field(default_factory=utc_now)
    modified_utc: str = field(default_factory=utc_now)

    data_roots: List[DataRoot] = field(default_factory=list)
    sources: List[SourceEntry] = field(default_factory=list)
    result_sets: List[ResultSetRef] = field(default_factory=list)

    # Named queries saying what a batch runs over (ADR §1.12). A project
    # decision like a metadata edit, not cosmetics, so it is a typed field
    # rather than another key in ui_state -- a selection that quietly vanished
    # would take a saved recipe's meaning with it.
    selections: List[MeasurementSelection] = field(default_factory=list)

    # Block-diagram workflows (ADR §1.6, Epic P phase 7A). A graph of processing
    # nodes the user built once and can re-run on new data. A project decision,
    # like `selections` above and for the same reason -- a workflow that quietly
    # vanished would take a campaign's whole analysis definition with it -- so it
    # is a typed field, not a key in ui_state.
    workflows: List[Workflow] = field(default_factory=list)

    # Per-card Filter card column configuration (ADR §1.32): which columns a
    # card shows, in what order, drawn as which widget. A typed field beside
    # `selections` and `workflows`, not another key in `ui_state`, and for the
    # same reason -- the user invests order, widgets and defaults into it, so
    # losing it is losing a decision, not cosmetics. Keyed to a FilterProfile
    # by id. Per-dock checked *values* stay in TabSpec; this is the card's
    # shape across every dock.
    filter_cards: List[FilterCardConfig] = field(default_factory=list)

    # Which metadata fields are shown and what they are called:
    # {key: {"custom_label": str, "is_active": bool, "layer": "excel"|"channel"}}.
    # "channel" (BUGS.md N1/N2) means the value lives per-channel on a reader's
    # ChannelMetadata (func_type, sampling_rate, id1..id5, ...), read through
    # selection.source_facets.channel_summary_value -- never a UNV-only
    # concept, any reader that fills the matching ChannelMetadata attribute
    # participates.
    # A user decision, so it belongs with the project rather than in the folder
    # cache, which is derived and may be deleted at any time.
    metadata_schema: Dict[str, Any] = field(default_factory=dict)

    # Window layout, open tabs, last selected channel. Cosmetic: a project that
    # loses this is still fully usable, so nothing here is validated.
    ui_state: Dict[str, Any] = field(default_factory=dict)

    # ---- lookup -------------------------------------------------------

    def source_by_id(self, source_id: str) -> Optional[SourceEntry]:
        return next((s for s in self.sources if s.id == source_id), None)

    def source_by_relpath(self, root_id: str, relpath: str) -> Optional[SourceEntry]:
        return next(
            (s for s in self.sources if s.root_id == root_id and s.relpath == relpath),
            None,
        )

    def setup_labels(self) -> List[str]:
        """
        Every test setup a source has been assigned to, in order of first use.

        Ordered by first use rather than alphabetically so the list the user is
        offered when assigning a file matches the order the setups appear in
        the Data Pool tree. The blank label is not one of them -- it is the
        absence of an assignment, not a setup.
        """
        labels: List[str] = []
        for entry in self.sources:
            if entry.setup_label and entry.setup_label not in labels:
                labels.append(entry.setup_label)
        return labels

    # ---- mutation -----------------------------------------------------

    def add_root(self, root: DataRoot) -> DataRoot:
        """
        Registers a data folder, or returns the one already standing for it.

        Paths are compared the way the platform compares them. Windows ignores
        case and takes either separator, so the same folder reaching here
        spelled two ways would otherwise become two roots -- and then every
        measurement in it would have two entries, two sets of metadata and two
        histories.

        normcase alone was not enough: it folds case and separators but leaves
        a trailing separator and "." / ".." segments in place, so "D:\\Data\\Set1"
        and "D:\\Data\\Set1\\" still compared unequal. normpath removes those.
        Both are pure string operations; nothing here touches a disk.
        """
        def same(left: str, right: str) -> bool:
            return _compare_path(left) == _compare_path(right)

        existing = next(
            (r for r in self.data_roots
             if same(r.relpath, root.relpath) and same(r.absolute_fallback, root.absolute_fallback)),
            None,
        )
        if existing is not None:
            return existing
        self.data_roots.append(root)
        return root

    def merge_root(self, keep: DataRoot, drop: DataRoot) -> None:
        """
        Folds `drop` into `keep` when both turned out to stand for one folder.

        A file known under both keeps the entry filed under `keep` -- the older
        one, whose id the earlier result sets were written against -- and takes
        over the user decisions made on the other copy, which win on conflict
        because the copy only ever held what was typed into it after it was
        created. Explicit selections that named the dropped entry are pointed
        at the kept one. Result sets are left alone: their shards on disk carry
        the id they were computed for, and rewriting one here would claim a
        result the file does not hold.
        """
        kept_by_relpath = {
            _compare_path(s.relpath): s for s in self.sources if s.root_id == keep.id
        }
        renamed: Dict[str, str] = {}
        for entry in [s for s in self.sources if s.root_id == drop.id]:
            survivor = kept_by_relpath.get(_compare_path(entry.relpath))
            if survivor is None:
                entry.root_id = keep.id
                kept_by_relpath[_compare_path(entry.relpath)] = entry
                continue
            survivor.metadata.update(entry.metadata)
            survivor.unit_overrides.update(entry.unit_overrides)
            survivor.setup_label = entry.setup_label or survivor.setup_label
            survivor.in_pool = survivor.in_pool or entry.in_pool
            renamed[entry.id] = survivor.id
            self.sources.remove(entry)

        if renamed:
            self.selections = [
                replace(s, source_ids=tuple(dict.fromkeys(
                    renamed.get(sid, sid) for sid in s.source_ids)))
                for s in self.selections
            ]
        self.data_roots.remove(drop)

    def add_source(self, source: SourceEntry) -> SourceEntry:
        self.sources.append(source)
        return source

    def add_result_set(self, result_set: ResultSetRef) -> ResultSetRef:
        self.result_sets.append(result_set)
        return result_set

    def selection_by_name(self, name: str) -> Optional[MeasurementSelection]:
        return next((s for s in self.selections if s.name == name), None)

    def put_selection(self, selection: MeasurementSelection) -> MeasurementSelection:
        """
        Stores `selection`, replacing any selection of the same name in place.

        Replacing rather than appending, and in place rather than at the end,
        because the name is how a recipe refers to a selection: two entries
        called "Campaign A" would make "run over Campaign A" ambiguous, and
        re-saving one would otherwise reshuffle the list the user reads.
        """
        existing = self.selection_by_name(selection.name)
        if existing is None:
            self.selections.append(selection)
        else:
            self.selections[self.selections.index(existing)] = selection
        return selection

    def remove_selection(self, name: str) -> bool:
        existing = self.selection_by_name(name)
        if existing is None:
            return False
        self.selections.remove(existing)
        return True

    def workflow_by_name(self, name: str) -> Optional[Workflow]:
        return next((w for w in self.workflows if w.name == name), None)

    def put_workflow(self, workflow: Workflow) -> Workflow:
        """
        Stores `workflow`, replacing one of the same name in place -- the same
        reasoning as put_selection: the name is the handle a run refers to, and
        re-saving must not reshuffle the list the user reads.
        """
        existing = self.workflow_by_name(workflow.name)
        if existing is None:
            self.workflows.append(workflow)
        else:
            self.workflows[self.workflows.index(existing)] = workflow
        return workflow

    def remove_workflow(self, name: str) -> bool:
        existing = self.workflow_by_name(name)
        if existing is None:
            return False
        self.workflows.remove(existing)
        return True

    def filter_card_by_id(self, card_id: str) -> Optional[FilterCardConfig]:
        return next((c for c in self.filter_cards if c.id == card_id), None)

    def put_filter_card(self, card: FilterCardConfig) -> FilterCardConfig:
        """
        Stores `card`, replacing one of the same id in place -- the id is the
        handle a FilterProfile refers to, and re-saving must not reshuffle the
        list, the same reasoning as put_selection / put_workflow.
        """
        existing = self.filter_card_by_id(card.id)
        if existing is None:
            self.filter_cards.append(card)
        else:
            self.filter_cards[self.filter_cards.index(existing)] = card
        return card

    def remove_filter_card(self, card_id: str) -> bool:
        existing = self.filter_card_by_id(card_id)
        if existing is None:
            return False
        self.filter_cards.remove(existing)
        return True

    def touch(self) -> None:
        self.modified_utc = utc_now()

    # ---- serialisation ------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "format": "nvhproject",
            "format_version": self.format_version,
            "name": self.name,
            "created_utc": self.created_utc,
            "modified_utc": self.modified_utc,
            "data_roots": [r.to_dict() for r in self.data_roots],
            "sources": [s.to_dict() for s in self.sources],
            "result_sets": [rs.to_dict() for rs in self.result_sets],
            "selections": [s.to_dict() for s in self.selections],
            "workflows": [w.to_dict() for w in self.workflows],
            "filter_cards": [c.to_dict() for c in self.filter_cards],
            "metadata_schema": dict(self.metadata_schema),
            "ui_state": dict(self.ui_state),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NVHProject":
        return cls(
            format_version=int(data.get("format_version", PROJECT_FORMAT_VERSION)),
            name=data.get("name", "Untitled Project"),
            created_utc=data.get("created_utc") or utc_now(),
            modified_utc=data.get("modified_utc") or utc_now(),
            data_roots=[DataRoot.from_dict(d) for d in data.get("data_roots") or []],
            sources=[SourceEntry.from_dict(d) for d in data.get("sources") or []],
            result_sets=[ResultSetRef.from_dict(d) for d in data.get("result_sets") or []],
            selections=[MeasurementSelection.from_dict(d) for d in data.get("selections") or []],
            workflows=[Workflow.from_dict(d) for d in data.get("workflows") or []],
            filter_cards=[FilterCardConfig.from_dict(d) for d in data.get("filter_cards") or []],
            metadata_schema=dict(data.get("metadata_schema") or {}),
            ui_state=dict(data.get("ui_state") or {}),
        )


