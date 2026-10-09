### Frequency Band & Full Bandwidth

- **F min, F max:** the integration band. Default $F_\text{min}=10$ Hz. $F_\text{max}$ must be greater than $F_\text{min}$, otherwise the run is refused.
- **Full Bandwidth** (on by default): $F_\text{max}$ is each file's own Nyquist frequency $f_s/2$. It is a stored intent, not a number, so files with different sampling rates share one result set. It is the true Nyquist limit, not an assumed analogue bandwidth of $f_s/2.56$, which the files do not record.
- **F max above Nyquist:** a typed $F_\text{max}$ is clipped to that file's Nyquist and the effective band is shown in the legend, so a batch over files with mixed sampling rates still runs.
- **Empty band:** if $F_\text{min}\ge f_s/2$ the band contains nothing. For that file it is an error, not a zero curve: it is logged, left out of overlay additions and counted as "partial" in a batch.

## Fractional Bin Weighting

Bin $k$ is centred at $f_k=k\,\Delta f$ and spans $\pm\Delta f/2$. Its weight is the share of that span inside the band:

$$b_k=\operatorname{clip}\!\left(\frac{\min(F_\text{max},\,f_k+\Delta f/2)-\max(F_\text{min},\,f_k-\Delta f/2)}{\Delta f},\ 0,\ 1\right)$$

A bin wholly inside has $b_k=1$, one cut by an edge counts proportionally, and one outside counts 0. Example: $\Delta f=6.25$ Hz and $F_\text{min}=10$ Hz. The bin at 12.5 Hz spans 9.375 to 15.625 Hz, so $b=(15.625-10)/6.25=0.9$, and the bin at 6.25 Hz spans 3.125 to 9.375 Hz and counts 0.

A hard in/out cut would flip a whole bin between 0 and 100 % when an edge crosses it, giving a staircase in the readout although the band content changes smoothly. The same weights are used by [Band RMS](topic:tools/band_rms), by [Overall Level](topic:overall_level/intro) and by the order bands of [Order Tracking](topic:order_tracking/orders), so their numbers agree.


## Legend & Band Identification

- **Default band** ($F_\text{min}$ 10 Hz and Full Bandwidth): the band is left out, e.g. `OAL [file] channel [unit RMS]`.
- **Any other band:** the *effective* band, after clipping to the file's Nyquist, is shown: `OAL 100–12800 Hz [file] channel [unit RMS]`.
- **Residual** (from [Order Tracking](topic:order_tracking/orders)) reads `Residual …` and always has the default band.

The rule is one function, so live curves, comparison overlays and [Result Pool](topic:results/intro) curves are named alike. Two curves count as the same result set when their *requested* band is the same, which is why Full Bandwidth files at different sampling rates share one set.
