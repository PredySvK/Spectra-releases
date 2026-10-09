"""
Which traces of a ``PlotModel`` are visible -- the mask, X-domain and
third-secondary-axis decision a graph draws through (issue #70, ADR §1.50).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from core.axis_projections import can_project
from core.units import check_units_compatibility

from ._plot_model import PlotModel, Trace


# =====================================================================
# Which traces are visible -- the one decision _draw_all() and the
# incremental overlay path (graph_dock.add_curve) share,
# so the same graph can't read two ways ("drawn now, gone after the next
# render"). Pure: a PlotModel + a mask predicate + the dock's X domain in,
# a draw list plus the reason anything is missing out. See issue #70.
# =====================================================================

# The mask _draw_all() draws through: None means "no filter, draw everything"
# (GraphCurves.trace_filter). A hidden trace stays in the model's recipe --
# masking is a view state, not a data edit (ARCHITECTURE_DECISIONS §1.28).
Mask = Optional[Callable[[Trace], bool]]


class HiddenReason(enum.Enum):
    """Why ``resolve_visible_traces`` returned fewer curves than the model
    holds. ``_draw_all()`` maps this onto the title wording -- the *decision*
    lives here, the phrasing stays with the renderer because it needs
    ``view.title`` and the domain name."""

    NONE = "none"
    MASK = "mask"          # the user's filter hid them (ADR §1.25 wording kept)
    X_DOMAIN = "x_domain"  # nothing survives the X projection (ADR §1.30)
    THIRD_AXIS = "third_axis"  # a third incompatible secondary unit, no ViewBox for it


class AcceptOutcome(enum.Enum):
    """What the incremental overlay path should do with one newly appended
    trace, per ``VisibleTraces.accepts``."""

    DRAWN = "drawn"              # draw it, bump the overlay count
    HIDDEN_MASK = "hidden_mask"  # mask hid it but others still show -- silently skip
    NEEDS_RENDER = "needs_render"  # fall back to a full _draw_all() so it writes the title


def trace_fits_x_domain(trace: Trace, domain: str) -> bool:
    """Whether ``trace`` can be drawn against a dock whose X domain is
    ``domain``. Undeclared (``""``) on either side draws unconditionally
    (plot_model.Trace docstring); otherwise a matching quantity is free and
    anything else needs a registered, exact projection (ADR §1.30)."""
    if not domain or not trace.x_quantity:
        return True
    return can_project(trace.x_quantity, domain, trace.compute_spec or {})


def drop_third_axis_unit(traces: List[Trace]) -> Tuple[List[Trace], int, Optional[str]]:
    """Only one secondary Y axis exists (``SecondaryAxis.ensure`` replaces
    rather than stacks). The first secondary unit encountered wins the axis;
    a later secondary trace whose unit doesn't fit it is excluded here
    instead of drawn-then-erased, so it can be reported (ADR §1.30 / plan F6).
    Returns the kept traces, how many were dropped, and the unit that won."""
    kept: List[Trace] = []
    established_unit: Optional[str] = None
    dropped = 0
    for trace in traces:
        if trace.axis == "secondary":
            if established_unit is None:
                established_unit = trace.unit
            elif not check_units_compatibility(trace.unit, established_unit):
                dropped += 1
                continue
        kept.append(trace)
    return kept, dropped, established_unit


@dataclass
class VisibleTraces:
    """The outcome of the visibility decision for one full render pass, and
    -- via ``accepts`` -- the running state the incremental overlay path
    checks each new curve against without an O(N^2) full re-resolve."""

    draw: List[Trace] = field(default_factory=list)
    hidden_reason: HiddenReason = HiddenReason.NONE
    total: int = 0
    mask_passed: int = 0
    third_axis_dropped: int = 0
    established_secondary_unit: Optional[str] = None

    def accepts(self, trace: Trace, mask: Mask, x_domain: str) -> AcceptOutcome:
        """Would this one newly appended ``trace`` survive, given what is
        already drawn? Same checks as ``resolve_visible_traces``, in the same
        order (mask -> X domain -> third secondary unit). On ``DRAWN`` the
        trace is appended to ``draw`` and may claim the secondary axis, so a
        second overlay curve sees it."""
        if mask is not None and not mask(trace):
            return AcceptOutcome.HIDDEN_MASK if self.draw else AcceptOutcome.NEEDS_RENDER
        if not trace_fits_x_domain(trace, x_domain):
            return AcceptOutcome.NEEDS_RENDER
        if trace.axis == "secondary" and self.established_secondary_unit is not None:
            if not check_units_compatibility(trace.unit, self.established_secondary_unit):
                return AcceptOutcome.NEEDS_RENDER

        self.draw.append(trace)
        if trace.axis == "secondary" and self.established_secondary_unit is None:
            self.established_secondary_unit = trace.unit
        return AcceptOutcome.DRAWN


def resolve_visible_traces(model: PlotModel, mask: Mask, x_domain: str) -> VisibleTraces:
    """The full-pass visibility decision: mask -> X-domain fit -> drop a
    third secondary unit, then classify why anything is missing.

    ``mask`` hiding *some but not all* traces is not a hidden reason -- the
    curves that remain are shown and that is the normal filtered state. Only
    an empty draw list, or a dropped third axis, gets reported. When the
    draw list is empty and the mask hid *any* trace at all, that reads as
    MASK (matching the pre-existing "Filter hid N of N" wording); otherwise
    the X domain is the cause."""
    total = len(model.traces)
    passed = list(model.traces) if mask is None else [t for t in model.traces if mask(t)]
    mask_passed = len(passed)

    fitting = [t for t in passed if trace_fits_x_domain(t, x_domain)]
    kept, dropped, established = drop_third_axis_unit(fitting)

    if total and not kept:
        reason = HiddenReason.MASK if mask_passed < total else HiddenReason.X_DOMAIN
    elif dropped:
        reason = HiddenReason.THIRD_AXIS
    else:
        reason = HiddenReason.NONE

    return VisibleTraces(
        draw=kept,
        hidden_reason=reason,
        total=total,
        mask_passed=mask_passed,
        third_axis_dropped=dropped,
        established_secondary_unit=established,
    )
