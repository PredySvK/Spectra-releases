## 🎛️ Spectrogram 2D

This module computes a time-frequency or RPM-frequency map of the signal. Each column is one windowed FFT block, so the map shows how the spectral content changes with time or with engine speed.

![Spectrogram 2D tab with its settings groups and a spectrogram](module_spectrogram.en.png)

## Where blocks are cut

One block of $N$ samples is placed **centred on every trigger**; there is no overlap setting and no averaging. The trigger spacing (the *Step*) decides whether neighbouring blocks overlap or leave gaps. Triggers come from [Tacho tracking](topic:shared/tracking):

- **RPM Tracked:** a trigger at every multiple of the step in RPM (default **50 RPM**) where the tacho crosses it, in the chosen sweep direction (Up or Down; Any is refused because a run-up plus run-down crosses each speed twice). The axis is the RPM (see [Order Tracking](topic:order_tracking/intro) for the same data read as orders).
- **Free Run (Time):** a trigger every step seconds from the start of the record (default **0.05 s**). The axis is time. No tacho is needed.

## Per-block computation

For trigger $i$ at sample $s_i$ (rounded to the nearest sample) the block is $x[s_i-\lfloor N/2\rfloor+n]$, $n=0,\dots,N-1$:

$$X_i[k]=\sum_{n=0}^{N-1} w[n]\,x\bigl[s_i-\lfloor N/2\rfloor+n\bigr]\,e^{-j2\pi kn/N},\qquad P_i[k]=g_i\,\frac{c_k\,\lvert X_i[k]\rvert^2}{N\sum_n w[n]^2}$$

This is the same $P_\text{canon}$ as in the [Spectrum](topic:spectrum/intro); the factor $g_i$ is explained next. The result is then shown as Linear, Power or PSD, RMS or Peak with a Linear or dB (Log) colour scale: see [Amplitude format](topic:shared/amplitude_format).

## Blocks at the record edge

A trigger closer than $N/2$ to either end of the record leaves part of its block empty (zeros). The program restores such a block to the level the same content would have further inside the record:

$$g_i=\frac{\sum_{n} w[n]^2}{\sum_{n\ \text{inside the record}} w[n]^2}$$

$g_i=1$ for a whole block. Because a trigger is always inside the record, a block is covered at least half-way and $g_i\le 2$ (amplitude $\le\sqrt2$).

## Defaults

| Setting | Default |
|---|---|
| FFT size / Window | 4096 / Hanning |
| Format / Amplitude / Colour scale | Linear / RMS / Linear |
| Tracking mode | RPM Tracked |
| Step | 50 RPM (time mode: 0.05 s) |
| Sweep / Hysteresis | Up / 10 RPM |
| Remove DC Offset | on (see [Spectrum](topic:spectrum/intro)) |

The record must be at least $N$ samples long. The map's data come from the [raw signal](topic:raw_data/intro) of the channel.

**See also:** [FFT size](topic:shared/fft_size), [Windows](topic:shared/windows), [Amplitude format](topic:shared/amplitude_format), [Tacho tracking](topic:shared/tracking)
