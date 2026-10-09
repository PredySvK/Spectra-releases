# Benchmark

A Benchmark times how long Spectra takes to read measurements, calculate analyses and, in the Full variant, draw them on screen. It records the machine and breaks each run down into steps so you can compare machines or app versions and find where time is spent. A Benchmark measures speed; it does not check whether an analysis is correct.

## Choose a variant

Open the **Settings** tab and choose **Run Benchmark…**. The dialog starts with **Full** selected.

| Variant | What it measures |
|---|---|
| **Full** | Opens the real application window, enters each analysis through its ribbon tab, computes the result and waits for the screen to finish painting. Use this to include the cost of drawing. A multi-channel Spectrogram or Overall Level case is skipped because those tabs do not open a comparison graph for several channels. |
| **Headless** | Reads the file and runs the analysis directly, without opening Qt or drawing a graph. Use this to compare computation without screen rendering. It can compute multi-channel cases for all four analyses. |

Both variants use the same plan and produce a Benchmark report. Full runs in a separate process, so the main application stays responsive. It starts with an empty project and isolated temporary settings; it does not add results to your open [project](topic:general/projects) or its [Result Pool](topic:results/intro).

## Pick the files

The **Plan** field points to a TOML plan. Its file list appears under **Files**. **Add from Data Pool** adds every currently loaded measurement file from the [Data Pool](topic:data_management/intro), without duplicates; it does not use only the highlighted rows. **Add file…** opens a file picker (UNV is the first filter, see [Supported formats](topic:import/formats), and **All files** is available). You can also edit the plan to change its files.

Tick **Generated reference signal** to include a deterministic example measurement: a 75-second, 25.6 kHz ramp-up with 16 measurement channels and a tacho channel. Spectra generates it as an ASC file in the system temporary folder when needed and reuses a valid cached file. This file is separate from your project and input measurements.

The supplied `benchmark_plan.toml` is an editable starting point. Adjust its `files` paths for your machine. It also selects analyses, channel counts and the settings to vary (such as [FFT size](topic:shared/fft_size) and tracking step). A Benchmark case is one input file, analysis, channel count and DSP setting combination. The plan's `base` settings apply to cases; `sweep` varies `nfft` and `rpm_step`. In `sweep` mode each setting is varied on its own around `base`; in `product` mode all listed values are combined. Each analysis uses only the settings it supports. The other plan fields set `repeats` and the per-case `timeout_s`.

## Quick and repeated runs

**Quick** is checked by default. It runs each case once and ignores the plan's `sweep` values, using only `base`. Clear it to run the plan's sweep or product combinations and repeat each case the number of times in `repeats` (at least once). The first run is reported separately; later runs are summarized by their median. This lets you see a first, colder run alongside repeated runs after the file and calculation paths have been used.

## Compare with a baseline

Use **Compare with…** to choose a previous Benchmark report in JSON format. The new report adds timing differences for cases it can match. A positive Δ means the current run took longer than the baseline; a negative Δ means it took less time. Cases present in only one report are listed without a timing difference. Reports made with different display backends, such as Headless and Full, are not compared because they time different work.

## Run and stop

Choose an **Output folder**, then press **Run**. The progress bar advances after each case. Press **Stop** to terminate the Benchmark process; an interrupted run may not produce a report. A case can also finish with `skipped`, `error` or `timeout` status. For example, RPM-tracked analyses ([tracking](topic:shared/tracking)) are skipped when the file has no tacho channel. In Full, multi-channel Spectrogram and Overall Level cases are skipped as described above. A timeout is per case and covers its repeats; if work from a timed-out case is still running, later cases are skipped.

If the plan cannot be read or a run fails, the dialog shows the error output. Fix the plan or input path and run it again. Benchmark reports are written only after the run finishes.

## Read the report

The Markdown report opens in the dialog when the run succeeds; choose **Open folder** to see it alongside the JSON report. Each report is named `benchmark_<machine>_<time>.md` and `.json`. The folder is created if needed. The default is `docs/perf` in a source checkout and Spectra's per-user `perf` folder in an installed build.

The report records the machine, software and input-disk details, then gives each case its settings and status. For successful cases it shows the first run and, when there are repeats, the median of the later runs. The step table has:

- **wall ms** — elapsed real time for the step;
- **CPU ms** — CPU time used by the process and all its threads during that step. It can exceed wall time when work uses multiple cores;
- **share** — the step's wall time as a fraction of the case run;
- **peak RAM MB** — the process's resident memory peak sampled while the step runs.

Step rows can overlap or run on several threads, so their shares can add to more than 100%. The case's total wall time includes the whole timed run; step values help locate the cost within it. RAM is the process peak, not memory attributed only to that step.

See [Spectrum](topic:spectrum/intro), [Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) and [Overall Level](topic:overall_level/intro) for what each analysis computes.
