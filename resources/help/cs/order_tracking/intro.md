## ⚡ Order Tracking

**Řád** je vibrace, jejíž frekvence je pevným násobkem otáček hřídele: řád $n$ leží na $f_n=n\cdot\text{RPM}/60$. Order Tracking vyřízne z časového signálu amplitudu vybraných řádů a vykreslí ji proti otáčkám. Výsledkem je jedna křivka na řád.

![Záložka Order Tracking s nastavením, řádovými křivkami a tabulkou Evaluation](module_order_tracking.cs.png)

**Postup:** volitelné odečtení DC → tacho na otáčky → [triggery trackingu](topic:shared/tracking) → jeden [okénkovaný](topic:shared/windows) blok na trigger → [FFT](topic:shared/fft_size) → energie po binech → integrace pásma, které se pohybuje s otáčkami → $\sqrt{\ }$.

## Kroky

1. Otáčky dává kanál tacha. Triggery se kladou tam, kde protnou celé násobky *Step*, ve zvoleném směru *Sweep*: viz [Tacho tracking](topic:shared/tracking). **Order Tracking vždy sleduje otáčky**; časový režim neexistuje a kanál tacha je nutný.
2. Blok $N$ vzorků (velikost FFT) se vyřízne **vystředěný na každý trigger** a okénkuje. Blok, který přesahuje začátek nebo konec záznamu, se doplní nulami a opraví o chybějící energii (zisk nejvýše $\sqrt2$).
3. Každý blok se stane [energií po binech](topic:shared/amplitude_format) $P_\text{canon}[k]$, tedy stejnými čísly, jaká drží sloupec [Spektrogramu](topic:spectrogram/intro) se stejným nastavením.
4. Pro každý řád se sečte energie pásma kolem $n\cdot\text{RPM}/60$ ([Extrakce řádů](topic:order_tracking/orders)). Hodnota křivky je její odmocnina, amplituda **Linear RMS**.

**RMS / Peak** ([Formát amplitudy](topic:shared/amplitude_format)) je přepínač zobrazení: Peak $=\sqrt2\cdot$ RMS, nic se nepřepočítává. Křivka řádu se vždy ukládá jako Linear RMS.

## Výchozí hodnoty

| Nastavení | Výchozí |
|---|---|
| Target Orders | 1 (seznam oddělený čárkami) |
| Order Width $\Delta O$ | 0,2 (rozsah 0,01–2) |
| [Velikost FFT](topic:shared/fft_size) / [Okno](topic:shared/windows) | 4096 / Hanning |
| Step / Sweep / Hystereze | 50 RPM / Up / 10 RPM |
| Amplituda | RMS |
| Remove DC Offset | zapnuto (tacho se nikdy neupravuje) |
| Overall Level + Residual | vypnuto |

**Viz také:** [Extrakce řádů](topic:order_tracking/orders), [Overall Level](topic:overall_level/intro), [Velikost FFT](topic:shared/fft_size), [Okna](topic:shared/windows), [Formát amplitudy](topic:shared/amplitude_format), [Tacho tracking](topic:shared/tracking), [Evaluation](topic:evaluation/intro) (tabulka hodnot řádů), [Remove DC Offset](topic:shared/remove_dc)
