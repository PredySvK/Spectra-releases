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

$P_m[k]=\lvert X_m[k]\rvert^2$ is the unscaled power of block $m$. The averaging is done before scaling, on power in every mode but Linear average. The modes are named and ordered as in Simcenter Testlab:

| Mode | Result | Notes |
|---|---|---|
| **Energy average** (default) | $\bar P[k]=\frac1M\sum_m P_m[k]$ | classic block average of power |
| **Linear average** | $\bar P[k]=\Bigl(\frac1M\sum_m \lvert X_m[k]\rvert\Bigr)^2$ | mean amplitude; lower than Energy average when the level changes (run-up, noise). Linear format only |
| **Energy exponential average** | $\bar P_0=P_0,\quad \bar P_m=p\,\bar P_{m-1}+(1-p)\,P_m$ | later blocks weigh more; $p$ is the Exponential parameter |
| **Minimum value** | $\bar P[k]=\min_m P_m[k]$ | the quietest each bin got |
| **Maximum value** | $\bar P[k]=\max_m P_m[k]$ | keeps a transient a mean would wash out |

The Exponential parameter $p$ (ribbon *Exp. parameter*, 0–99 %, default **50 %**) is used by Energy exponential average only. It is how much of the old average each new block keeps, as in Testlab, so the same percentage gives the same spectrum: 10 % is $0.1\,\bar P_{m-1}+0.9\,P_m$. A higher value smooths more; 0 % is the last block alone.

Linear average shows exactly the mean amplitude $\frac1M\sum_m \lvert X_m\rvert$, RMS or Peak, linear or in dB. **It shows only the Linear format:** the square of a mean amplitude is not the mean power (Testlab's Power and PSD with Linear average are the Energy average), and a PSD of it is no density (on noise it reads about 1 dB low). The ribbon therefore offers neither Power nor PSD with Linear average, and a Linear average curve already on a graph is hidden in those views, with the reason in the plot title. For Power or PSD use Energy average.

## Scaling and view

$\bar P$ becomes $P_\text{canon}$ and is then shown as Linear, Power or PSD, RMS or Peak, with a Linear or dB axis: see [Amplitude format](topic:shared/amplitude_format). Frequency axis: $f_k=k\,f_s/N$.

## Defaults

| Setting | Default |
|---|---|
| FFT size | 4096 |
| Window | Hanning |
| Format / Amplitude / Scale | Linear / RMS / Linear |
| Averaging | Energy average, Exponential parameter 50 % |
| Remove DC Offset | on |
| Overlap | 50 % (fixed) |

**Remove DC Offset** subtracts the mean of the whole record before blocking. A [tacho](topic:shared/tracking) or RPM channel is never touched.

**See also:** [FFT size](topic:shared/fft_size), [Windows](topic:shared/windows), [Amplitude format](topic:shared/amplitude_format)
