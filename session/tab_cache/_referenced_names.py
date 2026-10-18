"""The set of Tab cache file names a project's saved tabs refer to."""

from typing import Any, Iterable, Mapping, Set


def build_referenced_tab_cache_names(open_tabs: Iterable[Mapping[str, Any]]) -> Set[str]:
    """
    Every `tab_cache_file` of every curve of every saved tab (`TabSpec.to_dict`
    form, as the project file holds it). Generic over the curves, so a base
    curve, an overlay or a dropped channel all count. Malformed entries are
    skipped: they cannot name a file.
    """
    names: Set[str] = set()
    for tab in open_tabs or ():
        traces = tab.get("traces") if isinstance(tab, Mapping) else None
        if not isinstance(traces, (list, tuple)):
            continue
        for trace in traces:
            name = trace.get("tab_cache_file") if isinstance(trace, Mapping) else None
            if name and isinstance(name, str):
                names.add(name)
    return names
