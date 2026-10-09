# Graph Defaults

**Graph Defaults** controls how 1D curves in [graphs](topic:graphs/intro) are drawn. Downsampling and drawing only the visible part of a curve can make long records smoother to pan and zoom. These choices change the picture only; see [Raw data](topic:raw_data/intro) for how the full signal is used in analysis.

## Choose how curves are drawn

On the **Settings** tab, click **Graph Defaults**. The dialog is titled **Default Graph Throughput Settings**.

| Setting | What it does |
|---|---|
| **Enable Downsampling** | Reduces the number of points drawn. Clear it to turn off downsampling for the curves to which the setting is applied. The **Automatic Optimization** and **Manual Decimation Factor** controls are disabled while this is clear. |
| **Automatic Optimization (Matches Monitor Width)** | Chooses a downsampling factor from the visible X range and plot width. It adjusts as you zoom or resize; the current PyQtGraph renderer aims for about five samples per screen pixel. |
| **Manual Decimation Factor:** | Sets the grouping factor from **2** to **10,000**. A larger factor draws fewer groups of samples. The renderer keeps each group's high and low points to show peaks. |
| **Render Screen Only Data (Evict Hidden Points)** | Clips curve drawing to the visible X range, which can reduce work while viewing only part of a long record. It clips only when the X axis has a fixed view range; with X auto-range on, all X data remains in the drawing range. The underlying curve data is kept. |

**Defaults:** Enable Downsampling on, Automatic Optimization selected, Manual Decimation Factor 10, and Render Screen Only Data on. The manual factor is used only when **Manual Decimation Factor** is selected.

## Apply and keep your choices

Click **Save & Apply** to store these preferences and apply them to curve items already open in the current workspace. The update covers every open curve graph in that workspace, including curves on a secondary Y axis. It does not reach into another window's workspace. **Cancel** closes the dialog without applying or saving the changed performance choices.

The choices are saved in application settings, so they return after restarting Spectra and are shared across projects. They are not stored in the [project file](topic:general/projects). The dialog's size and position are remembered separately.

## What happens to graphs opened later

There is an important limit to the word *Defaults*: automatic downsampling and screen-only clipping are switched on only for curves with **more than 20,000 X points**, where they pay off; shorter curves are drawn in full. Your choices here can only switch them off: with **Enable Downsampling** or **Render Screen Only Data** off, even a long curve keeps that option off, including after a resize or redraw. For the long-record behavior, see [Long records](topic:raw_data/intro#long-records).

These rules affect rendering; they do not remove samples from the signal or change an analysis result.
