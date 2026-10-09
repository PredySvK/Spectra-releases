# Units

Spectra keeps every number in the unit the measurement was recorded in and converts only what is *shown*. Three separate things are called "units":

| What | Where | Stored | Affects |
|---|---|---|---|
| **Display units** (Y axis) | *Settings* tab, **Unit Settings** | the application (all projects) | the value axis of graphs and the [Evaluation table](topic:evaluation/intro) |
| **X axis unit** | *Settings* tab, **View** | the open project | every frequency and speed axis |
| **Channel unit** (a correction) | [Data Pool](topic:data_management/intro), **Fix Unit** | the project | one channel, and what is computed from it |

## Display units

**Unit Settings** offers one unit per physical domain:

| Domain | Choices | Default |
|---|---|---|
| Linear acceleration | g, m/s&sup2;, mm/s&sup2; | g |
| Acoustic / fluid pressure | Pa, bar, mbar | Pa |
| Electrical voltage | V, mV | V |
| Rotational speed / frequency | rpm, Hz, rad/s | rpm |

A channel belongs to a domain by its **channel type**: accelerometer, microphone, voltage or tacho (how the type is found: [Formats](topic:import/formats)). A channel of any other type (a force in N, a temperature) is never converted. The choice is remembered by the application, not by the project, and **Reset All Settings** brings the defaults back.

### How a value is converted

The conversion is one scalar factor $k$ between the channel's unit and the chosen one, applied to the values of the curve. Nothing is recomputed -- no FFT, no tracking -- so a change is instant.

- **Time signal and linear spectrum** (`g RMS`, `g Peak`): $y' = k\,y$.
- **Power and PSD** (`(g)^2`, `(g)^2/Hz`): $y' = k^2\,y$, because the quantity is squared.
- The label is rewritten with the new unit: `m/s2 RMS`, `(m/s2)^2/Hz`, and so on.

Fixed relations: 1 g = 9.80665 m/s&sup2;; 1 m/s&sup2; = 1000 mm/s&sup2;; 1 bar = 1000 mbar = 10<sup>5</sup> Pa; 1 V = 1000 mV; 1 Hz = 60 rpm = 2&pi; rad/s. In the speed domain a frequency in Hz means *revolutions per second*, which is why 1 Hz is 2&pi; rad/s and not 1 rad/s.

A conversion that is not possible (an unknown unit string) leaves the values as they are and writes a warning to the System Log.

### What is redrawn

**Apply &amp; Save Units** re-scales, from the untouched data of each graph:

- open **[Time](topic:raw_data/intro)** graphs and **[Spectrum](topic:spectrum/intro)** graphs;
- the **Evaluation** table, which follows the display units ([Evaluation](topic:evaluation/intro));
- the [Data Pool](topic:data_management/intro) tree.

[Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) and [Overall Level](topic:overall_level/intro) graphs are *not* re-scaled by the change; they take the new unit the next time their curve is drawn.

## X axis unit

**Native**, **Hz** or **RPM**. It is a property of the open [project](topic:general/projects) and is saved with it (a project without the entry opens as Native).

- **Native**: every graph keeps its own axis -- [spectra](topic:spectrum/intro) in Hz, [order cuts](topic:order_tracking/orders) and [Overall Level](topic:overall_level/intro) against speed in RPM, time in s.
- **Hz**: a speed axis (RPM) is drawn in Hz, $f = \text{rpm}/60$.
- **RPM**: a frequency axis (Hz) is drawn in RPM, $\text{rpm} = 60\,f$. A spectrogram follows on both of its axes.

It is a display rescale only. Nothing is projected: an order cut stays a curve against shaft speed, it merely reads in Hz. Time is never rescaled. Switching the unit on an Untitled project does not ask to save; on a project with a file it marks the project as changed.

### One X domain per graph

A graph has one X quantity (time, frequency or speed). A curve whose native quantity differs is drawn only if an exact conversion exists. The only one is **order cut &rarr; frequency**: a curve at a fixed order $o$ against speed is placed at

$$f = \frac{o\cdot \text{rpm}}{60}$$

point by point, without interpolation. Any other mismatch (a time signal on a spectrum graph) is not drawn.

## Two units on one graph

Curves of the same domain share the left axis, whatever their own units: a curve in m/s&sup2; dropped on a graph in g is converted to g. A curve of a different domain (a microphone in Pa on an accelerometer graph) gets its own **right-hand Y axis**; the two axes zoom together.

## Fix Unit

A file sometimes declares the wrong unit (an accelerometer saved as `V`, or `g` for data in m/s&sup2;). **Fix Unit** in the context menu of a channel in the Data Pool corrects it for one channel or a whole selection. The list offers units of the same domain first, then all others.

- The correction is stored **in the project**, per measurement and channel. The measurement file is never touched; the correction is applied again every time the folder is read.
- It changes what is computed, so a saved result computed before the correction is **not reused** for that channel ([Projects and cache](topic:general/projects)).
- Without a project data folder to attach it to, a correction holds for the current session only; the System Log says so.
