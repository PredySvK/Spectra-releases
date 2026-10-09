### Amplitude & Format

## Energy per bin

**In plain words:** the FFT sorts the signal into frequency "pigeonholes" (bins) and drops into each one the amount of signal energy that lies there. The **energy per bin** is that basic table "how much energy in which bin", which the program keeps working with. It is in real units (g²) and already corrected for the window, so a sine signal has the same energy whichever window you use. Linear, Power, PSD, RMS and Peak are just different **views** of the same table, like switching units on the same measurement. That is why switching the format recomputes nothing. (Display units are a separate choice: see [Units](topic:units/intro).)

A sine signal never sits exactly on one bin, so its energy is shared between neighbouring bins. Nothing is lost: the sum over all bins is always $A^2/2$.

![A 1 g sine as energy per bin, and one bin read as Linear RMS, Power and PSD](canonical_energy.png)

## Exactly

Per block $m$ the program computes $X_m[k]=\sum_{n=0}^{N-1} w[n]\,x[n+mH]\,e^{-j2\pi kn/N}$ and averages $\lvert X_m[k]\rvert^2$ over the blocks (see [Spectrum](topic:spectrum/intro)). The result is stored as the **energy per bin**

$$P_\text{canon}[k]=\frac{c_k\,\overline{\lvert X[k]\rvert^2}}{N\sum_n w[n]^2},\qquad c_k=\begin{cases}1 & k=0\text{ (DC)}\\ 1 & k=N/2\text{ (Nyquist, even }N)\\ 2 & \text{otherwise}\end{cases}$$

It is a mean square in squared units (g²), single-sided, and the sum over all bins equals the mean square of the signal (Parseval). A sine of amplitude $A$ has $\sum_k P_\text{canon}=A^2/2$.

## Views

With $r=\text{ACF}/\text{ECF}$, so $r^2=\text{ENBW}$ in bins ([Windows](topic:shared/windows)):

| Format | RMS | Peak | Unit |
|---|---|---|---|
| **Linear** | $r\sqrt{P_\text{canon}}$ | $r\sqrt{c_k P_\text{canon}}$ | g |
| **Power** | $r^2 P_\text{canon}$ | $r^2 c_k P_\text{canon}$ | g² |
| **PSD** | $P_\text{canon}/\Delta f$ | same as RMS | g²/Hz |

Here $c_k=2$ except DC and a real Nyquist bin, where it is 1. So Peak is $\sqrt 2$ times RMS in Linear and twice in Power. A sine of amplitude 1 g reads 0.707 g in Linear RMS and 1 g in Linear Peak, whatever the window. **PSD ignores the RMS/Peak choice** and is not multiplied by $r$: summing $\text{PSD}\cdot\Delta f$ over a band gives the band mean square.

## Sine signal and noise: a different signal, a different view

How much energy a bin gets depends on **what kind of signal** it is.

- A **sine signal (harmonic)** sits in one or two bins. If you make the FFT size $N$ larger the bin gets narrower, but the sine signal stays in it and its energy does not change. So the sine signal's height in **Linear** (and **Power**) does not depend on $N$. The sine signal's **PSD** instead grows (the same energy in a narrower bin), so PSD is **not** the view for reading a sine signal.
- **Noise (a random signal)** is spread evenly over all bins. If you make $N$ larger each bin has more neighbours to share the energy with, so each one gets less: the energy per bin, **Linear and Power drop** (by 9 dB for eight times the $N$). **PSD** is energy per hertz, which does not depend on $N$, so the PSD of noise stays the same. That is why **noise is read in PSD**.

In short: **read a sine signal in Linear (or Power), noise in PSD**. If a signal holds both, one value from one view will mislead for the other part. That is why the program always computes the energy per bin and you pick the view according to what you are reading.

![A sine signal and noise at N = 1024 and 8192, and how their level in Linear RMS and in PSD changes with N](sine_vs_noise.png)

### Why spectra are averaged

The spectrum of noise from a single block is **jagged**: each bin is just a random outcome of one measurement and the value changes strongly between neighbouring bins and between blocks. A sine signal in a single block is stable. Averaging several blocks (see [Spectrum](topic:spectrum/intro)) settles the noise level at its true value (dashed line), while the sine signal stays where it was.

![A sine signal in noise from one block and from the average of 50 blocks](spectrum_averaging.png)

## RMS vs. Peak

RMS and Peak are a display switch and recompute nothing. **Peak** is $\sqrt2\cdot$ RMS, the peak of a pure sine carrying the same energy. It is **not** the maximum of the time waveform, which for real vibration is usually higher. The same switch scales the Overall Level, the order curves and Residual in [Order Tracking](topic:order_tracking/intro).

## dB

dB is a display choice, applied after the view above. Linear formats use $20\log_{10}(y)$, Power and PSD use $10\log_{10}(y)$, so a sine signal has the same dB level in all three. Values are clipped at $10^{-12}$ before the logarithm.

**Defaults:** Linear, RMS, scale Linear.
