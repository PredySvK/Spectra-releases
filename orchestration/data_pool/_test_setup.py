"""
Resolution of the Test setup a measurement gets when entering the Data Pool.

ADR §1.207:
Every measurement entering the Data Pool without a Test setup gets one
automatically:
1. Sibling measurements from the same folder that already carry a Test setup in
   the project (in or out of the pool) have priority: take the most common one,
   ties broken by the order Test setups were created in the project.
2. Otherwise take the folder's base name and, if any project source already
   carries it (in or out of the pool), append ` (2)`, ` (3)`, … until a name
   nobody carries is found.
3. A measurement that already has a Test setup is never overwritten.

The decision is made over plain data -- which paths entered, what Test setup
each known source carries -- so nothing here reads the session; the ingest
takes the snapshot and records the result.
"""

import os
from collections import Counter
from typing import Collection, Dict, Iterable, List, Mapping, Sequence

from io_modules.measurement_files import canonical_path


def resolve_test_setups(entered: Iterable[str], setup_by_path: Mapping[str, str],
                        setup_labels: Sequence[str]) -> Dict[str, str]:
    """
    The Test setup for each entered measurement that does not carry one yet.

    `entered` are the file paths that just came into the pool, as the scan
    spelled them (a folder's name is taken from that spelling).
    `setup_by_path` maps the canonical path of every source the project can
    place on disk, in the pool or not, to its Test setup ("" for none).
    `setup_labels` is every Test setup in the project in creation order,
    including those whose sources cannot be placed on disk right now.

    Returns {entered path: Test setup}; a path that already carries one is
    left out. Folders are decided in the order their first path arrives, and
    a name given to one folder is taken for the next.
    """
    setups_by_folder: Dict[str, List[str]] = {}
    for path, label in setup_by_path.items():
        if label:
            setups_by_folder.setdefault(canonical_path(os.path.dirname(path)), []).append(label)
    creation_index = {label: index for index, label in enumerate(setup_labels)}
    taken = set(setup_labels) | {label for label in setup_by_path.values() if label}

    unlabelled: Dict[str, List[str]] = {}
    for path in entered:
        if setup_by_path.get(canonical_path(path)):
            continue
        unlabelled.setdefault(canonical_path(os.path.dirname(path)), []).append(path)

    resolved: Dict[str, str] = {}
    for folder_key, paths in unlabelled.items():
        siblings = setups_by_folder.get(folder_key)
        if siblings:
            label = _majority_setup(siblings, creation_index)
        else:
            label = _unique_name(_base_name(os.path.dirname(paths[0])), taken)
        taken.add(label)
        setups_by_folder.setdefault(folder_key, []).extend([label] * len(paths))
        resolved.update((path, label) for path in paths)
    return resolved


def _majority_setup(labels: List[str], creation_index: Mapping[str, int]) -> str:
    counts = Counter(labels)
    top = max(counts.values())
    candidates = [label for label, count in counts.items() if count == top]
    # Tie: the Test setup created first; one the project does not list ranks
    # last, then by first appearance among the siblings.
    return min(candidates, key=lambda label: (creation_index.get(label, len(creation_index)),
                                              labels.index(label)))


def _base_name(folder: str) -> str:
    return os.path.basename(folder.rstrip("/\\")) or folder


def _unique_name(base: str, taken: Collection[str]) -> str:
    """Windows style: `Run 00`, `Run 00 (2)`, `Run 00 (3)`, …"""
    if base not in taken:
        return base
    index = 2
    while f"{base} ({index})" in taken:
        index += 1
    return f"{base} ({index})"
