## 📈 Overall Level

**Overall Level** follows the total vibration level in one fixed frequency band across a run -- one RMS point per [tracking](topic:shared/tracking) step, against rpm or time. Unlike Order Tracking, it does not single out an order: everything inside the band counts.

![Overall Level tab with its settings groups and an Overall Level curve](module_overall_level.en.png)

**[Band RMS](topic:tools/band_rms)** is the same number read once from Band RMS Cursors on a single [spectrum](topic:spectrum/intro). Every point of an Overall Level curve equals the Band RMS of that step's spectrum, taken with the same FFT settings.

**Pipeline:** optional DC removal → [tracking triggers](topic:shared/tracking) → one [windowed](topic:shared/windows) block per trigger → [FFT](topic:shared/fft_size) → energy per bin $P_\text{canon}[k]$ → weighted sum over the band → $\sqrt{\ }$.

## Formula

$$L=\sqrt{\sum_k b_k\,P_\text{canon}[k]},\qquad b_k\in[0,1]\ \text{the share of bin }k\text{ inside }[F_\text{min},F_\text{max}]$$

$b_k$ is described in [Fractional bins](topic:overall_level/band), and why the sum is an RMS in [Parseval](topic:overall_level/energy_parseval). The result is a Linear RMS value in the unit of the signal; **Peak** shows $\sqrt2\cdot L$ ([RMS vs. Peak](topic:shared/amplitude_format)).

## Defaults

| Setting | Default |
|---|---|
| $F_\text{min}$ / $F_\text{max}$ | 10 Hz / Full Bandwidth (the file's Nyquist) |
| [FFT size](topic:shared/fft_size) / [Window](topic:shared/windows) | 4096 / Hanning |
| Tracking | RPM Tracked, Step 50 RPM, Sweep Up, Hysteresis 10 RPM |
| Free Run (Time) step | 0.05 s |
| [Amplitude](topic:shared/amplitude_format) | RMS |
| Remove DC Offset | on ([Spectrum](topic:spectrum/intro)) |

There is no Linear / Power / PSD choice ([Amplitude format](topic:shared/amplitude_format)): the result does not depend on it.

## Tracking Engine

The tracking decides where the analysis blocks are centred. The rules (RPM targets, interpolation, Sweep, Hysteresis, tacho cleaning) are the same as for the Spectrogram and are written once in [Tacho tracking](topic:shared/tracking). What is specific to Overall Level:

- **RPM Tracked:** one point per target speed; needs a tacho channel. Step default 50 RPM.
- **Free Run (Time):** a block every *Step* seconds from the start of the record, no tacho needed. Step default 0.05 s, minimum 0.001 s.
- **Sweep:** Up, Down or **Any (Both)**. The Spectrogram refuses Any because it must draw one regular image; Overall Level is a curve of $(x,y)$ points, so Any works and returns the points of both directions.
- Block centres near the start or end of the record are corrected for the zero-filled part (gain at most $\sqrt2$), so the first and last points are not read low.

**See also:** [Band](topic:overall_level/band), [Tacho tracking](topic:shared/tracking), [Order Tracking](topic:order_tracking/orders) (Overall Level + Residual)
