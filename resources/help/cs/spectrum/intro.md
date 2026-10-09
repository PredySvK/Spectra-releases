## 📈 Spectrum 1D

Tento modul počítá jednostranné, přes bloky průměrované frekvenční spektrum vybraného časového signálu. Slouží k nalezení dominantních frekvencí a rezonančních špiček.

![Záložka Spectrum 1D s nastavením, spektrem a tabulkou Evaluation](module_spectrum.cs.png)

**Postup:** volitelné odečtení DC → dělení na bloky → [okno](topic:shared/windows) → [FFT](topic:shared/fft_size) → průměrování bloků → energie po binech → [zvolený formát](topic:shared/amplitude_format).

**Co je bin.** FFT bloku o $N$ vzorcích dá hodnoty na pevné mřížce frekvencí $f_k=k\,\Delta f$, kde $\Delta f=f_s/N$ a $k=0,\dots,N/2$. Jedna taková hodnota je **bin**: „přihrádka“ šířky $\Delta f$ kolem frekvence $f_k$, do které FFT sečte energii signálu. Např. při $f_s=25\,600$ Hz a $N=4096$ je $\Delta f=6{,}25$ Hz, takže sinusový signál o 100 Hz leží v binu $k=16$.

## Bloky a překryv

Při délce záznamu $L$, velikosti FFT $N$ a překryvu $o$ začínají bloky v pevném kroku:

$$H=\max\bigl(1,\ \operatorname{round}(N(1-o))\bigr),\qquad M=\left\lfloor\frac{L-N}{H}\right\rfloor+1,\qquad \text{blok } m \text{ začíná ve vzorku } mH$$

**Překryv je pevný 50 %** ($H=N/2$); v pásu karet pro něj není ovládací prvek. Vzorky za posledním celým blokem se nepoužijí, záznam kratší než $N$ se odmítne a nic se nedoplňuje.

## Průměrování

$P_m[k]=\lvert X_m[k]\rvert^2$ je neškálovaný výkon bloku $m$. Průměruje se výkon, před škálováním:

| Režim | Výsledek | Poznámka |
|---|---|---|
| **Linear** (výchozí) | $\bar P[k]=\frac1M\sum_m P_m[k]$ | klasický průměr bloků |
| **Peak Hold** | $\bar P[k]=\max_m P_m[k]$ | zachová přechodový jev, který by průměr setřel |
| **Exponential** | $\bar P_0=P_0,\quad \bar P_m=(1-\alpha)\,\bar P_{m-1}+\alpha\,P_m$ | pozdější bloky váží více; $\alpha$ se ořezává na 0–1 |

Váha $\alpha$ (pás karet *Weight α*, rozsah 0,01–1, výchozí **0,1**) se používá jen v režimu Exponential.

## Škálování a pohled

$\bar P$ se stane $P_\text{canon}$ a pak se zobrazí jako Linear, Power nebo PSD, RMS nebo Peak, s lineární nebo dB osou: viz [Formát amplitudy](topic:shared/amplitude_format). Frekvenční osa: $f_k=k\,f_s/N$.

## Výchozí hodnoty

| Nastavení | Výchozí |
|---|---|
| Velikost FFT | 4096 |
| Okno | Hanning |
| Formát / Amplituda / Škála | Linear / RMS / Linear |
| Průměrování | Linear, $\alpha=0{,}1$ |
| Remove DC Offset | zapnuto |
| Překryv | 50 % (pevný) |

**Remove DC Offset** odečte průměr celého záznamu před dělením na bloky. [Kanál tacha](topic:shared/tracking) nebo RPM se nikdy neupravuje.

**Viz také:** [Velikost FFT](topic:shared/fft_size), [Okna](topic:shared/windows), [Formát amplitudy](topic:shared/amplitude_format)
