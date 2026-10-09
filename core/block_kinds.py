# =====================================================================
# FILE: core/block_kinds.py
# =====================================================================
"""
The register of block kinds: what each kind of NVHDataBlock means, and what a
valid one of that kind has to look like.

Lives in core/ next to the block itself -- these are rules about pure data,
with no I/O and no Qt.

Adding a result type (order trend, Campbell, cepstrum, FRF, TSA, ...) is one
entry here plus one factory on NVHDataBlock. Nothing else in the codebase
branches on `kind`, so nothing else has to learn about the new one; that is the
whole reason the discriminator is data rather than a subclass tree.

What earns a `kind` and what does not:

    `kind` distinguishes what needs a different renderer or different axis
    semantics. What only changes units -- spectrum_format's linear / power /
    psd / esd -- is a processing parameter.

The same split UFF dataset 58 makes with func_type + ordinate_data_type +
abscissa_spacing as three independent codes rather than 27 record types.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# Kind names. Referenced as constants so a typo is an ImportError rather than a
# block that silently fails validation at runtime.
KIND_TIME_RESPONSE = "time_response"
KIND_SPECTRUM = "spectrum"
KIND_SPECTROGRAM = "spectrogram"
KIND_ORDER_CUT = "order_cut"
KIND_OVERALL_LEVEL = "overall_level"
KIND_ORDER_RESIDUAL = "order_residual"

# Curves that scale with the RMS / Peak switch, and the two of them that
# are levels rather than order cuts. One place, so a new kind is one edit.
RMS_PEAK_CURVE_KINDS = (KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_ORDER_RESIDUAL)
LEVEL_CURVE_KINDS = (KIND_OVERALL_LEVEL, KIND_ORDER_RESIDUAL)

# Key under which an order cut records which order it is, in
# Provenance.params. The order is a parameter of the computation that produced
# the cut, not a property of the numbers in it -- see ARCHITECTURE_DECISIONS
# §1.18. Named here so the two reading sites and the factory cannot drift.
PARAM_ORDER = "order"
# The whole order list a Residual was computed against (ADR §1.141 point 6).
PARAM_ORDERS = "orders_to_extract"

# An Overall Level's band as requested, in Provenance.params -- what a
# Parameter Set groups by, with f_stop=None meaning Full Bandwidth (§1.62
# point 11). The band actually integrated after clipping to a file's Nyquist
# goes to `metadata` instead: it differs between files at two sampling rates
# while the result is the same Parameter Set.
PARAM_F_START = "f_start"
PARAM_F_STOP = "f_stop"

# The settings a result was computed with that no SpectralProcessing field
# carries (an order's width, the rpm step, DC removal), as one nested mapping
# in Provenance.params. Kept out of a curve's compute_spec on purpose: the
# Parameter Set signature is built from that, and these only serve to tell two
# curves apart when one is adopted into a result set (#428).
PARAM_COMPUTATION = "computation"
META_EFFECTIVE_F_START = "effective_f_start"
META_EFFECTIVE_F_STOP = "effective_f_stop"

# Provenance.step of a block read from a file rather than computed. A result
# kind read this way is an Imported result (§1.134): its numbers were computed
# by another tool, so it has no SpectralProcessing to carry.
STEP_READ = "read"

# Separator for an axis slot that accepts more than one quantity (a tracked
# waterfall's second axis is rpm when tracked against speed and time otherwise).
_ALTERNATIVES = "|"


@dataclass(frozen=True)
class KindSpec:
    """
    What a block of one kind must look like.

    `axis_quantities` has one entry per axis, in order, each entry either a
    quantity name or several separated by "|". Its length therefore also fixes
    how many axes the kind has -- 1 for a curve, 2 for a map.

    `renderer` is the hook §1.7 (Epic 3) will fill in to replace the current
    "route by whichever Qt signal delivered the block" dispatch. Empty until
    then: the field exists so adding it later is not a schema change.

    `cache_exempt_params` names the computation parameters that must NOT count
    towards "was this already computed with the same settings" (§1.21). An
    order-cut result set saved with orders "1, 2, 4.5" satisfies a live request
    for order 2, so orders_to_extract is exempt and the individual order is
    matched per stored block instead. A spectrum has no such parameter, so the
    default is empty -- which is what keeps "a new kind is one row here plus one
    factory" true for the cache as well.

    `display_only_params` names parameters that change how a result is drawn but
    not what it contains -- a spectrogram's colour scale. The workflow authoring
    side strips them from a node's params, and `shape_signature` leaves them out
    of the cache identity, so both read this one register instead of two that
    drift (audit 02 / 7.5): before this, a live spectrogram request carried
    `color_scale` and never matched a batch-saved set.
    """
    axis_quantities: Tuple[str, ...]
    requires_processing: bool
    renderer: str = ""
    description: str = ""
    cache_exempt_params: Tuple[str, ...] = ()
    display_only_params: Tuple[str, ...] = ()


KINDS: Dict[str, KindSpec] = {
    KIND_TIME_RESPONSE: KindSpec(
        axis_quantities=("time",), requires_processing=False,
        description="Raw recorded waveform as it came off the acquisition.",
    ),
    KIND_SPECTRUM: KindSpec(
        axis_quantities=("frequency",), requires_processing=True,
        description="Averaged single-sided spectrum of one channel.",
        display_only_params=("spectrum_format", "amplitude_mode", "decibel_scale"),
    ),
    KIND_SPECTROGRAM: KindSpec(
        axis_quantities=("frequency", "rpm|time"), requires_processing=True,
        description="Tracked waterfall: a spectrum per rpm step or time slice.",
        display_only_params=("spectrum_format", "amplitude_mode", "color_scale"),
    ),
    KIND_ORDER_CUT: KindSpec(
        axis_quantities=("rpm",), requires_processing=True,
        description="Amplitude of one order against speed.",
        cache_exempt_params=("orders_to_extract",),
        display_only_params=("amplitude_mode",),
    ),
    KIND_OVERALL_LEVEL: KindSpec(
        axis_quantities=("rpm|time",), requires_processing=True,
        description="Energy of one fixed frequency band against speed or time.",
        display_only_params=("amplitude_mode",),
    ),
    # No cache_exempt_params: a Residual is a function of the whole order list
    # (ADR §1.141 point 6), so a set with other orders is another result.
    KIND_ORDER_RESIDUAL: KindSpec(
        axis_quantities=("rpm",), requires_processing=True,
        description="Energy of the Overall Level band outside the selected orders' bands.",
        display_only_params=("amplitude_mode",),
    ),
}


def spec_for(kind: str) -> KindSpec:
    """The KindSpec for `kind`, or ValueError naming what is registered."""
    try:
        return KINDS[kind]
    except KeyError:
        raise ValueError(
            f"Unknown block kind '{kind}'. Registered kinds: {', '.join(sorted(KINDS))}. "
            f"A new kind is one entry in core/block_kinds.KINDS plus a factory on NVHDataBlock."
        ) from None


def validate(block: Any) -> None:
    """
    Raises ValueError unless `block` is a coherent member of its own kind.

    Called from NVHDataBlock.__post_init__, so it runs on every block the app
    builds and on every dataclasses.replace of one -- there is no path that
    produces an unvalidated block. Duck-typed on purpose: block_kinds must not
    import data_block, because data_block imports this.
    """
    spec = spec_for(block.kind)

    if len(block.axes) != block.values.ndim:
        raise ValueError(
            f"Block '{block.name}': {len(block.axes)} axis/axes described but values "
            f"are {block.values.ndim}-dimensional. An axis per dimension, always."
        )

    if len(block.axes) != len(spec.axis_quantities):
        raise ValueError(
            f"Block '{block.name}' of kind '{block.kind}' needs "
            f"{len(spec.axis_quantities)} axis/axes ({', '.join(spec.axis_quantities)}), "
            f"got {len(block.axes)}."
        )

    for position, (axis, allowed) in enumerate(zip(block.axes, spec.axis_quantities)):
        options = allowed.split(_ALTERNATIVES)
        if axis.quantity not in options:
            raise ValueError(
                f"Block '{block.name}' of kind '{block.kind}': axis {position} is "
                f"'{axis.quantity}', expected {' or '.join(options)}."
            )
        if len(axis.values) != block.values.shape[position]:
            raise ValueError(
                f"Block '{block.name}': axis {position} ('{axis.quantity}') has "
                f"{len(axis.values)} points but values dimension {position} is "
                f"{block.values.shape[position]} long."
            )

    if spec.requires_processing and block.processing is None and block.provenance.step != STEP_READ:
        raise ValueError(
            f"Block '{block.name}' of kind '{block.kind}' is a processing result and "
            f"must carry the SpectralProcessing it was made with. Only a block read "
            f"from a file (an Imported result) may come without one."
        )
    if not spec.requires_processing and block.processing is not None:
        raise ValueError(
            f"Block '{block.name}' of kind '{block.kind}' is not a processing result, so "
            f"claiming a window and correction factors would be a lie about the data. "
            f"That is exactly what the flat block used to do."
        )


def resolve_clipped_f_stop(block: Any) -> Optional[Tuple[float, float]]:
    """
    (requested, effective) F max when an Overall Level's band was clipped to
    its file's Nyquist (§1.62 point 9), else None -- also for a block with no
    requested F max (Full Bandwidth) or of another kind. The one comparison
    behind the live dock's log line and the batch run's summary line.
    """
    params = block.provenance.params if block.provenance else {}
    requested = params.get(PARAM_F_STOP)
    effective = block.metadata.get(META_EFFECTIVE_F_STOP)
    if requested is None or effective is None or float(effective) == float(requested):
        return None
    return float(requested), float(effective)
