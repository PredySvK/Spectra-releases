## 📈 Overall Level

**Overall Level** sleduje celkovou úroveň vibrací v jednom pevném frekvenčním pásmu během celého měření: jeden bod RMS na krok [trackingu](topic:shared/tracking), proti otáčkám nebo času. Na rozdíl od Order Tracking nevybírá žádný řád, počítá se všechno, co v pásmu leží.

![Záložka Overall Level s nastavením a křivkou Overall Level](module_overall_level.cs.png)

**[Band RMS](topic:tools/band_rms)** je totéž číslo odečtené jednou z Band RMS kurzorů na jednom [spektru](topic:spectrum/intro). Každý bod křivky Overall Level se rovná Band RMS spektra daného kroku při stejném nastavení FFT.

**Postup:** volitelné odečtení DC → [triggery trackingu](topic:shared/tracking) → jeden [okénkovaný](topic:shared/windows) blok na trigger → [FFT](topic:shared/fft_size) → energie po binech $P_\text{canon}[k]$ → vážený součet přes pásmo → $\sqrt{\ }$.

## Vzorec

$$L=\sqrt{\sum_k b_k\,P_\text{canon}[k]},\qquad b_k\in[0,1]\ \text{je podíl binu }k\text{ uvnitř }[F_\text{min},F_\text{max}]$$

$b_k$ popisují [Zlomkové biny](topic:overall_level/band) a proč je součet RMS, [Parseval](topic:overall_level/energy_parseval). Výsledek je hodnota Linear RMS v jednotce signálu; **Peak** zobrazí $\sqrt2\cdot L$ ([RMS vs. Peak](topic:shared/amplitude_format)).

## Výchozí hodnoty

| Nastavení | Výchozí |
|---|---|
| $F_\text{min}$ / $F_\text{max}$ | 10 Hz / Full Bandwidth (Nyquist souboru) |
| [Velikost FFT](topic:shared/fft_size) / [Okno](topic:shared/windows) | 4096 / Hanning |
| Tracking | RPM Tracked, Step 50 RPM, Sweep Up, Hystereze 10 RPM |
| Krok Free Run (Time) | 0,05 s |
| [Amplituda](topic:shared/amplitude_format) | RMS |
| Remove DC Offset | zapnuto ([Spektrum](topic:spectrum/intro)) |

Volba Linear / Power / PSD neexistuje ([Formát amplitudy](topic:shared/amplitude_format)): výsledek na ní nezávisí.

## Tracking

Tracking určuje, kde jsou vystředěny analyzované bloky. Pravidla (cílové RPM, interpolace, Sweep, Hystereze, čištění tacha) jsou stejná jako u Spektrogramu a jsou popsána jednou v [Tacho tracking](topic:shared/tracking). Specifické pro Overall Level:

- **RPM Tracked:** jeden bod na cílové otáčky; vyžaduje kanál tacha. Výchozí Step 50 RPM.
- **Free Run (Time):** blok každých *Step* sekund od začátku záznamu, tacho není třeba. Výchozí Step 0,05 s, minimum 0,001 s.
- **Sweep:** Up, Down nebo **Any (Both)**. Spektrogram Any odmítá, protože musí kreslit jeden pravidelný obraz; Overall Level je křivka bodů $(x,y)$, takže Any funguje a vrací body obou směrů.
- Středy bloků u začátku či konce záznamu se opraví o část doplněnou nulami (zisk nejvýše $\sqrt2$), takže první a poslední bod se nečtou nízko.

**Viz také:** [Pásmo](topic:overall_level/band), [Tacho tracking](topic:shared/tracking), [Order Tracking](topic:order_tracking/orders) (Overall Level + Residual)
