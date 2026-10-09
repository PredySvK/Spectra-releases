### Amplituda a Formát

## Energie po binech

**Jednoduše:** FFT rozdělí signál na „přihrádky" po frekvencích (biny) a do každé nasype, kolik energie signálu v ní leží. **Energie po binech** je ta základní tabulka „kolik energie v kterém binu", se kterou program dál pracuje. Je ve skutečných jednotkách (g²) a už je opravená o okno, takže sinusový signál má stejnou energii, ať použijete jakékoli okno. Linear, Power, PSD, RMS a Peak jsou jen jiné **pohledy** na tutéž tabulku, jako když přepnete [jednotky](topic:units/intro) u téhož měření. Proto přepnutí formátu nic nepočítá znovu.

Sinusový signál nikdy neleží přesně na jednom binu, takže se jeho energie rozdělí mezi sousední biny. Nic se neztratí: součet přes všechny biny je vždy $A^2/2$.

![Sinus 1 g jako energie po binech a jeden bin přečtený jako Linear RMS, Power a PSD](canonical_energy.png)

## Přesně

Pro každý blok $m$ program spočítá $X_m[k]=\sum_{n=0}^{N-1} w[n]\,x[n+mH]\,e^{-j2\pi kn/N}$ a zprůměruje $\lvert X_m[k]\rvert^2$ přes bloky (viz [Spektrum](topic:spectrum/intro)). Výsledek se ukládá jako **energie po binech**

$$P_\text{canon}[k]=\frac{c_k\,\overline{\lvert X[k]\rvert^2}}{N\sum_n w[n]^2},\qquad c_k=\begin{cases}1 & k=0\text{ (DC)}\\ 1 & k=N/2\text{ (Nyquist, sudé }N)\\ 2 & \text{jinak}\end{cases}$$

Je to střední kvadrát ve čtverci jednotky (g²), jednostranný, a součet přes všechny biny se rovná střednímu kvadrátu signálu (Parseval). Sinus o amplitudě $A$ má $\sum_k P_\text{canon}=A^2/2$.

## Pohledy

S $r=\text{ACF}/\text{ECF}$, tedy $r^2=\text{ENBW}$ v binech ([Okna](topic:shared/windows)):

| Formát | RMS | Peak | Jednotka |
|---|---|---|---|
| **Linear** | $r\sqrt{P_\text{canon}}$ | $r\sqrt{c_k P_\text{canon}}$ | g |
| **Power** | $r^2 P_\text{canon}$ | $r^2 c_k P_\text{canon}$ | g² |
| **PSD** | $P_\text{canon}/\Delta f$ | stejné jako RMS | g²/Hz |

$c_k=2$ kromě DC a skutečného Nyquistova binu, kde je 1. Peak je tedy v Linear $\sqrt 2$ násobek RMS a v Power dvojnásobek. Sinus o amplitudě 1 g ukáže v Linear RMS 0,707 g a v Linear Peak 1 g, ať je okno jakékoli. **PSD volbu RMS/Peak ignoruje** a nenásobí se $r$: součet $\text{PSD}\cdot\Delta f$ přes pásmo dává střední kvadrát pásma.

## Sinusový signál a šum: jiný signál, jiný pohled

Kolik energie dostane jeden bin, záleží na tom, **jaký je signál**.

- **Sinusový signál (harmonický)** sedí v jednom až dvou binech. Když zvětšíte velikost FFT $N$, bin se zúží, ale sinusový signál v něm zůstane a jeho energie se nezmění. Výška sinusového signálu v **Linear** (a **Power**) proto na $N$ nezávisí. **PSD** sinusového signálu naopak roste (stejná energie v užším binu), proto PSD **není** vhodná na čtení sinusového signálu.
- **Šum (náhodný signál)** je rozprostřen po všech binech rovnoměrně. Když zvětšíte $N$, má bin víc sousedů, mezi které se energie dělí, takže každý dostane méně: energie po binech, **Linear i Power klesají** (při osminásobném $N$ o 9 dB). **PSD** je energie na hertz, a ta na $N$ nezávisí, takže PSD šumu je stále stejná. Proto se **šum čte v PSD**.

Zkráceně: **sinusový signál čtěte v Linear (nebo Power), šum v PSD**. Pokud signál obsahuje obojí, jedna hodnota z jednoho pohledu bude pro druhou část zavádějící. Program proto počítá vždy energii po binech a pohled si vybíráte podle toho, co zrovna čtete.

![Sinusový signál a šum při N = 1024 a 8192 a jak se s N mění jejich hladina v Linear RMS a v PSD](sine_vs_noise.png)

### Proč se spektra průměrují

Spektrum šumu z jednoho bloku je **rozkolísané**: každý bin je jen náhodný výsledek jednoho měření a hodnota se mezi sousedními biny i mezi bloky silně mění. Sinusový signál v jednom bloku je naopak stabilní. Průměrování více bloků (viz [Spektrum](topic:spectrum/intro)) hladinu šumu uklidní na skutečnou hodnotu (čárkovaná čára), zatímco sinusový signál zůstane, kde byl.

![Sinusový signál v šumu z jednoho bloku a z průměru 50 bloků](spectrum_averaging.png)

## RMS vs. Peak

RMS a Peak je přepínač zobrazení a nic nepřepočítává. **Peak** je $\sqrt2\cdot$ RMS, špička čistého sinusu nesoucího stejnou energii. **Není** to maximum časového průběhu, které je u skutečné vibrace obvykle vyšší. Stejný přepínač škáluje Overall Level, křivky řádů a Residual v [Order Trackingu](topic:order_tracking/intro).

## dB

dB je volba zobrazení, použitá až po pohledu výše. Linear formáty používají $20\log_{10}(y)$, Power a PSD $10\log_{10}(y)$, takže sinusový signál má ve všech třech stejnou hladinu v dB. Před logaritmem se hodnoty ořezávají na $10^{-12}$.

**Výchozí:** Linear, RMS, škála Linear.
