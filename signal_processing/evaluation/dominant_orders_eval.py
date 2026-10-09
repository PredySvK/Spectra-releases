# =====================================================================
# FILE: signal_processing/evaluation/dominant_orders_eval.py
# =====================================================================
"""
Dominant orders (ADR §1.64 point 8, issue #142, CONTEXT.md Dominant order):
the N orders of one rpm-tracked spectrogram with the highest maximum
amplitude anywhere along their order line.

Two halves, deliberately separate:

- **Detection** (swappable -- a later detector C slots in here): every row
  of the spectrogram is resampled from Hz onto one common order grid
  (o = f*60/rpm), giving an order map. Its maximum over rpm is a "max
  energy vs. order" curve, on which the Local maximum rule of Top-N maxima
  (#140, `topn_eval.local_maxima_by_height`) picks candidates. Each
  candidate is then refined to the energy centroid (sum o*P / sum P) of the
  map summed over rpm around it, and rounded to hundredths.
- **Value** (fixed): the refined order goes through
  `typed_orders_eval.order_rows_from_spectrogram`, the exact path a Typed
  orders row takes. A Dominant order's amplitude and rpm therefore equal
  Typed orders -- and Order Tracking's Max -- on the displayed order by
  construction, never a bin height read off the map.

Why an order line is smeared, why a centroid, and why only some rows feed
the map are ADR §1.64 point 8 and its #142 outcome note.
"""

from dataclasses import dataclass
from typing import Callable, Iterator, List, Sequence, Tuple

import numpy as np

from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity, SingleValue
from signal_processing.dsp.steps.band_integration import measure_main_lobe_width_bins
from signal_processing.dsp.windows import generate_window
from signal_processing.evaluation.topn_eval import DEFAULT_MIN_PROMINENCE_DB, local_maxima_by_height
from signal_processing.evaluation.typed_orders_eval import (
    DEFAULT_ORDER_WIDTH, is_rpm_spectrogram, order_rows_from_spectrogram,
)

DEFAULT_N = 10
DEFAULT_ORDER_MIN = 0.5
DEFAULT_ORDER_MAX = 50.0
DEFAULT_MIN_ORDER_DISTANCE = 0.5
DEFAULT_ORDER_RESOLUTION = 0.01

# A refined order is rounded to this many decimals before its value is read,
# so the order the table shows is the order the value was computed at.
ORDER_DECIMALS = 2

# Grid cells (rows x orders) resampled per numpy batch -- bounds each
# scratch array to ~2.5 MB (64 rows of a default ~5000-point map) instead
# of letting it grow with rows x grid (issue #311). A grid wider than this
# goes one row per batch, so the scratch grows with the grid alone.
_BATCH_CELLS = 64 * 5000

OrderDetector = Callable[..., Sequence[float]]


@dataclass(frozen=True)
class OrderMap:
    """A spectrogram resampled onto a common order grid, reduced over rpm.
    `max_energy` finds candidates, `summed_energy` refines them; both are
    canonical bin energy (squared units), zero where a grid order sat above
    Nyquist or inside the window's main lobe around DC on every used row."""
    orders: np.ndarray
    max_energy: np.ndarray
    summed_energy: np.ndarray
    rows_used: int


def _order_grid(order_min: float, order_max: float, order_resolution: float) -> np.ndarray:
    if order_resolution <= 0.0 or order_max < order_min:
        return np.empty(0, dtype=np.float64)
    count = int(np.floor((order_max - order_min) / order_resolution + 1e-9)) + 1
    return order_min + np.arange(count, dtype=np.float64) * order_resolution


def build_order_map(
    block: NVHDataBlock,
    *,
    order_min: float,
    order_max: float,
    order_resolution: float,
    min_order_distance: float,
) -> OrderMap:
    """Order map of an rpm spectrogram, reduced over rpm."""
    orders = _order_grid(order_min, order_max, order_resolution)
    max_energy = np.zeros(orders.size, dtype=np.float64)
    summed_energy = np.zeros(orders.size, dtype=np.float64)
    rows_used = 0
    for batch_rpm, energy in order_map_rows(block, orders, min_order_distance):
        np.maximum(max_energy, energy.max(axis=0), out=max_energy)
        summed_energy += energy.sum(axis=0)
        rows_used += len(batch_rpm)
    return OrderMap(orders, max_energy, summed_energy, rows_used)


def order_map_rows(
    block: NVHDataBlock, orders: np.ndarray, min_order_distance: float,
) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    """The unreduced order map in batches: (rpm of each used row, canonical
    bin energy (rows x orders)). Only rows whose window main lobe spans no
    more than `min_order_distance` orders (lobe_hz * 60 / rpm) are used: a
    slower row smears one line across its neighbours, so it could neither
    separate two orders that far apart nor place one to hundredths."""
    if orders.size == 0:
        return
    frequencies = np.asarray(block.axes[0].values, dtype=np.float64)
    rpm_axis = np.asarray(block.axes[1].values, dtype=np.float64)
    # NVHDataBlock.spectrogram stores (frequency, rpm); one row per rpm step here.
    p_canon = np.asarray(block.values, dtype=np.float64).T

    df = float(frequencies[1] - frequencies[0])
    nyquist_hz = float(frequencies[-1])
    window, _acf, _ecf, _enbw = generate_window(block.processing.window_type, block.processing.fft_size)
    main_lobe_hz = measure_main_lobe_width_bins(window) * df

    positive_rpm = np.where(rpm_axis > 0.0, rpm_axis, np.nan)
    lobe_orders = main_lobe_hz * 60.0 / positive_rpm
    used = lobe_orders <= min_order_distance  # NaN (rpm <= 0) compares False

    rows_rpm = rpm_axis[used]
    rows_energy = p_canon[used]
    last_bin = len(frequencies) - 2
    batch_rows = max(1, _BATCH_CELLS // orders.size)
    for start in range(0, len(rows_rpm), batch_rows):
        batch_rpm = rows_rpm[start:start + batch_rows]
        batch_energy = rows_energy[start:start + batch_rows]
        query_hz = orders[np.newaxis, :] * batch_rpm[:, np.newaxis] / 60.0
        position = (query_hz - frequencies[0]) / df
        lower = np.clip(np.floor(position).astype(np.int64), 0, last_bin)
        fraction = np.clip(position - lower, 0.0, 1.0)
        energy = (np.take_along_axis(batch_energy, lower, axis=1) * (1.0 - fraction)
                  + np.take_along_axis(batch_energy, lower + 1, axis=1) * fraction)
        yield batch_rpm, np.where((query_hz > nyquist_hz) | (query_hz < main_lobe_hz), 0.0, energy)


def _centroid_order(order_map: OrderMap, index: int, half_width: float) -> float:
    """Energy centroid of the summed map around one candidate. Climbs to the
    summed map's own top within `half_width`, spans outward only while the
    map keeps falling (a neighbouring line past the valley never pulls the
    centroid) and weighs only the energy above the higher of the two valley
    floors (a sloping pedestal would otherwise drag it toward the window's
    middle)."""
    orders = order_map.orders
    energy = order_map.summed_energy
    size = len(orders)
    reach = half_width + 1e-9

    top = index
    while True:
        best = top
        for step in (-1, 1):
            neighbour = top + step
            if (0 <= neighbour < size and abs(orders[neighbour] - orders[index]) <= reach
                    and energy[neighbour] > energy[best]):
                best = neighbour
        if best == top:
            break
        top = best

    left = top
    while left > 0 and orders[top] - orders[left - 1] <= reach and energy[left - 1] <= energy[left]:
        left -= 1
    right = top
    while right < size - 1 and orders[right + 1] - orders[top] <= reach and energy[right + 1] <= energy[right]:
        right += 1

    floor = max(energy[left], energy[right])
    weights = np.clip(energy[left:right + 1] - floor, 0.0, None)
    total = float(weights.sum())
    if total <= 0.0:
        return float(orders[top])
    return float(np.sum(orders[left:right + 1] * weights) / total)


def detect_from_order_map(
    block: NVHDataBlock,
    *,
    n: int,
    order_min: float,
    order_max: float,
    min_order_distance: float,
    min_prominence_db: float,
    order_resolution: float,
) -> Tuple[float, ...]:
    """The default detector: order map -> Local maxima -> centroid. Returns
    up to `n` refined orders, rounded to ORDER_DECIMALS, strongest map
    maximum first. Two candidates refining onto the same line collapse into
    the first (taller) one."""
    order_map = build_order_map(
        block, order_min=order_min, order_max=order_max,
        order_resolution=order_resolution, min_order_distance=min_order_distance,
    )
    if order_map.orders.size == 0 or order_map.rows_used == 0:
        return ()

    # 10*log10(energy) is amplitude dB: the same scale Top-N maxima's
    # prominence is defined on (topn_eval._amplitude_db).
    with np.errstate(divide="ignore"):
        db = 10.0 * np.log10(order_map.max_energy)
    db = np.where(np.isfinite(db), db, -np.inf)

    detected: List[float] = []
    for index in local_maxima_by_height(db, order_map.orders, min_order_distance, min_prominence_db):
        order = round(_centroid_order(order_map, index, min_order_distance / 2.0), ORDER_DECIMALS)
        if all(abs(order - kept) >= min_order_distance - 1e-9 for kept in detected):
            detected.append(order)
            if len(detected) >= n:
                break
    return tuple(detected)


def extract_dominant_orders(
    block: NVHDataBlock,
    identity: CurveIdentity,
    n: int = DEFAULT_N,
    order_min: float = DEFAULT_ORDER_MIN,
    order_max: float = DEFAULT_ORDER_MAX,
    min_order_distance: float = DEFAULT_MIN_ORDER_DISTANCE,
    min_prominence_db: float = DEFAULT_MIN_PROMINENCE_DB,
    order_width: float = DEFAULT_ORDER_WIDTH,
    order_resolution: float = DEFAULT_ORDER_RESOLUTION,
    detector: OrderDetector = detect_from_order_map,
) -> Tuple[SingleValue, ...]:
    """Extraction on one spectrogram (ADR §1.64 point 2): zero to `n` rows,
    ranked by amplitude, never padded. A time-tracked spectrogram or any
    other block kind gives no rows."""
    if not is_rpm_spectrogram(block):
        return ()
    orders = detector(
        block, n=int(n), order_min=float(order_min), order_max=float(order_max),
        min_order_distance=float(min_order_distance), min_prominence_db=float(min_prominence_db),
        order_resolution=float(order_resolution),
    )
    if not orders:
        return ()
    rows = order_rows_from_spectrogram(block, identity, orders, order_width, f"{{:.{ORDER_DECIMALS}f}}")
    return tuple(sorted(rows, key=_amplitude_rank))


def _amplitude_rank(row: SingleValue) -> Tuple[bool, float]:
    # Canonical Linear RMS: the ranking must not depend on the table's
    # display switches. Empty rows ("--") go last.
    if row.is_empty:
        return True, 0.0
    return False, -float(row.block.values[row.sample_index])
