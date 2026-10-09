# Raw data

A **time signal** is a channel exactly as it was read from the file: no DC removal, no [window](topic:shared/windows), no filter.
## Opening a time signal

While the *Project* tab is active, double-click a channel in the [Data Pool](topic:data_management/intro). It opens in a new workspace tab with time on the X axis. Several selected channels open as one [graph](topic:graphs/intro); a channel dropped on an open time graph is added to it.

![A raw channel as a time signal](raw_data.en.png)

On an analysis tab ([Overall Level](topic:overall_level/intro), [Order Tracking](topic:order_tracking/intro), [Spectrogram 2D](topic:spectrogram/intro), [Spectrum 1D](topic:spectrum/intro)) the same double-click computes that analysis instead.

## Axes

| Axis | What it shows |
|---|---|
| X | time in s, from the time base stored in the file. Time is never rescaled by the X axis unit. |
| Y | the channel's values in its unit, converted to the chosen display unit: $y' = k\,y$ ([Units](topic:units/intro)) |

The sampling rate every analysis uses is $f_s = 1/\Delta t$, the spacing of that time base. A channel in another domain than the first one (a microphone next to an accelerometer) gets its own right-hand Y axis.

## Long records

A curve with more than **20 000 points** is drawn only where the view is, and thinned to the screen resolution. This is display only: zoom in to see single samples. Every analysis always reads all samples.

## The tacho channel

A tacho opens like any other channel and shows the speed in the unit recorded in the file. The analyses convert it to rpm themselves.

## What to check

| Look for | Why it matters |
|---|---|
| flat tops at the same level | the sensor or recorder clipped; the spectrum gains false harmonics |
| a level far from the expected one | wrong channel unit -- correct it with **Fix Unit** ([Units](topic:units/intro)) |
| a slow drift or a large offset | DC; the analyses remove the mean (**Remove DC Offset**), the time graph does not |
| spikes or drop-outs | single bad samples spread over every frequency of the block they fall in ([FFT size](topic:shared/fft_size)) |
| a noisy or broken tacho | order tracking and every speed axis depend on it ([Tracking](topic:shared/tracking)) |
