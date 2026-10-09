# Cursor

The **Cursor** reads a value off a graph exactly. With it on, move the mouse over a [curve graph](topic:graphs/intro) or [spectrogram](topic:spectrogram/intro): a small box next to the mouse shows the point under it -- no guessing from the grid.

## Switching it on

- Open the **Tools** tab ([Tools](topic:tools/intro)) and click the **Cursor** box in the **Cursors** group, or
- press **C** while a graph has focus (click the graph first).

The switch is one setting for **every** open graph. Pressing **C** again, or clicking the box, turns it off. The Cursor is **on by default**; the box is lit blue while it is on and grey while it is off, and Cursor, Highlight and Pin are remembered across restarts.

The box carries three small round buttons in a row along its bottom: **Cursor Settings** (gear, left), **Highlight** (flashlight, middle) and **Pin** (right). A button is filled teal while it is on; hover it for its tooltip. Pin is available only while the Cursor is on.

![The Cursor box and its buttons on the Tools tab, and the Cursor Box over a spectrum](cursor.en.png)

## What the box shows

On curve graphs, the Cursor snaps to the nearest **real sample** of the nearest visible curve -- a measured value, never an interpolation. "Nearest" is judged on the screen, in pixels, so it feels the same however different the X and Y scales are. Only a curve within about **10 pixels** of the mouse is picked; over empty space there is no box.

| Line | Meaning |
|---|---|
| **Curve** | the legend name of the curve (curve graphs) |
| **X** | the sample's X (or time / speed under the mouse on a spectrogram), in the unit of the axis |
| **Y** | the sample's value with its display unit (or frequency on a spectrogram). On a graph with two Y axes ([two units on one graph](topic:units/intro)) a curve on the right axis reads **Y (Secondary)** |
| **Z** | the amplitude under the mouse on a spectrogram, in the displayed unit and colour scale |
| **Amplitude** | **RMS** or **Peak** ([Amplitude format](topic:shared/amplitude_format)), where the curve has one |

Numbers use 4 significant digits; very small (below 0.001) or large (from 100 000) values switch to scientific notation, and dB values show one decimal.

Only curves you currently see are considered: curves hidden by the [Trace filter](topic:filtering/intro) or by the X domain of the graph are never picked, and neither are the [Band RMS](topic:tools/band_rms) Cursors.

### Spectrograms

Hovering a spectrogram shows a crosshair and the Cursor Box with X, Y and Z exactly under the mouse (no snap).
- **X** is time or speed/RPM in the displayed axis unit.
- **Y** is frequency in the displayed axis unit.
- **Z** is the pixel value under the mouse, displayed in the chosen colour scale and unit (linear engineering units or dB).

The crosshair lines track the mouse continuously and disappear when the mouse leaves the spectrogram or a mouse button is pressed.

## Behaviour

- The box floats to the lower right of the mouse and flips to the other side near a graph edge, so it is never cut off.
- It disappears while a mouse button is held (panning, zooming, dragging a [Band RMS](topic:tools/band_rms) Cursor or a curve to another graph), when the mouse leaves the graph, and when no curve is in reach (or outside the spectrogram).

## Highlight

**Highlight** is its own switch in the **Cursors** group, independent of the Cursor. While it is on, the curve under the mouse (the same nearest curve rule as the Cursor, within about 10 pixels) is drawn thicker and every other curve is dimmed to about 25 %. Turn it on with the **Highlight** button or press **H** while a graph has focus.

All curves return to normal when the mouse leaves the graph, moves away from every curve, a mouse button is pressed, the graph is redrawn, or Highlight is switched off.

## Pin

**Pin** (button in the **Cursors** group, or **P** while a graph has focus) freezes the Cursor Box where it is: it stops following the mouse, but its content keeps updating from the hover. Drag the box itself to move it; dragging anywhere else on the graph still pans or drags a curve to another graph. Unpinning hides the box until the mouse moves again.

## Cursor Settings

Click **Cursor Settings…** in the **Cursors** group to choose what the box shows. Tick a field to show it; its **Priority** (arrows or a typed number) is its line, 1 on top. The **Values** section has X, Y, Z, Curve name and RMS / Peak; the metadata sections offer the fields marked **Use as Filter** in [Metadata and Filter Settings](topic:import/metadata), with the curve's own values (for example Direction, File name or an Excel field).

One list serves curve graphs and spectrograms; a field that does not apply (Z on a curve graph, metadata on a spectrogram) is skipped. The choice is saved for **every project** and survives a restart. A metadata field the open project does not have is simply left out of the box.

In the bottom-left corner, **Other curves opacity (Highlight)** sets how visible the curves other than the highlighted one stay while Highlight is on: 0 % is invisible, 100 % is no dimming (default 25 %). Drag the slider or type the value; it is saved like the field list.
