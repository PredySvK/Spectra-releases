### Tacho Tracking

Určuje, **kde** v záznamu jsou vystředěny analyzované bloky ([Spektrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro), [Overall Level](topic:overall_level/intro)). Nastavení jsou popsána po jednom: co dělá a co mění ve výsledcích.

**Výchozí:** Step 50 RPM (v časovém režimu 0,05 s), Sweep Up, Hystereze 10 RPM.

## Režim

- **Free Run (Time):** trigger každých *Step* sekund od začátku záznamu. Ignoruje otáčky. Osa X výsledku je čas a tachometr není potřeba.
- **RPM Tracked:** trigger v místě, kde otáčky protnou cílové RPM. Cíle jsou celé násobky kroku ($0, 50, 100, \dots$), ne posunuté podle začátku konkrétního záznamu, takže dva běhy lze porovnávat bod po bodu. Průsečík se určí lineární interpolací mezi dvěma vzorky. Vyžaduje kanál tacha. Osa X výsledku jsou otáčky.

![Triggery Free Run a RPM Tracked](tracking_triggers.png)

Stejný rozjezd a dojezd, rozřezané dvěma způsoby. **Free Run** (vlevo) dává trigger každou sekundu bez ohledu na otáčky: body jsou rovnoměrně v čase, ale nerovnoměrně v rpm a některé padnou do klidu. **RPM Tracked** (vpravo, Sweep Up) dává trigger pokaždé, když otáčky při rozjezdu protnou násobek kroku, takže body jsou rovnoměrně v rpm a dojezd i klid jsou vynechány.

## Step

Vzdálenost mezi triggery: sekundy ve Free Run, otáčky v RPM Tracked. Určuje, kolik bloků se řeže a jak daleko od sebe. Malý krok dává víc bodů a delší výpočet a sousední bloky se překrývají, takže sousední body nejsou nezávislé. Velký krok dává méně bodů s mezerami mezi bloky: úzký vrchol nebo rychlá změna mezi dvěma triggery se neuvidí. Délka bloku zůstává $N$; frekvenční rozlišení určuje [Velikost FFT](topic:shared/fft_size), ne krok.

![Táž křivka řádu řezaná s Step = 50 rpm a Step = 400 rpm](tracking_step.png)

Stejný rozjezd, řád 2, s úzkou rezonancí na 3500 ot/min. Při Step = 50 ot/min se vrchol zachytí; při Step = 400 ot/min na něj žádný blok nepadne a křivka kolem něj projde, jako by tam nebyl.

**Nízký step výsledek nezaostří.** Otáčky se během bloku dál mění, takže jeden blok pokrývá úsek otáček (tady 100 ot/min) a každý bod je průměrem přes tento úsek, ať je krok jakýkoli. Snížení kroku pod tento úsek jen přidá body, které se překrývají: křivka vypadá podrobněji, než je, a osa rpm slibuje rozlišení, které data nemají.

![Úzká rezonance řezaná s Step = 50 rpm a Step = 5 rpm](tracking_step_fine.png)

Totéž měření s rychlým rozjezdem (125 ot/min za sekundu) a rezonancí širokou jen 15 ot/min. Step = 50 rpm i Step = 5 rpm dávají stejný široký a nižší vrchol, protože jeden blok pokrývá 100 ot/min, mnohem víc než rezonance. Úsek zúží pomalejší rozjezd nebo kratší blok ([Velikost FFT](topic:shared/fft_size), za cenu frekvenčního rozlišení); nižší krok ne.

## Sweep

Up bere jen průsečíky směrem nahoru, Down jen směrem dolů. Šum při stání před rozjezdem a po doběhu se vynechá. Stejný stroj se chová jinak při zrychlování a při zpomalování, takže Up a Down dávají při stejných otáčkách různé křivky.

![Kterou část záznamu používá Sweep Up a Sweep Down](tracking_sweep.png)

Sweep vychází z **nejvyššího bodu záznamu**. **Up** vezme nárůst k tomuto bodu, od posledního okamžiku v klidu před ním (nebo od začátku záznamu, pokud klid nebyl). **Down** vezme pokles z tohoto bodu k prvnímu okamžiku v klidu po něm (nebo ke konci záznamu). Teprve v tomto úseku se hledají průchody cíli. Menší rozjezd nebo dojezd jinde v záznamu se nepoužije: jinak by se některé otáčky protínaly dvakrát.

Hraniční případy:

- Záznam jen s dojezdem nedá pro Sweep Up žádné triggery, záznam jen s rozjezdem je nedá pro Sweep Down.
- Pokud dojezd přijde první a vyšší rozjezd až později, Sweep Down nic nenajde: nejvyšší bod je na konci a dřívější dojezd leží před ním.
- Tacho, které nikdy nespadne na 0 (např. volnoběh 800 ot/min), se neořezává: Up začne od prvního vzorku a triggery začínají prvním cílem na nejnižších otáčkách nebo nad nimi.

## Hystereze

Ochrana proti otáčkám, které kolem cíle kmitají. Po triggeru na cíli se další trigger na *stejném* cíli přijme, až když otáčky opustily pásmo kolem něj na opačné straně. Při Up sweepu to znamená pokles pod cíl − hystereze. Příklad: při 10 RPM se trigger na 1000 RPM nezopakuje, dokud otáčky neklesly pod 990 RPM a znovu neprotly 1000.

Když otáčky kolísají kolem cíle, příliš malá hodnota dá několik bloků na téměř stejných otáčkách, což se projeví zdvojenými body a zubatou křivkou. Větší hodnota nechá jen jeden. Příliš velká zahodí i skutečný pokles a návrat, který je menší než ona.

![Totéž kolísání otáček s Hystereze = 2 rpm a 10 rpm](tracking_hysteresis.png)

Otáčky kolísají o ±7 ot/min kolem cíle 300 ot/min. Při Hystereze = 2 rpm každé kolísání klesne pod oranžovou čáru (cíl − hystereze) a vrátí se, takže se každý návrat počítá znovu: pět triggerů na téměř stejných otáčkách. Při Hystereze = 10 rpm otáčky nikdy neklesnou pod 290 ot/min, takže první trigger platí a návraty (prázdné kroužky) jsou odmítnuty: jeden trigger, jeden blok.

## Čištění tacha

Tacho se nejdřív vyčistí: vzorky strmější než 200 000 RPM/s a nekonečné či chybějící hodnoty se nahradí interpolací, poté se použije 50ms klouzavý průměr. Tacho se zápornými hodnotami se převrátí a záporné otáčky se ořežou na 0.

Průměr otáčky vyhladí, takže otáčky čtené v triggeru jsou vyhlazené; změna rychlejší než 50 ms se rozmaže.

![Co udělá klouzavý průměr 50 ms s krátkým poklesem a se skokem](tracking_cleaning.png)

Dvě rychlé události v surovém tachu (šedě) a vyčištěné otáčky, které triggery používají (modře). Průměrování odstraní šum, ale změnu také rozprostře přes okno 50 ms. Skok o 200 ot/min za 5 ms se změní na rampu dlouhou 50 ms. Pokles dlouhý 30 ms a hluboký 200 ot/min se stane mělčím (tady asi 140 ot/min) a širším. Pomalý rozjezd nebo dojezd to neovlivní: průměr přímé rampy je tatáž rampa.
