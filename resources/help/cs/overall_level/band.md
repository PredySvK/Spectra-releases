### Frekvenční pásmo a Full Bandwidth

- **F min, F max:** integrační pásmo. Výchozí $F_\text{min}=10$ Hz. $F_\text{max}$ musí být větší než $F_\text{min}$, jinak se výpočet odmítne.
- **Full Bandwidth** (výchozí zapnuto): $F_\text{max}$ je vlastní Nyquistova frekvence souboru $f_s/2$. Ukládá se jako záměr, ne jako číslo, takže soubory s různými vzorkovacími frekvencemi sdílejí jednu sadu výsledků. Je to skutečný Nyquistův limit, ne předpokládaná analogová šířka pásma $f_s/2{,}56$, kterou soubory nezaznamenávají.
- **F max nad Nyquistem:** zadané $F_\text{max}$ se oříznou na Nyquist daného souboru a efektivní pásmo se zobrazí v legendě, takže dávka přes soubory se smíšenými vzorkovacími frekvencemi proběhne.
- **Prázdné pásmo:** pokud $F_\text{min}\ge f_s/2$, pásmo nic neobsahuje. Pro daný soubor je to chyba, ne nulová křivka: zapíše se do logu, vynechá z přidání do overlay a v dávce se označí jako „partial“.

## Zlomkové vážení binů

Bin $k$ je vystředěn na $f_k=k\,\Delta f$ a zabírá $\pm\Delta f/2$. Jeho váha je podíl tohoto rozsahu uvnitř pásma:

$$b_k=\operatorname{clip}\!\left(\frac{\min(F_\text{max},\,f_k+\Delta f/2)-\max(F_\text{min},\,f_k-\Delta f/2)}{\Delta f},\ 0,\ 1\right)$$

Bin zcela uvnitř má $b_k=1$, bin protnutý hranou se počítá poměrně a bin vně 0. Příklad: $\Delta f=6{,}25$ Hz a $F_\text{min}=10$ Hz. Bin na 12,5 Hz zabírá 9,375 až 15,625 Hz, takže $b=(15{,}625-10)/6{,}25=0{,}9$, a bin na 6,25 Hz zabírá 3,125 až 9,375 Hz a počítá se 0.

Tvrdé „uvnitř/vně“ by při přechodu hrany přeskočilo celý bin mezi 0 a 100 %, čímž by v odečtu vzniklo schodiště, ačkoli se obsah pásma mění plynule. Stejné váhy používá [Band RMS](topic:tools/band_rms), [Overall Level](topic:overall_level/intro) i pásma řádů v [Order Tracking](topic:order_tracking/orders), takže jejich čísla souhlasí.


## Legenda a identifikace pásma

- **Výchozí pásmo** ($F_\text{min}$ 10 Hz a Full Bandwidth): pásmo se vynechá, např. `OAL [soubor] kanál [jednotka RMS]`.
- **Jakékoli jiné pásmo:** zobrazí se *efektivní* pásmo po oříznutí na Nyquist souboru: `OAL 100–12800 Hz [soubor] kanál [jednotka RMS]`.
- **Residual** (z [Order Tracking](topic:order_tracking/orders)) se čte `Residual …` a má vždy výchozí pásmo.

Pravidlo je jediná funkce, takže živé křivky, srovnávací overlay i křivky z [Result Pool](topic:results/intro) se jmenují stejně. Dvě křivky patří do téže sady výsledků, když je jejich *požadované* pásmo stejné, proto soubory s Full Bandwidth při různých vzorkovacích frekvencích sdílejí jednu sadu.
