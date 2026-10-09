"""FilterSelectionStore -- the Qt-free state half of FilterPanel (ADR §1.39).

FilterPanel is a QWidget, but a chunk of what it holds is pure data with no Qt
in it: the two dicts of checked state (one core.project_model.FilterSelection
shared app-wide per Global card, one per (card, dock) for Local cards), the
Global->None key fold, the §1.29 staleness bookkeeping (which offering a
(card, dock) last saw, whether it has been populated for real -- ADR §1.44),
and carrying all of that across a scope flip atomically. This class owns exactly
that, so the logic can be tested without a QApplication.

It is **stateless about "which card is active"** -- the panel owns
_active_profile_id / _current_dock_id and passes card_id + dock_id on every
call. It keeps its own light Dict[card_id, scope] (kept in sync by the panel on
add / scope flip / delete) so the fold does not need the Qt FilterProfile
objects.

Lives in session/trace_filter.py (ADR §1.57 / #170), not core/: Global/Local scoping
and per-dock keying is a session concept, holding the open project's evolving
filter selection state. core/ is pure data without behaviour over collections,
and session/ may import core/ and selection/ but not gui/. Glossary term: **Filter
selection** (CONTEXT.md).

This completes the expand--contract move in ADR §1.39: the two dicts and the
scope map (T1), the JSON (de)serialization and the ui_state export/import (T2),
the atomic migrate_scope (T3), and the contract step (T4) that dropped the
panel's 9 _checked_* property pairs for one self._sel window onto
active_selection().

The gui.handlers / gui.workspace persistence callers reach this straight through
the read-only FilterPanel.selection_store property (ADR §1.51), not through a
forwarding method per call. serialize_profile_identities / restore_profile_identities
moved off FilterPanel too, onto FilterProfileRegistry below (ADR §1.68 / #177) --
that class owns the profile list itself, so FilterPanel no longer holds any of
this component's Qt-free state.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.project_model import FilterProfile, FilterSelection
from selection.trace_filter import OfferedFacets
from selection.source_facets import channel_identity_sort_key

SelectionKey = Tuple[str, Optional[str]]

# FilterProfileRegistry.add_profile's owner_dock_id default: "derive it from
# the focused dock" (a fresh custom Local card), as opposed to an explicit
# None passed by a restore of a pre-§1.37 project.
OWNER_FROM_FOCUS = object()

# The two fixed profiles that always exist -- "Global" (global scope) and
# "Local" (local scope), never removable, recreated fresh by FilterPanel on
# every startup rather than round-tripped (their identity never changes).
BUILTIN_GLOBAL_ID = "__global__"
BUILTIN_LOCAL_ID = "__local__"


def _signature_to_json(signature: Tuple) -> list:
    """A Parameter Set signature as nested JSON lists -- every tuple in it
    (the pairs, and a list/dict param already flattened to a tuple by
    selection.parameter_sets) becomes a list, and a numpy scalar (a
    compute_spec value can be one) its plain Python value, which json can write."""
    return [_signature_to_json(item) if isinstance(item, tuple)
            else item.item() if hasattr(item, "dtype") else item
            for item in signature]


def _signature_from_json(raw: list) -> Tuple:
    """Inverse of _signature_to_json: every list back to a tuple, so the
    signature is hashable again and compares equal to a freshly built one."""
    return tuple(_signature_from_json(item) if isinstance(item, list) else item for item in raw)


def serialize_selection(selection: FilterSelection) -> dict:
    """One FilterSelection as a JSON-safe dict -- the shape export_global_selections
    / export_local_selections_for_dock persist into a project's ui_state. Sets are
    sorted so the saved file is stable across runs."""
    return {
        "checked_metadata_values": {
            key: sorted(values) for key, values in selection.checked_metadata_values.items()
        },
        "checked_identity_values": {
            key: sorted(values) for key, values in selection.checked_identity_values.items()
        },
        "checked_channel_identities": [
            list(identity) for identity
            in sorted(selection.checked_channel_identities, key=channel_identity_sort_key)
        ],
        "checked_orders": sorted(selection.checked_orders),
        # Sorted by their JSON text: a signature's values mix str/float/None,
        # which do not order against each other.
        "checked_parameter_set_signatures": sorted(
            (_signature_to_json(signature) for signature in selection.checked_parameter_set_signatures),
            key=json.dumps,
        ),
        "checked_result_kinds": sorted(selection.checked_result_kinds),
        "checked_ranges": dict(selection.checked_ranges),
        "checked_empty_buckets": sorted(selection.checked_empty_buckets),
    }


def deserialize_selection(raw: dict) -> FilterSelection:
    """Inverse of serialize_selection() -- a missing key restores as empty, so an
    older or partial save still loads. A pre-#349 save's
    `checked_parameter_set_indices` is dropped: those numbers were per-round
    positions with nothing left to resolve them against, so the first populate
    after loading re-ticks every Parameter Set on offer."""
    return FilterSelection(
        checked_metadata_values={
            key: set(values) for key, values in raw.get("checked_metadata_values", {}).items()
        },
        checked_identity_values={
            key: set(values) for key, values in raw.get("checked_identity_values", {}).items()
        },
        checked_channel_identities={tuple(identity) for identity in raw.get("checked_channel_identities", [])},
        checked_orders={float(order) for order in raw.get("checked_orders", [])},
        checked_parameter_set_signatures={
            _signature_from_json(signature)
            for signature in raw.get("checked_parameter_set_signatures", [])
        },
        checked_result_kinds=set(raw.get("checked_result_kinds", [])),
        checked_ranges={key: tuple(bounds) for key, bounds in raw.get("checked_ranges", {}).items()},
        checked_empty_buckets=set(raw.get("checked_empty_buckets", [])),
    )


class FilterSelectionStore:
    """Owns the two selection dicts and the card_id -> scope map."""

    def __init__(self) -> None:
        self._global: Dict[str, FilterSelection] = {}
        self._local: Dict[SelectionKey, FilterSelection] = {}
        # Light mirror of each card's scope -- the panel keeps this synced so
        # the Global->None fold below never needs a FilterProfile object.
        self._scope: Dict[str, str] = {}
        # The §1.29 staleness bookkeeping, moved here from FilterPanel (ADR
        # §1.44): what a (card, dock) was last offered for real, and whether it
        # has been populated for real at all. Keyed by selection_key() -- the
        # same fold as the selections themselves -- so a scope flip carries all
        # four maps atomically and the Global->None fold exists once.
        self._offered: Dict[SelectionKey, OfferedFacets] = {}
        self._seen: Set[SelectionKey] = set()

    # ---- scope bookkeeping (the panel keeps this in sync) -----------------

    def set_scope(self, card_id: str, scope: str) -> None:
        """Record a card's scope -- called from FilterPanel._add_profile."""
        self._scope[card_id] = scope

    def scope_of(self, card_id: str) -> Optional[str]:
        return self._scope.get(card_id)

    def _is_global(self, card_id: str) -> bool:
        return self._scope.get(card_id) == "global"

    # ---- key + lookup ---------------------------------------------------

    def selection_key(self, card_id: str, dock_id: Optional[str]) -> SelectionKey:
        """Normalizes (card, dock) to the key that identifies a FilterSelection
        -- a Global card's dock is always folded to None since it shares one
        selection app-wide, so code comparing keys does not special-case scope."""
        return (card_id, None if self._is_global(card_id) else dock_id)

    def active_selection(self, card_id: str, dock_id: Optional[str]) -> FilterSelection:
        """The FilterSelection a (card, dock) combo resolves to, creating an
        empty one on first access -- a dock that has never touched this card
        just starts with nothing checked, no claiming needed."""
        if self._is_global(card_id):
            return self._global.setdefault(card_id, FilterSelection())
        return self._local.setdefault((card_id, dock_id), FilterSelection())

    def local_selections_for_dock(self, dock_id: Optional[str]) -> Dict[str, FilterSelection]:
        """Every Local card's own selection for `dock_id`, keyed by card id --
        what a dock's TabSpec carries across a save/reopen."""
        return {
            card_id: selection
            for (card_id, d_id), selection in self._local.items()
            if d_id == dock_id
        }

    # ---- §1.29 staleness bookkeeping (ADR §1.44) ------------------------

    def offered_facets(self, card_id: str, dock_id: Optional[str]) -> Optional[OfferedFacets]:
        """What the (card, dock) was last offered for real, or None if it never
        has -- the None resolve_panel_render reads as "first real populate"."""
        return self._offered.get(self.selection_key(card_id, dock_id))

    def record_offering(self, card_id: str, dock_id: Optional[str], offering: OfferedFacets) -> None:
        """Remember this round's offering for the (card, dock) -- the mask needs
        it to tell "unchecked" from "never asked about" while another dock has
        focus (§1.29)."""
        self._offered[self.selection_key(card_id, dock_id)] = offering

    def mark_seen(self, card_id: str, dock_id: Optional[str]) -> None:
        """Record that populate_facets has run for real for this (card, dock)."""
        self._seen.add(self.selection_key(card_id, dock_id))

    def has_seen(self, card_id: str, dock_id: Optional[str]) -> bool:
        return self.selection_key(card_id, dock_id) in self._seen

    def _migrate_bookkeeping(self, old_key: SelectionKey, new_key: SelectionKey) -> None:
        """Carry the offering and seen mark for `old_key` over to `new_key` --
        the offering belongs with the checked state it was measured against, or
        a scope flip would keep a mask's picks while forgetting what was on
        offer (§1.29)."""
        if old_key in self._offered:
            self._offered[new_key] = self._offered.pop(old_key)
        if old_key in self._seen:
            self._seen.discard(old_key)
            self._seen.add(new_key)

    # ---- mutation -----------------------------------------------------

    def migrate_scope(self, card_id: str, new_scope: str, dock_id: Optional[str]) -> None:
        """Flip a card's scope, carrying its current checked state -- and its
        offering / seen mark -- over to the other store rather than starting it
        empty. Keyed by `dock_id` -- the dock in focus when the flip happened is
        the one whose Local state becomes (or came from) the one shared Global
        value."""
        if self._scope.get(card_id) == new_scope:
            return
        if new_scope == "global":
            self._global[card_id] = self._local.pop((card_id, dock_id), FilterSelection())
            old_key, new_key = (card_id, dock_id), (card_id, None)
        else:
            self._local[(card_id, dock_id)] = self._global.pop(card_id, FilterSelection())
            old_key, new_key = (card_id, None), (card_id, dock_id)
        self._scope[card_id] = new_scope
        self._migrate_bookkeeping(old_key, new_key)

    def copy_selections(self, src_id: str, dst_id: str) -> None:
        """Clone every FilterSelection `src_id` holds onto `dst_id`, under the
        same dock keys -- a Global card has one shared selection, a Local one a
        separate selection per dock it has ever been checked against. The panel
        registers `dst_id`'s scope (via set_scope) before calling this."""
        if self._scope.get(src_id) == "global":
            if src_id in self._global:
                self._global[dst_id] = copy.deepcopy(self._global[src_id])
        else:
            for (card_id, dock_id), selection in list(self._local.items()):
                if card_id == src_id:
                    self._local[(dst_id, dock_id)] = copy.deepcopy(selection)
        for (card_id, dock_id), offering in list(self._offered.items()):
            if card_id == src_id:
                self._offered[(dst_id, dock_id)] = replace(
                    offering,
                    identity_values=dict(offering.identity_values),
                    metadata_values=dict(offering.metadata_values),
                )
        self._seen |= {
            (dst_id, dock_id) for (card_id, dock_id) in self._seen if card_id == src_id
        }

    def forget_profile(self, card_id: str) -> None:
        """Drop every trace of a card -- its shared Global selection, every
        per-dock Local one, its scope entry, and its offering / seen marks."""
        self._global.pop(card_id, None)
        for key in [k for k in self._local if k[0] == card_id]:
            del self._local[key]
        self._scope.pop(card_id, None)
        self._offered = {k: v for k, v in self._offered.items() if k[0] != card_id}
        self._seen = {k for k in self._seen if k[0] != card_id}

    def clear_selections(self) -> None:
        """Drop every checked state and offering/seen mark but keep each
        card's scope -- the cards themselves outlive a project switch
        (FilterProfileRegistry.reset_to_builtins), their picks do not."""
        self._global.clear()
        self._local.clear()
        self._offered.clear()
        self._seen.clear()

    # ---- serialization: a project's ui_state round-trip (ADR §1.39 T2) ----
    #
    # import_* rejects an entry whose card is gone by testing `card_id in
    # self._scope` -- the panel syncs that map on every add/delete, so this
    # needs no Qt FilterProfile object (ADR §1.39, "Scope bez leaku").

    def export_global_selections(self) -> Dict[str, dict]:
        """Every Global card's one shared selection, JSON-safe, keyed by card id."""
        return {
            card_id: serialize_selection(self._global.get(card_id) or FilterSelection())
            for card_id, scope in self._scope.items()
            if scope == "global"
        }

    def import_global_selections(self, raw: Dict[str, dict]) -> None:
        """Inverse of export_global_selections() -- skips an entry for a card
        that no longer exists."""
        for card_id, data in raw.items():
            if card_id in self._scope:
                self._global[card_id] = deserialize_selection(data)

    def export_local_selections_for_dock(self, dock_id: Optional[str]) -> Dict[str, dict]:
        """`dock_id`'s own selection across every Local card it has been checked
        against, JSON-safe, keyed by card id -- what a dock's TabSpec carries."""
        return {
            card_id: serialize_selection(selection)
            for card_id, selection in self.local_selections_for_dock(dock_id).items()
        }

    def import_local_selections_for_dock(self, dock_id: Optional[str], raw: Dict[str, dict]) -> None:
        """Inverse of export_local_selections_for_dock() -- same skip-unknown-card
        rule as import_global_selections()."""
        for card_id, data in raw.items():
            if card_id in self._scope:
                self._local[(card_id, dock_id)] = deserialize_selection(data)

    def snapshot_for(self, card_id: str, dock_id: Optional[str]) -> dict:
        """JSON-safe dict of the selection a (card, dock) resolves to -- the
        staleness key apply_active_filter_to_dock compares against."""
        return serialize_selection(self.active_selection(card_id, dock_id))


class FilterProfileRegistry:
    """Owns FilterPanel's Qt-free profile bookkeeping (ADR §1.68 / #177): the
    list of FilterProfile identities, which one is active app-wide, which dock
    currently has focus, and the per-dock memory of a custom Local card's last
    active state (ADR §1.37, ticket #66).

    This is the other half of what #170 already carried into session/ as
    FilterSelectionStore -- that class owns the checked *values*, this one
    owns *which cards exist and which is showing*. The two are related (a
    profile's scope decides how its selection is keyed, and removing or
    flipping a profile must carry its selection along), so this registry is
    constructed with a FilterSelectionStore and drives it through the same
    calls FilterPanel used to make directly.

    Stays Qt-free by design: every method here only touches this data. The
    Qt side -- rebuilding the tab bar, updating checkboxes, emitting
    signals, replaying the last populate_facets() -- is FilterPanel's job.
    Several methods therefore split what used to be one panel method in two:
    this class computes what changed (and whether it changed), and the panel
    decides what to draw because of it.
    """

    def __init__(self, selection_store: FilterSelectionStore) -> None:
        self._store = selection_store
        self._profiles: List[FilterProfile] = []
        self._active_profile_id: Optional[str] = None
        self._current_dock_id: Optional[str] = None
        # {dock_id: last active profile id while that dock had focus} --
        # never persisted: after a reopen each dock starts on the fallback.
        self._active_card_by_dock: Dict[str, str] = {}

    # ---- read access ------------------------------------------------------

    @property
    def profiles(self) -> List[FilterProfile]:
        return self._profiles

    @property
    def active_profile_id(self) -> Optional[str]:
        return self._active_profile_id

    @property
    def current_dock_id(self) -> Optional[str]:
        return self._current_dock_id

    def profile_by_id(self, profile_id: Optional[str]) -> Optional[FilterProfile]:
        return next((p for p in self._profiles if p.id == profile_id), None)

    def active_profile(self) -> FilterProfile:
        for profile in self._profiles:
            if profile.id == self._active_profile_id:
                return profile
        # Guards against a corrupted active id rather than a state that
        # should ever occur -- add_profile/remove_profile keep it in sync.
        return self._profiles[0]

    def profile_is_dock_local(self, profile_id: str) -> bool:
        """True for a custom (non-builtin) Local card -- one whose tab shows
        only while its owner dock has focus, so it is the kind of card the
        per-dock active memory exists for."""
        profile = self.profile_by_id(profile_id)
        return profile is not None and not profile.builtin and profile.scope == "local"

    def visible_profiles(self) -> List[FilterProfile]:
        """The profiles whose tabs show for the focused dock, in tab order
        (§1.37): the two builtins, then every custom Global card, then only
        those custom Local cards owned by the focused dock. A custom Local
        card whose owner_dock_id is some other dock is simply absent from the
        bar until that dock has focus again."""
        builtins = [p for p in self._profiles if p.builtin]
        custom_global = [p for p in self._profiles if not p.builtin and p.scope == "global"]
        custom_local = [
            p for p in self._profiles
            if not p.builtin and p.scope == "local" and p.owner_dock_id == self._current_dock_id
        ]
        return builtins + custom_global + custom_local

    # ---- mutation ----------------------------------------------------------

    def add_profile(self, name: str, scope: str = "local", builtin: bool = False,
                     profile_id: Optional[str] = None,
                     owner_dock_id: Any = OWNER_FROM_FOCUS) -> FilterProfile:
        """Appends a new profile and registers its scope with the selection
        store. Does not activate it and does not touch the tab bar -- the
        panel's own _add_profile wraps this with make_active / _rebuild_tab_bar."""
        # A custom "local" card is owned by the dock in focus when it is
        # created (§1.37) -- only for tab visibility, the checked state stays
        # keyed by (profile, dock). A builtin or a "global" card has no
        # owner; a restore passes owner_dock_id explicitly (including None
        # for a pre-§1.37 save).
        if owner_dock_id is OWNER_FROM_FOCUS:
            owner_dock_id = self._current_dock_id if (not builtin and scope == "local") else None
        kwargs = dict(name=name, scope=scope, builtin=builtin, owner_dock_id=owner_dock_id)
        if profile_id is not None:
            kwargs["id"] = profile_id
        profile = FilterProfile(**kwargs)
        self._profiles.append(profile)
        self._store.set_scope(profile.id, profile.scope)
        return profile

    def set_active_profile_id(self, profile_id: str) -> bool:
        """Points the active pointer at `profile_id`; no-op (returns False)
        if it names no known profile. Pure pointer update -- FilterPanel's
        _activate_profile wraps this with the Qt-side effects (checkbox
        state, replaying the last populate, the active_profile_focus_changed
        signal)."""
        if self.profile_by_id(profile_id) is None:
            return False
        self._active_profile_id = profile_id
        return True

    def set_current_dock_id(self, dock_id: Optional[str]) -> Optional[str]:
        """Records the dock that just gained focus, remembering the
        previously-focused dock's active profile before moving on. Returns
        the dock that was left (or None if `dock_id` was already current, or
        there was no dock in focus before) -- the caller does not need it,
        it is only there so a test can observe the memory write happened."""
        if dock_id == self._current_dock_id:
            return None
        leaving = self._current_dock_id
        if leaving is not None and self._active_profile_id is not None:
            self._active_card_by_dock[leaving] = self._active_profile_id
        self._current_dock_id = dock_id
        return leaving

    def resolve_active_for_focused_dock(self) -> Optional[str]:
        """Picks the active card for the dock that just gained focus (ADR
        §1.37, ticket #66): a remembered custom Local card owned by this dock
        wins -- that is the click the user should not have to redo.
        Otherwise the app-wide active card stays if it is visible here; if it
        is not (a custom Local card owned by the dock just left, or one that
        has since been deleted), fall back to the "Local" builtin. Returns
        the profile id FilterPanel should activate, or None if the current
        active profile should simply stay active."""
        visible_ids = {p.id for p in self.visible_profiles()}
        remembered = self._active_card_by_dock.get(self._current_dock_id)
        if (remembered is not None and remembered in visible_ids
                and self.profile_is_dock_local(remembered)):
            target = remembered
        elif self._active_profile_id in visible_ids:
            return None
        else:
            target = BUILTIN_LOCAL_ID
        return target if target != self._active_profile_id else None

    def prune_active_card_memory(self) -> None:
        """Drops dict entries pointing at a card that no longer exists --
        called after a profile or a dock's cards are removed (ADR §1.37)."""
        self._active_card_by_dock = {
            dock_id: profile_id
            for dock_id, profile_id in self._active_card_by_dock.items()
            if self.profile_by_id(profile_id) is not None
        }

    def set_profile_scope(self, profile_id: str, new_scope: str) -> bool:
        """Flips a custom profile's scope -- the tab bar's context menu's
        "Make Global"/"Make Local" (not offered for either builtin). Carries
        the profile's current checked state over to its new storage location
        in the selection store (keyed by the now-focused dock) rather than
        starting it over empty, so flipping never looks like it discarded a
        pick. Returns False (no-op) for an unknown profile, a builtin, a
        scope that already matches, or flipping to local when no dock is
        focused (there is no dock to own it, §1.37)."""
        profile = self.profile_by_id(profile_id)
        if profile is None or profile.builtin or profile.scope == new_scope:
            return False
        if new_scope == "local" and self._current_dock_id is None:
            return False
        # migrate_scope carries the checked state, the offering and the seen
        # mark together (ADR §1.44) -- the flipped card must not keep a
        # mask's checked values while forgetting which of them were ever on
        # offer (§1.29).
        self._store.migrate_scope(profile_id, new_scope, self._current_dock_id)
        profile.scope = new_scope
        # "Make Global" -> visible everywhere; "Make Local" re-homes the card
        # under whichever dock is focused now, with no memory of a prior
        # owner (§1.37).
        profile.owner_dock_id = self._current_dock_id if new_scope == "local" else None
        return True

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        new_name = new_name.strip()
        if not new_name:
            return False
        for profile in self._profiles:
            if profile.id == profile_id:
                profile.name = new_name
                return True
        return False

    def remove_profile(self, profile_id: str) -> Optional[bool]:
        """Refuses to remove a builtin -- "Global" and "Local" always exist.
        Returns None (no-op) for an unknown id or a builtin, otherwise
        whether the removed profile was the active one -- so the caller
        knows to fall back to the "Local" builtin specifically (not just
        "whatever is first"): it is always there to land on, the same way
        closing a custom view returns you to a default one."""
        profile = self.profile_by_id(profile_id)
        if profile is None or profile.builtin:
            return None
        was_active = self._active_profile_id == profile_id
        self._profiles = [p for p in self._profiles if p.id != profile_id]
        self._store.forget_profile(profile_id)
        self.prune_active_card_memory()
        return was_active

    def doomed_local_cards(self, is_orphan: Callable[[Optional[str]], bool]) -> List[str]:
        """Ids of every custom Local card whose owner_dock_id satisfies
        `is_orphan` -- the shared predicate behind drop_owned_local_cards
        (FilterPanel.forget_dock and .prune_orphan_dock_cards)."""
        return [
            p.id for p in self._profiles
            if not p.builtin and p.scope == "local" and is_orphan(p.owner_dock_id)
        ]

    def drop_owned_local_cards(self, is_orphan: Callable[[Optional[str]], bool]) -> bool:
        """Removes every custom Local card whose owner_dock_id satisfies
        `is_orphan` (and with it, via remove_profile, its selections and
        offerings). Returns whether the active profile was among them, so
        the caller knows to fall back to the "Local" builtin -- the one Qt
        decision (which tab becomes current) this class cannot make for
        itself. FilterPanel.forget_dock and .prune_orphan_dock_cards differ
        only in the predicate they pass."""
        fell_back = False
        for profile_id in self.doomed_local_cards(is_orphan):
            if self.remove_profile(profile_id):
                fell_back = True
        return fell_back

    def drop_dock_memory(self, dock_id: str) -> None:
        """Drops `dock_id`'s restore memory -- called once the dock is closed,
        so the memory is dead weight."""
        self._active_card_by_dock.pop(dock_id, None)

    def duplicate_profile_identity(self, source_profile_id: str) -> Optional[FilterProfile]:
        """Adds a profile that copies `source_profile_id`'s scope -- the
        identity half of the tab bar context menu's "Duplicate" (ticket #47).
        The copy is never builtin, even when the source is. Returns None if
        the source is unknown. Cloning the checked state (store.copy_selections),
        activating the copy and emitting profile_duplicated are left to the
        caller -- they need the column configuration copy to have happened
        first (gui.handlers.filter_routing) and touch Qt state."""
        source = self.profile_by_id(source_profile_id)
        if source is None:
            return None
        return self.add_profile(f"{source.name} copy", scope=source.scope)

    # ---- persisting/restoring profiles (T5) --------------------------------

    def reset_to_builtins(self) -> None:
        """Back to the state FilterPanel.__init__ leaves: only the two builtins,
        nothing checked, the Local builtin active, no per-dock memory. Run on
        every project switch before a saved state is restored (issue #372) --
        the cards and picks belong to the outgoing project, so a project with
        nothing saved must not inherit them. Leaves which dock has focus alone:
        that is the workspace's, not the project's."""
        for profile in self._profiles:
            if not profile.builtin:
                self._store.forget_profile(profile.id)
        self._profiles = [p for p in self._profiles if p.builtin]
        self._store.clear_selections()
        self._active_card_by_dock = {}
        self._active_profile_id = BUILTIN_LOCAL_ID

    def serialize_profile_identities(self) -> List[dict]:
        """Custom profiles' identity only, JSON-safe -- the two builtins are
        recreated fresh by FilterPanel.__init__ every time rather than
        round-tripped, since their identity (id, name, scope) never changes.
        No selection here: a Global profile's content comes from
        FilterSelectionStore.export_global_selections(), a Local one's from
        whichever TabSpec holds it."""
        return [
            {"id": p.id, "name": p.name, "scope": p.scope, "owner_dock_id": p.owner_dock_id}
            for p in self._profiles if not p.builtin
        ]

    def restore_profile_identities(self, raw_profiles: List[dict]) -> None:
        """Adds back the custom profiles (identity only) from a saved list
        (gui.handlers.filter_routing.restore_filter_state, called once
        right after a project opens -- never on an ordinary refresh)
        alongside the two builtins FilterPanel.__init__ always creates. No-op
        if nothing was saved. Call before
        FilterSelectionStore.import_global_selections() /
        import_local_selections_for_dock(): both need the profile to already
        exist to key into."""
        for raw in raw_profiles:
            scope = raw.get("scope", "local")
            owner_dock_id = raw.get("owner_dock_id")
            # Migration (§1.37): a custom Local card saved before
            # owner_dock_id existed is promoted to Global -- it stays usable
            # and can be flipped back, rather than vanishing because no dock
            # will ever match a missing owner.
            if scope == "local" and "owner_dock_id" not in raw:
                scope = "global"
                owner_dock_id = None
            self.add_profile(raw["name"], scope=scope, profile_id=raw.get("id"),
                              owner_dock_id=owner_dock_id)

    def resolve_restore_target(self, profile_id: Optional[str]) -> str:
        """Which profile id to activate for a restored `profile_id` --
        falling back to the Local builtin when it names no known profile (an
        older save's differently-shaped pointer, or simply nothing saved).
        Call after restore_profile_identities() so custom profiles are
        already registered."""
        return profile_id if self.profile_by_id(profile_id) is not None else BUILTIN_LOCAL_ID


@dataclass(frozen=True)
class FilterStateSnapshot:
    """The Filter panel's whole profile list + Global content, as read back
    from a project's ui_state (ticket #178) -- what
    gui.handlers.filter_routing.restore_filter_state hands to the
    panel's own restore calls, and what its two checkbox writes (Data Pool
    filtering, Show all) read directly rather than through this class, since
    writing a checkbox without emitting is Qt glue that stays in gui/."""
    profiles: List[dict]
    global_selections: Dict[str, dict]
    active_profile_id: Optional[str]
    filter_data_pool: bool
    show_all: bool


def build_filter_state_snapshot(*, filter_data_pool: bool, show_all: bool,
                                 profiles: List[dict], global_selections: Dict[str, dict],
                                 active_profile_id: Optional[str]) -> dict:
    """The JSON-safe dict gui.handlers.filter_routing._persist_filter_state
    writes into a project's ui_state under FILTER_STATE_KEY (ticket #178) --
    the panel's Local content is not in here at all, it travels on each
    dock's own TabSpec instead (see FilterStateSnapshot)."""
    return {
        "filter_data_pool": filter_data_pool,
        "show_all": show_all,
        "profiles": profiles,
        "global_selections": global_selections,
        "active_profile_id": active_profile_id,
    }


def read_filter_state_snapshot(saved: dict) -> FilterStateSnapshot:
    """Inverse of build_filter_state_snapshot() -- a missing key restores as
    empty/False, so an older or partial save (including a pre-T5 shape with
    none of these keys at all) still loads onto clean builtins instead of
    crashing (ticket #178)."""
    return FilterStateSnapshot(
        profiles=saved.get("profiles", []),
        global_selections=saved.get("global_selections", {}),
        active_profile_id=saved.get("active_profile_id"),
        filter_data_pool=bool(saved.get("filter_data_pool", False)),
        show_all=bool(saved.get("show_all", False)),
    )
