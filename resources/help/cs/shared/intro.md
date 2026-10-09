# Společná nastavení analýz

[Spektrum](topic:spectrum/intro), [Spektrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) a [Overall Level](topic:overall_level/intro) dělí signál na bloky, každý blok oknují, provedou FFT a výsledek přeškálují. Tyto stránky popisují nastavení, která mají společná.

| Nastavení | Stránka | Výchozí |
|---|---|---|
| Velikost FFT $N$ | [Velikost FFT](topic:shared/fft_size) | 4096 |
| Okno | [Okna](topic:shared/windows) | Hanning |
| Formát a amplituda | [Formát amplitudy](topic:shared/amplitude_format) | Linear, RMS |
| Krok, směr, hystereze | [Tacho tracking](topic:shared/tracking) | 50 RPM, Up, 10 RPM |
| Remove DC Offset | [Remove DC Offset](topic:shared/remove_dc) | zapnuto |

Výsledek se ukládá jako **energie po binech** $P_\text{canon}$ (čtverec jednotky, např. g²). Linear, Power, PSD, RMS a Peak jsou pohledy, které se z ní počítají až při zobrazení, takže jejich přepnutí FFT nepočítá znovu.
