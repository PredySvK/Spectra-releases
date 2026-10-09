## 📊 Evaluation: Dominant orders

<b>Dominant orders</b> finds, on one <b>rpm-tracked spectrogram</b>, the N orders with the highest maximum amplitude anywhere along their order line -- without you typing them in. Each row is one order, shown to hundredths (e.g. 4.79), with its amplitude and the rpm where that amplitude sits. Compare with [Top-N maxima](topic:evaluation/topn_maxima) and [Typed orders](topic:evaluation/typed_orders).

![](dominant_orders_order_map.png)

<i>Top: the order map of a synthetic run-up -- order 4.79, its harmonics 9.58 and 14.37, and a resonance fixed at 1800 Hz. Bottom: the max amplitude vs. order curve. Red markers: the Dominant orders found with N = 3. The faint diagonal trail in the map is the resonance -- with the default N = 10 some of its spots would take the remaining rows (see Limits).</i>

### Step by step

1. <b>Order map:</b> every spectrogram row (one rpm step) is resampled from Hz onto one common order grid, o = f&middot;60/rpm. A line that follows the shaft speed now sits at the same place in every row.
1. <b>Max over rpm:</b> for every order on the grid, the highest amplitude any row has there. The result is one curve: max amplitude vs. order.
1. <b>Candidates:</b> the Local maxima of that curve, by exactly the same rule as Top-N maxima -- min distance (here in orders) and min prominence in dB -- tallest first.
1. <b>Refinement:</b> each candidate moves to the energy centroid &Sigma;o&middot;P / &Sigma;P of the map summed over all rows, taken over its own hump only (up to the valley on each side, at most half the min distance away) and counting only the energy above the higher of the two valley floors, so a sloping background cannot drag it sideways; then it is rounded to hundredths.
1. <b>Value and rpm:</b> the order cut at that rounded order, read off the same spectrogram -- exactly what <b>Typed orders</b> gives for that order. Up to N rows, ranked by this amplitude.

### Why an order line is smeared

- <b>Bin width in orders:</b> at shaft speed rpm one FFT bin &Delta;f covers &Delta;o = &Delta;f&middot;60/rpm orders. At 51.2 kHz and FFT 4096 that is 0.25 orders at 3 000 rpm, but 0.025 at 30 000 rpm.
- <b>Window main hump:</b> the window spreads even a pure sine signal over several bins (Hann about 4).
- <b>Drift:</b> the speed changes during one frame, and the order itself can drift physically -- belt slip can make 4.79 read 4.77 at low load and 4.81 at high load.

So no single row can place an order to hundredths; the <b>centroid</b> combines many rows into one number. Rows too slow to separate two orders the min distance apart (window main hump wider than the min distance, in orders) are left out of the map entirely -- they would only blur it.

### Why the value equals the order cut's Max

A point on the map is one bin's energy on a smeared hump -- smaller than what an order cut integrates over the whole order band. Showing it would give two different numbers for the same thing. The value therefore comes from the order cut: equal to <b>[Typed orders](topic:evaluation/typed_orders)</b> on the displayed order, and to [Order Tracking](topic:order_tracking/intro)'s <b>Max</b> with the same [FFT](topic:shared/fft_size), [window](topic:shared/windows), step and order width. Type 4.79 into Typed orders and you get the same amplitude and rpm.

### Parameters

- <b>Orders (range):</b> lowest and highest order searched. Default 0.5 &ndash; 50.
- <b>N:</b> how many Dominant orders at most. Default 10. Fewer candidates give fewer rows -- never padded.
- <b>Min distance:</b> two Dominant orders stand at least this many orders apart, so the neighbours of one smeared line (4.78 / 4.79 / 4.80) are one row, not three. It also decides which rows are sharp enough to take part (see above). Default 0.5.
- <b>Min prominence:</b> how far a candidate must stand above the valley toward its higher neighbour on the max amplitude vs. order curve, in amplitude dB -- the Top-N maxima rule. Default 3 dB.
- <b>Order width:</b> the order band &Delta;O the value is integrated over, same meaning and default (0.2) as Typed orders and Order Tracking. The Evaluation's own parameter, not read from the ribbon.
- <b>Grid:</b> spacing of the common order grid. Default 0.01. Coarser is faster; the centroid still refines between grid points.

### Limits

- <b>Resonance at a fixed frequency:</b> energy that stays at one frequency f<sub>r</sub> while the speed changes lands on a different order in every row (f<sub>r</sub>&middot;60/rpm). On the map it is a broad hump or a trail of spots, not a line -- and it can take a row in the table. A detector that tells the two apart is deliberately not built yet.
- <b>Spectrogram against time:</b> has no orders -- no rows, the card shows its usual message.
- <b>Amplitude, Units, Sorting, Copy/Export, Columns&hellip;:</b> same as [Max](topic:evaluation/max). Format stays disabled -- a row is a Linear amplitude, like [Typed orders](topic:evaluation/typed_orders).
