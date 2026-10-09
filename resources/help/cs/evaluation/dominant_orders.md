## 📊 Vyhodnocení: Dominant orders (dominantní řády)

<b>Dominant orders</b> najde na jednom <b>spektrogramu sledovaném proti otáčkám</b> N řádů s nejvyšší maximální amplitudou kdekoli podél jejich řádové čáry -- aniž byste je zadávali ručně. Každý řádek tabulky je jeden řád zobrazený na setiny (např. 4,79) s amplitudou a otáčkami (rpm), při kterých ta amplituda leží. Srovnejte s [Top-N maxima](topic:evaluation/topn_maxima) a [Typed orders](topic:evaluation/typed_orders).

![](dominant_orders_order_map.png)

<i>Nahoře: řádová mapa syntetického rozběhu -- řád 4,79, jeho harmonické 9,58 a 14,37 a rezonance pevně na 1800 Hz. Dole: křivka maximální amplitudy proti řádu. Červené značky: nalezené Dominant orders s N = 3. Slabá diagonální stopa v mapě je rezonance -- s výchozím N = 10 by některé její skvrny obsadily zbylé řádky (viz Omezení).</i>

### Krok za krokem

1. <b>Řádová mapa:</b> každý řádek spektrogramu (jeden krok otáček) se přepočítá z Hz na společnou řádovou mřížku, o = f&middot;60/rpm. Čára, která sleduje otáčky hřídele, pak leží v každém řádku na stejném místě.
1. <b>Maximum přes otáčky:</b> pro každý řád mřížky nejvyšší amplituda, kterou tam má kterýkoli řádek. Výsledek je jedna křivka: maximální amplituda proti řádu.
1. <b>Kandidáti:</b> Local maxima této křivky přesně stejným pravidlem jako u Top-N maxima -- minimální vzdálenost (zde v řádech) a minimální prominence v dB -- nejvyšší první.
1. <b>Zpřesnění:</b> každý kandidát se posune na energetické těžiště &Sigma;o&middot;P / &Sigma;P mapy sečtené přes všechny řádky, jen v rámci vlastního hrbu (po údolí na každé straně, nejvýše polovinu min. vzdálenosti daleko) a počítá se jen energie nad vyšším ze dvou den údolí, aby ho šikmé pozadí netáhlo do strany; pak se zaokrouhlí na setiny.
1. <b>Hodnota a otáčky:</b> řádový řez na zaokrouhleném řádu, přečtený ze stejného spektrogramu -- přesně to, co pro ten řád dá <b>Typed orders</b>. Nejvýše N řádků seřazených podle této amplitudy.

### Proč je řád rozmazaný

- <b>Šířka binu v řádech:</b> při otáčkách rpm pokryje jeden FFT bin &Delta;f právě &Delta;o = &Delta;f&middot;60/rpm řádů. Při 51,2 kHz a FFT 4096 je to 0,25 řádu při 3 000 rpm, ale 0,025 při 30 000 rpm.
- <b>Hlavní hrb okna:</b> okno rozprostře i čistý sinusový signál do několika binů (Hann asi 4).
- <b>Drift:</b> otáčky se mění během jednoho framu a řád sám může fyzikálně driftovat -- prokluz řemenu může z 4,79 udělat 4,77 při nízké a 4,81 při vysoké zátěži.

Žádný jednotlivý řádek tedy řád na setiny neurčí; <b>těžiště</b> spojí mnoho řádků do jednoho čísla. Řádky příliš pomalé na to, aby oddělily dva řády vzdálené o min. vzdálenost (hlavní hrb okna v řádech širší než min. vzdálenost), se do mapy vůbec nezapočítají -- jen by ji rozmazaly.

### Proč se hodnota rovná Max řádového řezu

Bod mapy je energie jednoho binu na rozmazaném hrbu -- menší než to, co řádový řez integruje přes celé řádové pásmo. Jeho zobrazení by pro tutéž věc dalo dvě různá čísla. Hodnota proto pochází z řádového řezu: rovná se <b>[Typed orders](topic:evaluation/typed_orders)</b> na zobrazeném řádu a <b>Max</b> [Order Trackingu](topic:order_tracking/intro) se stejným [FFT](topic:shared/fft_size), [oknem](topic:shared/windows), krokem a šířkou pásma. Zadejte 4,79 do Typed orders a dostanete stejnou amplitudu i otáčky.

### Parametry

- <b>Orders (rozsah řádů):</b> nejnižší a nejvyšší prohledávaný řád. Výchozí 0,5 &ndash; 50.
- <b>N:</b> kolik Dominant orders nejvýše. Výchozí 10. Méně kandidátů dá méně řádků -- nikdy se nevyplňuje.
- <b>Min distance (min. vzdálenost):</b> dva Dominant orders leží aspoň tolik řádů od sebe, takže sousedé jedné rozmazané čáry (4,78 / 4,79 / 4,80) jsou jeden řádek, ne tři. Rozhoduje také, které řádky spektrogramu jsou dost ostré, aby se započítaly (viz výše). Výchozí 0,5.
- <b>Min prominence:</b> o kolik musí kandidát vyčnívat nad údolí k vyššímu sousedovi na křivce maximální amplitudy proti řádu, v amplitudových dB -- pravidlo Top-N maxima. Výchozí 3 dB.
- <b>Order width (šířka pásma):</b> řádové pásmo &Delta;O, přes které se integruje hodnota, stejný význam a výchozí hodnota (0,2) jako u Typed orders a Order Trackingu. Vlastní parametr vyhodnocení, nečtený z ribbonu.
- <b>Grid (mřížka):</b> rozestup společné řádové mřížky. Výchozí 0,01. Hrubší je rychlejší; těžiště řád stále zpřesní mezi body mřížky.

### Omezení

- <b>Rezonance s pevnou frekvencí:</b> energie, která zůstává na jedné frekvenci f<sub>r</sub>, zatímco se mění otáčky, padne v každém řádku na jiný řád (f<sub>r</sub>&middot;60/rpm). V mapě je to široký hrb nebo stopa skvrn, ne čára -- a může v tabulce obsadit řádek. Detektor, který obojí rozliší, zatím vědomě není.
- <b>Spektrogram proti času:</b> nemá řády -- žádné řádky, karta zobrazí obvyklou hlášku.
- <b>Amplituda, jednotky, třídění, kopírování/export, Columns&hellip;:</b> stejné jako u [Max](topic:evaluation/max). Formát zůstává vypnutý -- řádek je lineární amplituda, stejně jako u [Typed orders](topic:evaluation/typed_orders).
