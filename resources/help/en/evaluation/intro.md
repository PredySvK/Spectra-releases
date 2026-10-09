# Evaluation

**Evaluation** turns the curves of one graph into numbers. Open the *Evaluation* tab of the bottom panel, click a graph, pick an Evaluation, and the table lists one **Single value** per curve (or several, for Top-N maxima): the number, where on the curve it sits, and which curve it came from. An Evaluation never creates a new curve and never changes the data.

![Filters dock and Evaluation table](filter_evaluation.en.png)

Each graph keeps its own Evaluation, its parameters and its columns; they are saved with the project. The table follows the graph in focus and recomputes when the graph's content or its [Trace filter](topic:filtering/intro) changes. The computation runs in the background; while the tab is hidden it is only marked out of date and recomputed when you open it.

## The four Evaluations

| Evaluation | Reads | Rows per curve | Page |
|---|---|---|---|
| **Max** | spectra, order cuts, Overall Level | exactly 1 (a dash if the curve has no valid sample) | [Max](topic:evaluation/max) |
| **Top-N maxima** | spectra, order cuts, Overall Level | 0 to N, tallest first | [Top-N maxima](topic:evaluation/topn_maxima) |
| **Typed orders** | one rpm-tracked spectrogram | one per order you type | [Typed orders](topic:evaluation/typed_orders) |
| **Dominant orders** | one rpm-tracked spectrogram | 0 to N, found automatically | [Dominant orders](topic:evaluation/dominant_orders) |

A time-domain graph, or a graph whose curves the chosen Evaluation does not read, shows the message *This dock has no curves Evaluation supports.* instead of a table. With no graph open the tab says *No graph is open.* A table that comes out empty says so (*No evaluation results for the current parameters.*, or the Typed / Dominant orders variant).

## Columns

The first eight columns are always there, in this order. Further columns come from **Columns&hellip;** (below).

| Column | What it holds |
|---|---|
| **Channel** | channel name and direction, e.g. *Acc1 Z* |
| **Measurement** | the file the curve was computed from |
| **Source** | the [result set](topic:results/intro)'s label, or *Live* for a curve computed on the spot |
| **Order / Band** | what the curve was computed for: *Order 4.79* for an [order cut](topic:order_tracking/orders), a band such as *10-Full Bandwidth* or *100-2000 Hz* for [Overall Level](topic:overall_level/band); empty for a [spectrum](topic:spectrum/intro). Typed orders and Dominant orders add the order width, e.g. *Order 4.79 (&plusmn;0.2)* |
| **Value (unit)** | the extracted number, four significant digits, with the unit in the header (e.g. *Value (g)*, or *Value (g Peak)* in Peak mode). When rows carry different units the header shows only *Value (RMS)* or *Value (Peak)* and each cell carries its own unit |
| **at X (unit)** | where on the curve's X axis the value sits: rpm, Hz, s or order, in the global [X axis unit](topic:units/intro). Unit in the header when all rows share one |
| **Edge** | *Yes* when the value sits on the first or last valid sample of its curve, meaning the real maximum may lie beyond the computed range. Empty otherwise |
| **Parameter Set** | *Parameter Set 1*, *2*, ... -- curves computed with the same settings share a number ([Result Pool](topic:results/intro)), so you can tell two [FFT sizes](topic:shared/fft_size) apart. Empty when the curve has none |

A curve with no valid sample (an order below the frequency resolution or above Nyquist) still gets a row: Value and at X show **&mdash;**. A dash is not a dropped curve.

## Toolbar

- **Evaluation:** the choice above. Its parameters appear next to it.
- **Amplitude (RMS / Peak):** ([Amplitude format](topic:shared/amplitude_format)) Peak = &radic;2 &times; RMS. A display switch; nothing is recomputed and the position does not move.
- **Format (Linear / Power / PSD):** how spectrum rows are shown; enabled only when the table holds spectra. Order cuts and Overall Level have no such choice.
- **Units:** follow the global unit settings ([Units](topic:units/intro)); the table updates when you change them.
- **Copy** or Ctrl+C copies the selected rows, or the whole table when nothing is selected, tab-separated with headers for Excel. The right-click menu offers the same.
- **Export CSV** writes the **whole** table (not just the selection) in the order currently shown, headers included. The cell texts are what you see on screen, so *Value* carries four significant digits.
- **Columns&hellip;** adds further columns in four groups: *Identity* (Channel, Direction, Channel type, File name, Data Pool label, Result set), *Raw metadata*, *Excel metadata* and *Calculated metadata* (Analysis type, Order, Parameter set). Only fields that are active in the [Metadata Editor](topic:import/metadata) are offered; a field you deactivate later stays selected but drops out of the table. The selection is kept per graph and saved with the project.
- **Respect Trace filter:** on by default, so the table covers only the curves the graph is showing. Off evaluates every curve the graph holds, including the ones the filter hides. Remembered per graph.
- **?** opens the page of the chosen Evaluation.

Click a column header to sort. Numbers sort numerically, orders and bands by their number, text alphabetically without regard to case. Empty cells and dashes stay at the bottom in both directions.

## Reading the numbers

The value is always computed in the channel's own unit from the energy per bin (see [Amplitude format](topic:shared/amplitude_format)); the Amplitude, Format and Units switches only re-express it. That is why the position never moves when you flip a switch, and why Top-N maxima and Dominant orders measure prominence in dB of the linear RMS amplitude: the pick does not depend on the display.
