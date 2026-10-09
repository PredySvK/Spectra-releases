# Step-by-step workflow

The same eight steps work for every kind of measurement.

1. **[Project](topic:general/projects).** On the *Project* tab press **New** for an empty project (or **Open** for an existing one).
2. **[Add data](topic:import/intro).** Press **Add Data Directory** and pick the folder with your measurements. They appear in the *Data Pool* tab of the Explorer, grouped by test setup and measurement.
3. **[Look at the raw signal](topic:raw_data/intro).** While the *Project* tab is active, double-click a channel in the Data Pool. It opens as a time signal in a new workspace tab. Check that it looks sane before analysing it.
4. **Compute.** Switch to an analysis tab ([Overall Level](topic:overall_level/intro), [Order Tracking](topic:order_tracking/intro), [Spectrogram 2D](topic:spectrogram/intro) or [Spectrum 1D](topic:spectrum/intro)), set the [FFT size](topic:shared/fft_size) and [window](topic:shared/windows) in the ribbon, then double-click a channel. Several selected channels open as one comparison graph. After changing a setting press **Refresh**. **[Compute Batch](topic:batch/intro)** does the same for a whole folder and keeps the result in the [Result Pool](topic:results/intro).
5. **[Filter](topic:filtering/intro).** In the *Filters* dock untick the values you do not want to see (for example one channel). The graph hides those curves. Tick **Filter Data Pool** to narrow the Data Pool tree the same way; **Show all** switches every filter off without forgetting your choice.
6. **[Extract maxima](topic:evaluation/intro).** Open the *Evaluation* tab in the *Output* dock at the bottom. Pick **Max** for the highest value of each curve, or **Top-N maxima**, **Typed orders**, **Dominant orders**. The table lists every value with the position on the X axis where it sits.
7. **Export.** Press **Export CSV** in the [Evaluation](topic:evaluation/intro) tab, or select rows and press Ctrl+C to paste them into a spreadsheet.
8. **[Save](topic:general/projects).** On the *Project* tab press **Save**. Open graphs, filters and settings come back when you open the project again.

![Where to click in each of the eight steps](workflow_steps.en.png)
