# Legend Settings

A curve's **Curve name** is the line that names it: in the graph's legend, as **Curve** in the [Cursor Box and the Track table](topic:tools/cursor), and in the [Band RMS](topic:tools/band_rms) readout. Out of the box it reads `[file] channel Result name [unit]`, for example `[run.unv] B1 Out:+Z Order 2 [g RMS]`.

## Open the window

Right-click a graph and choose **Legend Settings…**, or move the mouse over the legend and click the small gear that appears at its top-right corner. The gear is shown only while the mouse is over the legend, so it is never in an exported image; it follows the legend if you move it. The window opens over that graph and changes only that graph. A spectrogram has no legend, so it does not offer the item.

## Choose the parts

Each row is one part of the Curve name. Tick a row to use it; its **Priority** (arrows or a typed number) is its place in the name, 1 first.

The window offers every field [Configure Filters](topic:filtering/intro) offers, in the same sections, plus two rows of its own:

- **Identity:** File name, Channel, Direction, Channel type, Data Pool label, Result set, and **Unit** (the curve's unit as on the axis, for example `g RMS` or `dB`).
- **Raw metadata** and **Excel metadata:** every field with Active Status on in Metadata and Filter Settings.
- **Calculated:** Analysis type, Order, Parameter set, and **Result name**: `Order 2`, `OAL`, `OAL 10–500 Hz`, `Residual`; empty for a plain spectrum or time signal.

A metadata field shows its value alone, without the field's name, for example `Parameter Set 2` or `Front`. After you edit a measurement's metadata, the legend shows the new value the next time the graph is redrawn.

Parts are joined by a space in Priority order. File name and Unit stay in square brackets, as in the default; a part the curve has no value for is left out. A curve on the right Y axis keeps its `▸ right axis` note after the name. The name follows a unit or display change by itself.

## Auto apply, Restore Defaults

With **Auto apply** on, the graph shows each change as you make it; **Cancel** puts the graph back the way it was. Auto apply's on/off and the window's size and position are remembered. **Restore Defaults** puts both columns back to File name, Channel, Result name and Unit, in that order. **OK** keeps the choice for this graph and saves it with the project.

## Default for new graphs

The **Default** column works as in [Configure Filters](topic:filtering/intro): tick it on a ticked row to start every new graph with that part, in the Priority order. Unticking a row clears its Default. **OK** keeps the Default for every project; a graph saved without its own legend takes the Default too.
