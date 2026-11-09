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

$P_m[k]=\lvert X_m[k]\rvert^2$ je neškálovaný výkon bloku $m$. Průměruje se před škálováním, ve všech režimech kromě Linear average výkon. Režimy se jmenují a řadí jako v Simcenter Testlab:

| Režim | Výsledek | Poznámka |
|---|---|---|
| **Energy average** (výchozí) | $\bar P[k]=\frac1M\sum_m P_m[k]$ | klasický průměr výkonu bloků |
| **Linear average** | $\bar P[k]=\Bigl(\frac1M\sum_m \lvert X_m[k]\rvert\Bigr)^2$ | průměr amplitudy; nižší než Energy average, když se úroveň mění (rozběh, šum). Jen formát Linear |
| **Energy exponential average** | $\bar P_0=P_0,\quad \bar P_m=p\,\bar P_{m-1}+(1-p)\,P_m$ | pozdější bloky váží více; $p$ je Exponential parameter |
| **Minimum value** | $\bar P[k]=\min_m P_m[k]$ | nejnižší hodnota, kterou bin měl |
| **Maximum value** | $\bar P[k]=\max_m P_m[k]$ | zachová přechodový jev, který by průměr setřel |

Exponential parameter $p$ (pás karet *Exp. parameter*, 0–99 %, výchozí **50 %**) se používá jen v režimu Energy exponential average. Říká, kolik ze starého průměru si každý nový blok ponechá, stejně jako v Testlabu, takže stejné procento dá stejné spektrum: 10 % je $0{,}1\,\bar P_{m-1}+0{,}9\,P_m$. Vyšší hodnota vyhlazuje víc; 0 % je jen poslední blok.

Linear average ukáže přesně průměr amplitudy $\frac1M\sum_m \lvert X_m\rvert$, RMS nebo Peak, lineárně nebo v dB. **Ukazuje jen formát Linear:** druhá mocnina průměru amplitudy není průměrný výkon (Power a PSD s Linear average jsou v Testlabu Energy average) a PSD z něj není hustota (na šumu vyjde asi o 1 dB níž). Pás karet proto s Linear average nenabízí Power ani PSD a křivka Linear average, která už v grafu je, se v těchto pohledech skryje a důvod stojí v titulku grafu. Pro Power nebo PSD použijte Energy average.

## Škálování a pohled

$\bar P$ se stane $P_\text{canon}$ a pak se zobrazí jako Linear, Power nebo PSD, RMS nebo Peak, s lineární nebo dB osou: viz [Formát amplitudy](topic:shared/amplitude_format). Frekvenční osa: $f_k=k\,f_s/N$.

## Výchozí hodnoty

| Nastavení | Výchozí |
|---|---|
| Velikost FFT | 4096 |
| Okno | Hanning |
| Formát / Amplituda / Škála | Linear / RMS / Linear |
| Průměrování | Energy average, Exponential parameter 50 % |
| Remove DC Offset | zapnuto |
| Překryv | 50 % (pevný) |

**Remove DC Offset** odečte průměr celého záznamu před dělením na bloky. [Kanál tacha](topic:shared/tracking) nebo RPM se nikdy neupravuje.

**Viz také:** [Velikost FFT](topic:shared/fft_size), [Okna](topic:shared/windows), [Formát amplitudy](topic:shared/amplitude_format)
