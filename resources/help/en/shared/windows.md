### Windowing Functions

A window $w[n]$ multiplies every block before the FFT. It reduces **spectral leakage**, which appears because a non-periodic signal is cut off at the block edges. All windows are the *periodic* form (the form meant for spectral analysis), $n = 0,\dots,N-1$.

When a sine signal fits the block exactly (here 10 whole cycles), the block's two ends meet and the spectrum is a single line. This is the ideal case: no leakage, no window needed.

![A sine signal that fits the block exactly: one line in the spectrum](windows_ideal.png)

A real sine signal almost never fits. Here it has 10.5 cycles, so the block ends mid-cycle and the cut-off leaves a jump.

![One block of a sine signal cut off as it is (Rectangular) and tapered (Hanning), with the spectrum of each](windows_leakage.png)

The Rectangular window keeps that jump, and it spreads the sine signal over the whole spectrum as **side humps** next to the **main hump**. The Hanning window fades the block to zero at both edges: the side humps fall far lower, at the price of a wider main hump.

![The five windows in time and as spectra](windows_shapes.png)

On the left, each window as the weight $w[n]$ applied to every sample of the block. On the right, how each window behaves in frequency; two things can be read from the curve:

- **Width of the main hump** (where the curve falls from 0 dB): Rectangular is the narrowest, Flat-top the widest. The narrower, the better two close sine signals can be told apart.
- **Height of the side humps:** about −13 dB for Rectangular, −31 dB Hanning, −43 dB Hamming, −58 dB Blackman, below −90 dB Flat-top. The lower, the less leakage.

That is the trade-off: a window that suppresses leakage better has a wider main hump, and the other way round. Flat-top has a wide flat top, so the amplitude of a sine signal reads accurately, but its frequency is the hardest to read.

| Window (ribbon name) | Definition | ACF | ECF | ENBW [bins] |
|---|---|---|---|---|
| Rectangular | $w[n]=1$ | 1.000 | 1.000 | 1.000 |
| Hanning | $0.5-0.5\cos\frac{2\pi n}{N}$ | 2.000 | 1.633 | 1.500 |
| Hamming | $0.54-0.46\cos\frac{2\pi n}{N}$ | 1.852 | 1.586 | 1.363 |
| Blackman | $0.42-0.5\cos\frac{2\pi n}{N}+0.08\cos\frac{4\pi n}{N}$ | 2.381 | 1.812 | 1.727 |
| Flat-top | five-term cosine sum (below) | 4.639 | 2.389 | 3.770 |

The factors are shown for $N=4096$; they depend on $N$ only in the last digit.

$$w_\text{flat-top}[n]=a_0-a_1\cos\tfrac{2\pi n}{N}+a_2\cos\tfrac{4\pi n}{N}-a_3\cos\tfrac{6\pi n}{N}+a_4\cos\tfrac{8\pi n}{N}$$

with $a_0=0.21557895$, $a_1=0.41663158$, $a_2=0.277263158$, $a_3=0.083578947$, $a_4=0.006947368$.

## Correction factors

$$\text{ACF}=\frac{N}{\sum_n w[n]},\qquad \text{ECF}=\sqrt{\frac{N}{\sum_n w[n]^2}},\qquad \text{ENBW}=\left(\frac{\text{ACF}}{\text{ECF}}\right)^2\text{ bins}=\left(\frac{\text{ACF}}{\text{ECF}}\right)^2\Delta f$$

- **ACF** (amplitude correction) restores the height of a single sine signal read from one bin.
- **ECF** (energy correction) is what a sum of energy over many bins needs. [Energy per bin](topic:shared/amplitude_format) is already divided by $\sum w^2$, so band levels need no further correction.
- **ENBW** is the width of an ideal rectangular filter that passes the same noise power as one bin of the window.

![A sine signal and noise, read with no factor, with ACF and with ECF](windows_factors.png)

The same measurement (a sine signal plus broadband noise, Flat-top window) read three ways. A window lowers both the sine signal and the noise, but by different amounts. **ACF** brings the sine signal back to its true height, and the noise floor then reads too high. **ECF** brings the noise floor right, and the sine signal then reads too low. The gap between the two is exactly $r=\text{ACF}/\text{ECF}$ in amplitude (5.8 dB for Flat-top, 1.8 dB for Hanning).

**Why not both at once?** A sine signal adds up coherently, so its height scales with $\sum w$. Noise adds up incoherently, so its power scales with $\sum w^2$. For every window except Rectangular these two scale differently, so one number can make only one of them right.

### Which factor is used when

The program works with **ECF**: [energy per bin](topic:shared/amplitude_format) is divided by $\sum w^2$, so it is already energy-corrected. You never pick a factor; the result format decides:

| View | Correction applied |
|---|---|
| [Spectrum](topic:spectrum/intro), [Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro): **Linear**, **Power** | **ACF** (multiplying by $r=\text{ACF}/\text{ECF}$ on top of the energy, so a sine signal reads at its true height) |
| **PSD**, [Overall Level](topic:overall_level/intro), [Band RMS](topic:tools/band_rms) | none further; the ECF-based energy is enough |

**ENBW** is not applied on its own; it is just $r^2$ from the table above.

## Choosing a window

- **Hanning** (default): general vibration, continuous or random signals.
- **Hamming:** similar to Hanning, with the nearest side hump cancelled.
- **Blackman:** stronger side-hump suppression, wider main hump.
- **Flat-top:** best amplitude accuracy for discrete sine signals (calibration sine), poorest frequency resolution.
- **Rectangular:** no window. Use it only for transients that start and end at zero inside the block, or for exactly periodic signals.

**See also:** [FFT size](topic:shared/fft_size), [Amplitude format](topic:shared/amplitude_format)
