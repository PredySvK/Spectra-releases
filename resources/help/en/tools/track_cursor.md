# Track cursor

The **Track cursor** reads **every curve of a graph at one X**. It draws a vertical line across a [curve graph](topic:graphs/intro) and a **Track table** next to it with each curve's value at the line -- useful when you compare many curves at the same frequency, order or speed. For one exact point on one curve use the [Cursor](topic:tools/cursor).

## Switching it on

- Open the **Tools** tab ([Tools](topic:tools/intro)) and click the **Track** box in the **Cursors** group, or
- press **T** while a graph has focus (click the graph first).

The switch is one setting for **every** open graph. Pressing **T** again, or clicking the box, turns it off. The Track cursor is **off by default**; the box is lit while it is on. It works on curve graphs only: a spectrogram has no line (**T** still flips the switch there, nothing is drawn).

The box carries three small round buttons in a row along its bottom: **Track cursor Settings** (gear, left), **Highlight** (flashlight, middle) and **Pin** (right). A button is filled while it is on; hover it for its tooltip. Highlight and Pin are available only while the Track cursor is on, and both are remembered across restarts.

![The Track box and its buttons on the Tools tab, and the line with the Track table over three spectra](track_cursor.en.png)

## The line and the Track table

The line first appears in the middle of the graph and stays on the graph while you zoom, pan or add curves. If the last curve is removed it forgets its place and comes back in the middle with the next one. It follows the graph's X axis, also a logarithmic one. A [Trace filter](topic:filtering/intro) that hides every curve hides the line too, and only the curves you currently see are in the table.

The **Track table** floats at the top right of the graph. Its first line is X at the line; below it are the curves, each with the columns you chose in Track cursor Settings (default **Channel** and **Y**).

- Rows are sorted from the highest Y. A curve with no value at the line (the line is outside its X range, or the value is missing) shows "—" and goes last.
- Curves on the right Y axis ([two units on one graph](topic:units/intro)) are their own group under a thin rule, each group sorted from the highest value.
- A cell longer than 32 characters ends in "…". Rows that do not fit the graph's height give way to **… and N more**, columns that do not fit its width to **+N columns** at the end of the header, so the table always stays inside the graph, also after the window is resized.
- Drag the table to move it; it stays where you put it until the Track cursor is switched off. Dragging it does not auto-range the graph.

Numbers follow the Display prefix and decimals set in Settings → Units, as in the Cursor Box; X thousands are separated (15 466 RPM).

## Pin

**Pin** (button in the **Cursors** group) decides how the line moves. It is **on** by default.

- **Pinned:** the line stays where it is. Drag the line (it thickens under the mouse) to move it; dragging anywhere else on the graph still pans.
- **Unpinned:** the line follows the mouse along X while the mouse is over the graph, and stays at the last place when the mouse leaves. Dragging the table does not move the line.

## Highlight

While the Track cursor's **Highlight** is on, every curve the line crosses gets a solid dot in the curve's own colour at that point, also curves the table folds into "… and N more". At the same time every curve is dimmed by **Other curves opacity**, also a curve the line does not cross; at 0 % the curves disappear and only the dots remain. The dots are never dimmed and the legend stays as it is. Highlight starts off.

With the Cursor's [Highlight](topic:tools/cursor#highlight) on too, the curve under the mouse is drawn thicker in its full colour on top of the dimmed ones; away from every curve, only the Track cursor's look applies. Switching either Highlight off gives the curves back their own look.

## Track cursor Settings

The gear on the **Track** box opens the same window as [Cursor Settings](topic:tools/cursor#cursor-settings), for the Track table's columns. Tick a field to show it as a column; its **Priority** (arrows or a typed number) is its place, 1 on the left. The **Values** section has Curve name, Y and RMS / Peak (no X and no Z: X is the first line of the table); the metadata sections offer the fields with **Active Status** ticked in [Metadata and Filter Settings](topic:import/metadata). A curve without a field shows "—", and a field no curve has gets no column.

The choice is the Track table's own: it does not change the Cursor Box, and it is saved for **every project** and survives a restart. **OK** redraws every open Track table at once.

- **Other curves opacity** (bottom left) is the same setting as in Cursor Settings: how visible the curves stay while a Highlight is on (default 25 %).
- **Table background opacity** (next to it) goes from 0 % (invisible) to 100 % (solid), default 90 %.
- **Auto apply** shows your changes in the graphs as you make them; **Cancel** takes them back.
- **Restore Defaults** puts the whole window back to its defaults: Channel and Y, and both sliders. Nothing is saved until **OK**.
