### Order Extraction

## The moving band

At a trigger with speed $\text{RPM}$ the band of order $n$ is centred and sized by

$$f_n=\frac{n\cdot\text{RPM}}{60},\qquad W_n=\max\!\Bigl(\Delta O\cdot\frac{\text{RPM}}{60},\ \ B\,\Delta f\Bigr),\qquad \Bigl[f_n-\tfrac{W_n}{2},\ f_n+\tfrac{W_n}{2}\Bigr]$$

with the lower edge clipped at 0 Hz. $\Delta O$ is **Order Width** in orders, $\Delta f=f_s/N$ the bin width and $B$ the **main hump width of the [window](topic:shared/windows) in bins**, measured from the window itself:

| Window | Rectangular | Hanning, Hamming | Blackman | Flat-top |
|---|---|---|---|---|
| $B$ [bins] | 2 | 4 | 6 | about 10 |

So the band is never narrower than the main hump: a sine signal of the order then keeps all its energy in the band, however small Order Width is. With the defaults ($f_s=25\,600$ Hz, $N=4096$, so $\Delta f=6.25$ Hz, Hanning, $\Delta O=0.2$) the band is 25 Hz wide up to $0.2\cdot\text{RPM}/60=25$ Hz, that is up to 7500 rpm, and grows with the speed after that.

## The value

Bins are weighted by the fraction of their width inside the band ([Fractional bins](topic:overall_level/band)):

$$A_n=\sqrt{\sum_k w_{n,k}\,P_\text{canon}[k]},\qquad w_{n,k}\in[0,1]$$

By Parseval the sum is a mean square, so $A_n$ is the RMS of the order in the unit of the signal.

**When there is no value.** The curve has a gap (NaN) at every trigger where $f_n<\Delta f$ (below the FFT resolution) or $f_n>f_s/2$. If *every* requested order is a gap everywhere, the run is refused with a message naming the rpm range and the FFT resolution; use a smaller FFT size or lower orders.

## Overall Level + Residual

With **Overall Level + Residual** ticked, the same $P_\text{canon}$ also gives two more curves, from one pass:

- **OAL**: the [Overall Level](topic:overall_level/intro) of the default band, 10 Hz to each file's Nyquist ($F_\text{min}=10$ Hz, Full Bandwidth). The band cannot be changed here. It uses this tab's [FFT](topic:shared/fft_size), [window](topic:shared/windows), Step, Sweep ([tracking](topic:shared/tracking)), Hysteresis and Remove DC.
- **Residual**: the energy of that band **outside** every selected order's band.

With $b_k$ the fraction of bin $k$ inside the OAL band and $m_k$ the fraction covered by the **union** of the order bands (clipped to the OAL band):

$$\text{OAL}=\sqrt{\sum_k b_k P_k},\qquad \text{Explained}=\sqrt{\sum_k m_k P_k},\qquad \text{Residual}=\sqrt{\sum_k (b_k-m_k)\,P_k}$$

$$\text{Explained}^2+\text{Residual}^2=\text{OAL}^2$$

This holds at every point, and Residual is never negative.

### Example

Run-up on a gearbox, one point at 3000 rpm: the shaft is at 50 Hz, **Target Orders** `2, 4`. Order 2 is at 100 Hz, order 4 at 200 Hz; each band is 25 Hz wide (the main hump), so the bands do not touch. Suppose the integrals read

| | Energy [g²] | Level [g RMS] |
|---|---|---|
| OAL (10 Hz – Nyquist) | 1.00 | 1.00 |
| Order 2 | 0.64 | 0.80 |
| Order 4 | 0.16 | 0.40 |
| Explained (union) | 0.80 | 0.89 |
| **Residual** | **0.20** | **0.45** |

The two orders explain 80 % of the energy in the band. The other 20 % (Residual 0.45 g) is something else at that speed: a resonance, noise, an order you did not select. Where Residual is the biggest curve on the graph, look for what is missing, for instance with [Dominant orders](topic:evaluation/dominant_orders).

### Why not subtract the order curves?

$\sqrt{\text{OAL}^2-\sum A_n^2}$ looks like the same thing but it counts shared energy twice. At low speed the bands of neighbouring orders overlap: at 600 rpm the shaft is 10 Hz, orders 1 and 2 sit at 10 and 20 Hz, and both bands are 25 Hz wide, so they cover mostly the same bins. The sum of squares then exceeds the OAL and the difference goes negative. Residual uses the union, so each bin counts once. An order that has no value at a trigger (the gaps above) masks nothing there. The [RMS / Peak](topic:shared/amplitude_format) switch scales Residual like the orders.

Live order dock only: Overall Level + Residual is not available in [batch](topic:batch/intro), in a workflow block or in a saved h5 ([Result Pool](topic:results/intro)).
