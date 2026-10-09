### Window functions

Okno $w[n]$ násobí každý blok před FFT. Potlačuje **prosakování spektra** (spectral leakage), které vzniká odseknutím neperiodického signálu na okrajích bloku. Všechna okna jsou v *periodické* podobě (určené pro spektrální analýzu), $n = 0,\dots,N-1$.

Když sinusový signál do bloku přesně zapadne (tady 10 celých period), konce bloku na sebe navazují a spektrum je jediná čára. To je ideální případ: žádné prosakování, okno není třeba.

![Sinusový signál, který do bloku přesně zapadá: ve spektru jediná čára](windows_ideal.png)

Skutečný sinusový signál do bloku téměř nikdy nezapadne. Tady má 10,5 periody, takže blok končí uprostřed periody a odseknutí zanechá skok.

![Jeden blok sinusového signálu odseknutý tak, jak je (Rectangular), a zjemněný (Hanning), se spektrem obou](windows_leakage.png)

Okno Rectangular tento skok ponechá a sinusový signál se rozlije po celém spektru jako **vedlejší hrby** vedle **hlavního hrbu**. Okno Hanning blok na obou okrajích zeslabí k nule: vedlejší hrby klesnou mnohem níž, za cenu širšího hlavního hrbu.

![Všech pět oken v čase a jako spektra](windows_shapes.png)

Vlevo je každé okno jako váha $w[n]$, kterou se násobí každý vzorek bloku. Vpravo je, jak se okno chová ve frekvenci; z křivky se čtou dvě věci:

- **Šířka hlavního hrbu** (kde křivka klesá od 0 dB): Rectangular je nejužší, Flat-top nejširší. Čím užší, tím lépe rozlišíte dva blízké sinusové signály.
- **Výška vedlejších hrbů:** asi −13 dB u Rectangular, −31 dB Hanning, −43 dB Hamming, −58 dB Blackman, pod −90 dB Flat-top. Čím nižší, tím menší prosakování.

To je kompromis: okno, které prosakování potlačí lépe, má širší hlavní hrb, a naopak. Flat-top má široký plochý vrchol, takže amplituda sinusového signálu vychází přesně, ale frekvenci z něj odečtete nejhůř.

| Okno (název v pásu karet) | Definice | ACF | ECF | ENBW [binů] |
|---|---|---|---|---|
| Rectangular | $w[n]=1$ | 1.000 | 1.000 | 1.000 |
| Hanning | $0.5-0.5\cos\frac{2\pi n}{N}$ | 2.000 | 1.633 | 1.500 |
| Hamming | $0.54-0.46\cos\frac{2\pi n}{N}$ | 1.852 | 1.586 | 1.363 |
| Blackman | $0.42-0.5\cos\frac{2\pi n}{N}+0.08\cos\frac{4\pi n}{N}$ | 2.381 | 1.812 | 1.727 |
| Flat-top | pětičlenný součet kosinů (níže) | 4.639 | 2.389 | 3.770 |

Činitele jsou uvedeny pro $N=4096$; na $N$ závisejí jen v posledním místě.

$$w_\text{flat-top}[n]=a_0-a_1\cos\tfrac{2\pi n}{N}+a_2\cos\tfrac{4\pi n}{N}-a_3\cos\tfrac{6\pi n}{N}+a_4\cos\tfrac{8\pi n}{N}$$

kde $a_0=0.21557895$, $a_1=0.41663158$, $a_2=0.277263158$, $a_3=0.083578947$, $a_4=0.006947368$.

## Korekční činitele (ACF, ECF)

$$\text{ACF}=\frac{N}{\sum_n w[n]},\qquad \text{ECF}=\sqrt{\frac{N}{\sum_n w[n]^2}},\qquad \text{ENBW}=\left(\frac{\text{ACF}}{\text{ECF}}\right)^2\text{ binů}=\left(\frac{\text{ACF}}{\text{ECF}}\right)^2\Delta f$$

- **ACF** (amplitudová korekce) vrací výšku jednoho sinusového signálu odečtenou z jednoho binu.
- **ECF** (energetická korekce) je to, co potřebuje součet energie přes mnoho binů. [Energie po binech](topic:shared/amplitude_format) je už dělena $\sum w^2$, takže pásmové hladiny další korekci nepotřebují.
- **ENBW** je šířka ideálního obdélníkového filtru, který propustí stejný výkon šumu jako jeden bin okna.

![Sinusový signál a šum, čtené bez činitele, s ACF a s ECF](windows_factors.png)

Totéž měření (sinusový signál a širokopásmový šum, okno Flat-top) čtené třemi způsoby. Okno sníží sinusový signál i šum, ale každý jinak. **ACF** vrátí sinusový signál na správnou výšku, šum pak vychází příliš vysoko. **ECF** srovná šum, sinusový signál pak vychází příliš nízko. Rozdíl mezi nimi je v amplitudě přesně $r=\text{ACF}/\text{ECF}$ (5,8 dB u Flat-top, 1,8 dB u Hanningu).

**Proč nejde mít oboje najednou?** Sinusový signál se sčítá koherentně, jeho výška roste s $\sum w$. Šum se sčítá nekoherentně, jeho výkon roste s $\sum w^2$. U každého okna kromě Rectangular se tyto dvě hodnoty mění jinak, takže jedno číslo srovná vždy jen jednu z nich.

### Který činitel se kdy použije

Program počítá s **ECF**: [energie po binech](topic:shared/amplitude_format) je dělena $\sum w^2$, tedy už je energeticky korigovaná. Činitele nikdy nevybíráte, určuje je formát výsledku:

| Zobrazení | Použitá korekce |
|---|---|
| [Spektrum](topic:spectrum/intro), [Spektrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro): **Linear**, **Power** | **ACF** (násobení $r=\text{ACF}/\text{ECF}$ nad energií, takže sinusový signál vychází ve správné výšce) |
| **PSD**, [Overall Level](topic:overall_level/intro), [Band RMS](topic:tools/band_rms) | žádná další; stačí energie z ECF |

**ENBW** se samostatně nepoužívá, je to jen $r^2$ z tabulky výše.

## Výběr okna

- **Hanning** (výchozí): běžné vibrace, spojité nebo náhodné signály.
- **Hamming:** podobné Hanningu, nejbližší vedlejší hrb je potlačen.
- **Blackman:** silnější potlačení vedlejších hrbů, širší hlavní hrb.
- **Flat-top:** nejlepší přesnost amplitudy pro diskrétní sinusové signály (kalibrační sinus), nejhorší frekvenční rozlišení.
- **Rectangular:** bez okna. Jen pro přechodové jevy, které uvnitř bloku začínají a končí na nule, nebo pro přesně periodické signály.

**Viz také:** [Velikost FFT](topic:shared/fft_size), [Formát amplitudy](topic:shared/amplitude_format)
