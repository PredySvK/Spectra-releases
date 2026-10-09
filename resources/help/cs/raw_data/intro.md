# Surová data

**Časový signál** je kanál přesně tak, jak byl přečten ze souboru: bez odečtení DC, bez [okna](topic:shared/windows), bez filtru.
## Otevření časového signálu

Když je aktivní záložka *Project*, dvakrát klikněte na kanál v [Data Poolu](topic:data_management/intro). Otevře se v nové záložce workspace s časem na ose X. Více vybraných kanálů se otevře jako jeden [graf](topic:graphs/intro); kanál přetažený na otevřený časový graf se do něj přidá.

![Surový kanál jako časový signál](raw_data.cs.png)

Na záložce analýzy ([Overall Level](topic:overall_level/intro), [Order Tracking](topic:order_tracking/intro), [Spectrogram 2D](topic:spectrogram/intro), [Spectrum 1D](topic:spectrum/intro)) stejný dvojklik místo toho spočítá danou analýzu.

## Osy

| Osa | Co ukazuje |
|---|---|
| X | čas v s, z časové základny uložené v souboru. Jednotka osy X čas nikdy nepřepočítává. |
| Y | hodnoty kanálu v jeho jednotce, převedené na zvolenou zobrazovací jednotku: $y' = k\,y$ ([Jednotky](topic:units/intro)) |

Vzorkovací frekvence, kterou používá každá analýza, je $f_s = 1/\Delta t$, krok této časové základny. Kanál z jiné domény než první (mikrofon vedle akcelerometru) dostane vlastní pravou osu Y.

## Dlouhé záznamy

Křivka s více než **20 000 body** se kreslí jen v zobrazeném úseku a prořeďuje se na rozlišení obrazovky. Jde jen o zobrazení: po přiblížení uvidíte jednotlivé vzorky. Každá analýza vždy čte všechny vzorky.

## Kanál tacho

Tacho se otevře jako každý jiný kanál a ukazuje otáčky v jednotce zapsané v souboru. Analýzy si je samy převedou na rpm.

## Co zkontrolovat

| Hledejte | Proč na tom záleží |
|---|---|
| ploché vrcholy na stejné úrovni | senzor nebo záznamník saturoval; spektrum získá falešné harmonické |
| úroveň daleko od očekávané | špatná jednotka kanálu -- opravte ji přes **Fix Unit** ([Jednotky](topic:units/intro)) |
| pomalý drift nebo velký offset | DC; analýzy střední hodnotu odečtou (**Remove DC Offset**), časový graf ne |
| špičky nebo výpadky | jednotlivé vadné vzorky se rozlijí do všech frekvencí bloku ([FFT](topic:shared/fft_size)), do kterého padnou |
| zašuměné nebo přerušované tacho | na něm závisí [order tracking](topic:order_tracking/intro) i každá osa otáček ([Tracking](topic:shared/tracking)) |
