## 📈 Spectrum 1D

This module computes a single-sided, block-averaged frequency spectrum of the selected time signal. It is used to find dominant frequencies and resonance peaks.

![Spectrum 1D tab with its settings groups, a spectrum and the Evaluation table](module_spectrum.en.png)

**Pipeline:** optional DC removal → cut into blocks → [window](topic:shared/windows) → [FFT](topic:shared/fft_size) → average the blocks → energy per bin → [chosen format](topic:shared/amplitude_format).

**What a bin is.** The FFT of a block of $N$ samples gives values on a fixed frequency grid $f_k=k\,\Delta f$, where $\Delta f=f_s/N$ and $k=0,\dots,N/2$. One such value is a **bin**: a "slot" of width $\Delta f$ around the frequency $f_k$ into which the FFT collects the signal energy. For example, at $f_s=25\,600$ Hz and $N=4096$, $\Delta f=6.25$ Hz, so a 100 Hz sine signal falls into bin $k=16$.

## Blocks and overlap

With record length $L$, FFT size $N$ and overlap $o$ the blocks start at a fixed hop:

$$H=\max\bigl(1,\ \operatorname{round}(N(1-o))\bigr),\qquad M=\left\lfloor\frac{L-N}{H}\right\rfloor+1,\qquad \text{block } m \text{ starts at sample } mH$$

**The overlap is fixed at 50 %** ($H=N/2$); there is no ribbon control for it. Samples after the last whole block are not used, a record shorter than $N$ is refused, and nothing is padded.

## Averaging

$P_m[k]=\lvert X_m[k]\rvert^2$ is the unscaled power of block $m$. The averaging is done on power, before scaling:

| Mode | Result | Notes |
|---|---|---|
| **Linear** (default) | $\bar P[k]=\frac1M\sum_m P_m[k]$ | classic block average |
| **Peak Hold** | $\bar P[k]=\max_m P_m[k]$ | keeps a transient a mean would wash out |
| **Exponential** | $\bar P_0=P_0,\quad \bar P_m=(1-\alpha)\,\bar P_{m-1}+\alpha\,P_m$ | later blocks weigh more; $\alpha$ is clamped to 0–1 |

The weight $\alpha$ (ribbon *Weight α*, range 0.01–1, default **0.1**) is used by Exponential only.

## Scaling and view

$\bar P$ becomes $P_\text{canon}$ and is then shown as Linear, Power or PSD, RMS or Peak, with a Linear or dB axis: see [Amplitude format](topic:shared/amplitude_format). Frequency axis: $f_k=k\,f_s/N$.

## Defaults

| Setting | Default |
|---|---|
| FFT size | 4096 |
| Window | Hanning |
| Format / Amplitude / Scale | Linear / RMS / Linear |
| Averaging | Linear, $\alpha=0.1$ |
| Remove DC Offset | on |
| Overlap | 50 % (fixed) |

**Remove DC Offset** subtracts the mean of the whole record before blocking. A [tacho](topic:shared/tracking) or RPM channel is never touched.

**See also:** [FFT size](topic:shared/fft_size), [Windows](topic:shared/windows), [Amplitude format](topic:shared/amplitude_format)
