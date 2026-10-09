"""
Project-wide lookups a Trace needs to be resolved into a TraceIdentity.

Pure function (no Qt, no AppContext): reads the open project once, so every
caller of `identity_for_trace` builds identities from the same inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.project_model import SourceEntry


@dataclass(frozen=True)
class IdentityContext:
    """
    What `identity_for_trace` and the curve-identity builders read off the
    project: measurements by path, Result set labels (without them the Result
    set Identity facet stays None, §1.33) and the metadata schema.
    """

    sources_by_path: Dict[str, SourceEntry] = field(default_factory=dict)
    result_set_labels: Dict[str, str] = field(default_factory=dict)
    schema: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def build_identity_context(session: Optional[Any]) -> IdentityContext:
    """The context of `session`'s open project; empty when there is no session."""
    if session is None:
        return IdentityContext()
    project = session.project
    return IdentityContext(
        sources_by_path=session.sources_by_path(),
        result_set_labels={ref.id: ref.label for ref in project.result_sets},
        schema=project.metadata_schema,
    )
