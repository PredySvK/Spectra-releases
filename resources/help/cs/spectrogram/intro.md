## 🎛️ Spectrogram 2D

Tento modul vytváří časově-frekvenční nebo RPM-frekvenční mapu signálu. Každý sloupec je jeden oknovaný blok FFT, takže mapa ukazuje, jak se spektrální složení mění s časem nebo s otáčkami.

![Záložka Spectrogram 2D s nastavením a spektrogramem](module_spectrogram.cs.png)

## Kde se bloky řežou

Blok o $N$ vzorcích je umístěn **se středem v každém triggeru**; neexistuje nastavení překryvu ani průměrování. Rozestup triggerů (*Step*) rozhoduje, zda se sousední bloky překrývají, nebo mezi nimi zůstanou mezery. Triggery vznikají podle [Tacho trackingu](topic:shared/tracking) (viz též [Order Tracking](topic:order_tracking/intro) pro tatáž data čtená jako řády):

- **RPM Tracked:** trigger v každém násobku kroku v RPM (výchozí **50 RPM**), kde tacho tuto hodnotu protne ve zvoleném směru (Up nebo Down; Any se odmítne, protože rozjezd s doběhem protíná každé otáčky dvakrát). Osa je RPM.
- **Free Run (Time):** trigger každých Step sekund od začátku záznamu (výchozí **0,05 s**). Osa je čas. Tacho není potřeba.

## Výpočet jednoho bloku

Pro trigger $i$ ve vzorku $s_i$ (zaokrouhleném na nejbližší vzorek) je blok $x[s_i-\lfloor N/2\rfloor+n]$, $n=0,\dots,N-1$:

$$X_i[k]=\sum_{n=0}^{N-1} w[n]\,x\bigl[s_i-\lfloor N/2\rfloor+n\bigr]\,e^{-j2\pi kn/N},\qquad P_i[k]=g_i\,\frac{c_k\,\lvert X_i[k]\rvert^2}{N\sum_n w[n]^2}$$

Je to stejná $P_\text{canon}$ jako ve [Spektru](topic:spectrum/intro); činitel $g_i$ vysvětluje další část. Výsledek se pak zobrazí jako Linear, Power nebo PSD, RMS nebo Peak s lineární nebo dB (Log) barevnou škálou: viz [Formát amplitudy](topic:shared/amplitude_format).

## Bloky na okraji záznamu

Trigger blíže než $N/2$ ke kterémukoli konci záznamu nechá část svého bloku prázdnou (nuly). Program takový blok vrátí na úroveň, kterou by stejný obsah měl uvnitř záznamu:

$$g_i=\frac{\sum_{n} w[n]^2}{\sum_{n\ \text{uvnitř záznamu}} w[n]^2}$$

Pro celý blok je $g_i=1$. Protože trigger leží vždy uvnitř záznamu, je blok pokryt alespoň z poloviny a $g_i\le 2$ (amplituda $\le\sqrt2$).

## Výchozí hodnoty

| Nastavení | Výchozí |
|---|---|
| Velikost FFT / Okno | 4096 / Hanning |
| Formát / Amplituda / Barevná škála | Linear / RMS / Linear |
| Režim trackingu | RPM Tracked |
| Step | 50 RPM (časový režim: 0,05 s) |
| Směr / Hystereze | Up / 10 RPM |
| Remove DC Offset | zapnuto (viz [Spektrum](topic:spectrum/intro)) |

Záznam musí mít alespoň $N$ vzorků. Data mapy pocházejí z [surového signálu](topic:raw_data/intro) kanálu.

**Viz také:** [Velikost FFT](topic:shared/fft_size), [Okna](topic:shared/windows), [Formát amplitudy](topic:shared/amplitude_format), [Tacho tracking](topic:shared/tracking)
