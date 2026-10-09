# =====================================================================
# FILE: signal_processing/evaluation/typed_orders_eval.py
# =====================================================================
"""
Typed orders (ADR §1.64 point 8, issue #141): the value of each user-typed
order on an rpm-tracked spectrogram, read straight off the spectrogram's own
canonical matrix through `order_cut.order_cut_from_spectrogram` rather than a
fresh cut from raw samples (§1.64 point 8's "why no raw data is needed") --
one row per requested order, dash ("--" in the table) when it falls entirely
above the file's Nyquist frequency or below the FFT's resolution, exactly
like Max (never a dropped row).

Each row is built by handing a synthetic order-cut block (the same shape
`result_blocks.build_order_cut_blocks` produces) to `extract_max` --
reusing Max's own edge/empty-curve handling instead of a second copy of it,
and giving the Evaluation table's Amplitude/Format/Units switches the same
NVHDataBlock.to_display_values path every other Evaluation row uses (ADR
§1.60/§1.61). The invariant this pins: the row's value and rpm equal
Order Tracking's Max over the same file, FFT, window, step and order width
(tests/test_evaluation_typed_orders.py) -- a spectrogram and an order cut
recipe already agree on canonical power for the same reason (ADR §1.58
point 6/8), so `order_cut_from_spectrogram` is the only place that invariant
could quietly slip.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence, Tuple

import numpy as np

from core.block_kinds import KIND_SPECTROGRAM
from core.data_block import NVHDataBlock, Provenance, SpectralProcessing
from core.evaluation import CurveIdentity, SingleValue
from core.units import format_order_unit, strip_amplitude_suffix
from signal_processing.dsp.order_cut import order_cut_from_spectrogram
from signal_processing.evaluation.max_eval import extract_max

# Same default as Order Tracking's own ribbon (core.dsp_configs.OrderTrackingConfig)
# -- a starting point for the widget, not read from it (ADR §1.64 point 8: the
# evaluation must be reproducible from its own parameters, not the ribbon's
# current, possibly-later-changed state).
DEFAULT_ORDER_WIDTH = 0.2


def is_rpm_spectrogram(block: NVHDataBlock) -> bool:
    """Only a spectrogram tracked against rpm has orders to read (ADR §1.64
    point 8) -- shared by every Evaluation that reads one."""
    return block.kind == KIND_SPECTROGRAM and block.axes[1].quantity == "rpm"


def extract_typed_orders(
    block: NVHDataBlock,
    identity: CurveIdentity,
    orders: Sequence[float] = (),
    order_width: float = DEFAULT_ORDER_WIDTH,
) -> Tuple[SingleValue, ...]:
    """Extraction on one curve (ADR §1.64 point 2). `block` must be a
    KIND_SPECTROGRAM tracked against rpm -- a time-tracked spectrogram (or
    any other block kind a dock might also be showing, point 3) gives no
    rows here, not an error; the panel shows its usual "no curves supported"
    message rather than a blank table for that case. An empty `orders` list
    (nothing typed yet) gives no rows either."""
    if not orders or not is_rpm_spectrogram(block):
        return ()
    return order_rows_from_spectrogram(block, identity, orders, order_width, "{:g}")


def order_rows_from_spectrogram(
    block: NVHDataBlock,
    identity: CurveIdentity,
    orders: Sequence[float],
    order_width: float,
    order_format: str,
) -> Tuple[SingleValue, ...]:
    """The one value path from an rpm spectrogram and a list of orders to
    table rows, one per order in the given sequence. Typed orders and
    Dominant orders (#142) both end here, which is what makes a Dominant
    order's value equal the Typed orders row for the same order by
    construction. `order_format` only shapes the Order / Band label."""
    z_axis = block.axes[1]
    frequencies = np.asarray(block.axes[0].values, dtype=np.float64)
    rpm_axis = np.asarray(z_axis.values, dtype=np.float64)
    # NVHDataBlock.spectrogram stores (frequency, z); the moving-band
    # integrator wants one row per rpm step.
    p_canon_matrix = np.asarray(block.values, dtype=np.float64).T
    fft_size = block.processing.fft_size
    window_type = block.processing.window_type

    order_cuts = order_cut_from_spectrogram(
        p_canon_matrix, frequencies, rpm_axis, list(orders), float(order_width),
        fft_size=fft_size, window_type=window_type,
    )

    value_unit = format_order_unit(strip_amplitude_suffix(block.value_unit), "linear", "rms")
    processing = SpectralProcessing(
        window_type=window_type, amplitude_mode="rms", spectrum_format="linear", fft_size=fft_size,
    )

    rows = []
    for order in orders:
        amplitudes = order_cuts[float(order)]
        cut_block = NVHDataBlock.order_cut(
            name=f"Order {order:g} [{block.name}]",
            values=amplitudes, rpm=rpm_axis, order=float(order),
            value_unit=value_unit, processing=processing,
            provenance=Provenance(step="evaluation_typed_orders", parents=(block.name,)),
            **block.inherited_context(),
        )
        # Order width has no home of its own on the table (ADR "Order width
        # is visible in the table"), so it rides in the same cell as the order.
        row_identity = replace(
            identity, order_or_band=f"Order {order_format.format(order)} (±{float(order_width):g})",
        )
        rows.append(extract_max(cut_block, row_identity))
    return tuple(rows)
