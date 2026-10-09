## ⚡ Order Tracking

An **order** is a vibration whose frequency is a fixed multiple of the shaft speed: order $n$ sits at $f_n=n\cdot\text{RPM}/60$. Order Tracking cuts the amplitude of chosen orders out of a time signal and plots it against rpm. The result is one curve per order.

![Order Tracking tab with its settings groups, order curves and the Evaluation table](module_order_tracking.en.png)

**Pipeline:** optional DC removal → tacho to rpm → [tracking triggers](topic:shared/tracking) → one [windowed](topic:shared/windows) block per trigger → [FFT](topic:shared/fft_size) → energy per bin → integrate a band that moves with the speed → $\sqrt{\ }$.

## Steps

1. The tacho channel gives the speed. Triggers are placed where it crosses whole multiples of *Step*, in the chosen *Sweep* direction: see [Tacho tracking](topic:shared/tracking). **Order Tracking always tracks against rpm**; there is no time mode and a tacho channel is required.
2. A block of $N$ samples (FFT size) is cut **centred on each trigger** and windowed. A block that runs off the start or end of the record is zero-filled and corrected for the missing energy (gain at most $\sqrt2$).
3. Every block becomes [energy per bin](topic:shared/amplitude_format) $P_\text{canon}[k]$, the same numbers a [Spectrogram](topic:spectrogram/intro) with the same settings holds in that column.
4. Per order, the energy of a band around $n\cdot\text{RPM}/60$ is summed ([Order extraction](topic:order_tracking/orders)). The curve value is its square root, a **Linear RMS** amplitude.

**RMS / Peak** ([Amplitude format](topic:shared/amplitude_format)) is a display switch: Peak $=\sqrt2\cdot$ RMS, nothing is recomputed. An order curve is always stored as Linear RMS.

## Defaults

| Setting | Default |
|---|---|
| Target Orders | 1 (comma-separated list) |
| Order Width $\Delta O$ | 0.2 (range 0.01–2) |
| FFT size / Window | 4096 / Hanning |
| Step / Sweep / Hysteresis | 50 RPM / Up / 10 RPM |
| Amplitude | RMS |
| Remove DC Offset | on (the tacho is never touched) |
| Overall Level + Residual | off |

**See also:** [Order extraction](topic:order_tracking/orders), [Overall Level](topic:overall_level/intro), [FFT size](topic:shared/fft_size), [Windows](topic:shared/windows), [Amplitude format](topic:shared/amplitude_format), [Tacho tracking](topic:shared/tracking), [Evaluation](topic:evaluation/intro) (the table of order values), [Remove DC Offset](topic:shared/remove_dc)
