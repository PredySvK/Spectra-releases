### Energy per Bin & Parseval's Invariance

**In plain words:** Parseval's theorem says that the total energy of a signal is the same whether you add it up in time or in frequency. The FFT only re-sorts the same signal into frequency "pigeonholes" (bins); nothing is added and nothing is lost. A pythagorean analogy: the length of a vector does not change when you rotate the axes, and the FFT is just such a rotation.

**Why the program uses it:** it lets Overall Level read the energy of a band straight from the spectrum, without going back to the time signal and filtering it. You add up the bins that lie in the band and take the square root. It is also why a result does not depend on the [window](topic:shared/windows) or on the FFT size, and why Linear, Power and PSD all give the same Overall Level.

## Exactly

Overall Level sums [energy per bin](topic:shared/amplitude_format), $P_\text{canon}[k]=c_k\lvert X[k]\rvert^2/(N\sum w^2)$, which is a mean square per bin. By **Parseval's theorem** the sum over all bins is the mean square of the signal, and the sum over a band is the mean square of the part of the signal inside that band.

$$L^2=\sum_k b_k P_\text{canon}[k]\ \ [\text{unit}^2]$$

A PSD is $P_\text{canon}/\Delta f$, so $\sum \text{PSD}\cdot\Delta f$ is the same energy, and the Linear, Power and PSD views all integrate to the same $L$. This is why Overall Level has no format setting. The [window](topic:shared/windows) is already divided out ($\sum w^2$ in the denominator), so no further window correction applies to a band level.

Check: a sine of amplitude $A$ well inside the band gives $L=A/\sqrt2$, whatever the window.
