# Graph Rendering

**Graph Rendering** controls how 1D curves in [graphs](topic:graphs/intro) are drawn. Downsampling and drawing only the visible part of a curve can make long records smoother to pan and zoom. These choices change the picture only; see [Raw data](topic:raw_data/intro) for how the full signal is used in analysis.

## Choose how curves are drawn

Open the **Settings** window from the gear in the title strip and select **Graphic › Graph Rendering**.

| Setting | What it does |
|---|---|
| **Enable downsampling** | Reduces the number of points drawn. Clear it to turn off downsampling for the curves to which the setting is applied. The **Automatic (matches monitor width)** and **Manual factor** controls are disabled while this is clear. |
| **Automatic (matches monitor width)** | Chooses a downsampling factor from the visible X range and plot width. It adjusts as you zoom or resize; the current PyQtGraph renderer aims for about five samples per screen pixel. |
| **Manual downsampling factor** | Sets the grouping factor from **2** to **10,000**. A larger factor draws fewer groups of samples. The renderer keeps each group's high and low points to show peaks. |
| **Render screen only** | Clips curve drawing to the visible X range, which can reduce work while viewing only part of a long record. It clips only when the X axis has a fixed view range; with X auto-range on, all X data remains in the drawing range. The underlying curve data is kept. |

**Defaults:** Enable downsampling on, Automatic (matches monitor width) selected, Manual factor 10, and Render screen only on. The manual factor is used only when **Manual factor** is selected.

**Other curves opacity** sets how visible the curves other than the highlighted one stay while [Highlight](topic:tools/cursor) is on: 0 % hides them, 100 % does not dim them (default 25 %). It is the same value as **Other curves opacity (Highlight)** in the Cursor settings dialog; changing it in either place updates the other.

## Apply and keep your choices

Click **Apply** to store these preferences and apply them to curve items already open in the current workspace. The update covers every open curve graph in that workspace, including curves on a secondary Y axis. It does not reach into another window's workspace. **Revert** discards unapplied edits; **Close** asks what to do if edits remain.

The choices are saved in application settings, so they return after restarting Spectra and are shared across projects. They are not stored in the [project file](topic:general/projects). The Settings window's size, position and last page are remembered separately.

## What happens to graphs opened later

There is an important limit to the word *Defaults*: automatic downsampling and screen-only clipping are switched on only for curves with **more than 20,000 X points**, where they pay off; shorter curves are drawn in full. Your choices here can only switch them off: with **Enable downsampling** or **Render screen only** off, even a long curve keeps that option off, including after a resize or redraw. For the long-record behavior, see [Long records](topic:raw_data/intro#long-records).

These rules affect rendering; they do not remove samples from the signal or change an analysis result.
