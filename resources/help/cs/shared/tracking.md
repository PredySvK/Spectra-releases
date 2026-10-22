### Tacho Tracking

Určuje, **kde** v záznamu jsou vystředěny analyzované bloky ([Spektrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro), [Overall Level](topic:overall_level/intro)). Nastavení jsou popsána po jednom: co dělá a co mění ve výsledcích.

**Výchozí:** Step 50 RPM (v časovém režimu 0,05 s), Ramp Up.

## Režim

- **Free Run (Time):** trigger každých *Step* sekund od začátku záznamu. Ignoruje otáčky. Osa X výsledku je čas a tachometr není potřeba.
- **RPM Tracked:** trigger v místě, kde otáčky protnou cílové RPM. Cíle jsou celé násobky kroku ($0, 50, 100, \dots$), ne posunuté podle začátku konkrétního záznamu, takže dva běhy lze porovnávat bod po bodu. Průsečík se určí lineární interpolací mezi dvěma vzorky. Vyžaduje kanál tacha. Osa X výsledku jsou otáčky.

![Triggery Free Run a RPM Tracked](tracking_triggers.png)

Stejný rozjezd a dojezd, rozřezané dvěma způsoby. **Free Run** (vlevo) dává trigger každou sekundu bez ohledu na otáčky: body jsou rovnoměrně v čase, ale nerovnoměrně v rpm a některé padnou do klidu. **RPM Tracked** (vpravo, Ramp Up) dává trigger pokaždé, když otáčky při rozjezdu protnou násobek kroku, takže body jsou rovnoměrně v rpm a dojezd i klid jsou vynechány.

## Step

Vzdálenost mezi triggery: sekundy ve Free Run, otáčky v RPM Tracked. Určuje, kolik bloků se řeže a jak daleko od sebe. Malý krok dává víc bodů a delší výpočet a sousední bloky se překrývají, takže sousední body nejsou nezávislé. Velký krok dává méně bodů s mezerami mezi bloky: úzký vrchol nebo rychlá změna mezi dvěma triggery se neuvidí. Délka bloku zůstává $N$; frekvenční rozlišení určuje [Velikost FFT](topic:shared/fft_size), ne krok.

![Táž křivka řádu řezaná s Step = 50 rpm a Step = 400 rpm](tracking_step.png)

Stejný rozjezd, řád 2, s úzkou rezonancí na 3500 ot/min. Při Step = 50 ot/min se vrchol zachytí; při Step = 400 ot/min na něj žádný blok nepadne a křivka kolem něj projde, jako by tam nebyl.

**Nízký step výsledek nezaostří.** Otáčky se během bloku dál mění, takže jeden blok pokrývá úsek otáček (tady 100 ot/min) a každý bod je průměrem přes tento úsek, ať je krok jakýkoli. Snížení kroku pod tento úsek jen přidá body, které se překrývají: křivka vypadá podrobněji, než je, a osa rpm slibuje rozlišení, které data nemají.

![Úzká rezonance řezaná s Step = 50 rpm a Step = 5 rpm](tracking_step_fine.png)

Totéž měření s rychlým rozjezdem (125 ot/min za sekundu) a rezonancí širokou jen 15 ot/min. Step = 50 rpm i Step = 5 rpm dávají stejný široký a nižší vrchol, protože jeden blok pokrývá 100 ot/min, mnohem víc než rezonance. Úsek zúží pomalejší rozjezd nebo kratší blok ([Velikost FFT](topic:shared/fft_size), za cenu frekvenčního rozlišení); nižší krok ne.

## Ramp

Up bere jen průsečíky směrem nahoru, Down jen směrem dolů. Šum při stání před rozjezdem a po doběhu se vynechá. Stejný stroj se chová jinak při zrychlování a při zpomalování, takže Up a Down dávají při stejných otáčkách různé křivky.

![Kterou část záznamu používá Ramp Up a Ramp Down](tracking_sweep.png)

Ramp vychází z **nejvyššího bodu záznamu**. **Up** vezme nárůst k tomuto bodu, od posledního okamžiku v klidu před ním (nebo od začátku záznamu, pokud klid nebyl). **Down** vezme pokles z tohoto bodu k prvnímu okamžiku v klidu po něm (nebo ke konci záznamu). Teprve v tomto úseku se hledají průchody cíli. Menší rozjezd nebo dojezd jinde v záznamu se nepoužije: jinak by se některé otáčky protínaly dvakrát.

Hraniční případy:

- Záznam jen s dojezdem nedá pro Ramp Up žádné triggery, záznam jen s rozjezdem je nedá pro Ramp Down.
- Pokud dojezd přijde první a vyšší rozjezd až později, Ramp Down nic nenajde: nejvyšší bod je na konci a dřívější dojezd leží před ním.
- Tacho, které nikdy nespadne na 0 (např. volnoběh 800 ot/min), se neořezává: Up začne od prvního vzorku a triggery začínají prvním cílem na nejnižších otáčkách nebo nad nimi.

## Tracking range

**Min [RPM]** a **Max [RPM]** vedle kroku zúží rampu na otáčky, které vás zajímají. Prázdná pole znamenají auto: 0 ot/min a nejvyšší otáčky záznamu, přesně rampa popsaná výše. Ve Free Run jsou stejná pole **Start [s]** a **End [s]** (viz níže).

- **Up** začíná **posledním okamžikem, kdy jsou otáčky na Min nebo pod ním**, před nejvyššími otáčkami záznamu, a končí na nejvyšších otáčkách. Krátké roztočení nad Min a zpět před skutečným rozjezdem se proto za rozjezd nebere a klid i neklidný začátek pod Min nedají žádné bloky.
- **Down** je zrcadlový: začíná na nejvyšších otáčkách a končí prvním okamžikem na Min nebo pod ním po nich.
- Cíle nad **Max** se zahodí. Max pod nejvyššími otáčkami nevybere dřívější běh: rampa se stále hledá kolem nejvyšších otáček celého záznamu.
- Cíle zůstávají na **celých násobcích kroku**: Min 1 030 ot/min se Step 50 rpm dá první bod na 1 050 ot/min, takže dvě měření analyzovaná s různým rozsahem stále sdílejí body otáček.
- Záznam, který začíná už nad Min, se použije od začátku.
- Běh s opačným směrem otáčení bere rozsah v kladných ot/min, stejně jako jeho osa výsledku.
- Min na Max nebo nad ním se odmítne už při zadávání. Rozsah, kterého měření nikdy nedosáhne (Min 40 000 ot/min při běhu do 35 000 ot/min), skončí hlášením se jménem měření. V [dávce](topic:batch/intro) se takové měření zapíše jako problém a ostatní měření doběhnou.
- Záložky Spectrogram, Order Tracking a Overall Level mají každá vlastní rozsah. **Calculate & Save Data** použije rozsah záložky a blok [workflow](topic:workflow/intro) ho má v Properties jako *Rpm Min* / *Rpm Max* (prázdné = auto). Křivky Overall Level + Residual v Order Trackingu používají rozsah řádů.

### Start a End ve Free Run

Ve Free Run mají obě pole popis **Start [s]** a **End [s]** a zúží záznam v čase. Prázdná pole znamenají celý záznam, přesně bloky bez rozsahu.

- Časy jsou ty z **časové osy**, jako v grafu časového signálu: záznam, který začíná na 12,3 s, analyzovaný od 15 s začne 2,7 s od svého začátku.
- **První blok leží přesně na Start**, další po kroku; poslední na End nebo před ním. Na rozdíl od cílů v otáčkách časová mřížka neleží na násobcích kroku: Start 12,3 s se Step 0,5 s dá 12,3, 12,8, 13,3 s … Start před začátkem záznamu si mřížku ponechá: Start 10 s se Step 0,5 s u záznamu od 12,3 s dá první blok na 12,5 s.
- Časový rozsah a rozsah otáček se pamatují zvlášť: přepnutí Tracking Mode ukáže rozsah daného režimu, takže hodnota v ot/min se nikdy nepřečte jako sekundy. Každá záložka má vlastní dvojici a blok [workflow](topic:workflow/intro) ji má jako *Time Start* / *Time End*.
- Start na End nebo za ním se odmítne už při zadávání. Rozsah mimo záznam (Start 40 s u záznamu, který končí na 30 s) skončí hlášením se jménem měření; v dávce ostatní měření doběhnou.

## Jeden blok na otáčky: první průchod

Každé cílové otáčky dostanou právě jeden blok, z **prvního okamžiku**, kdy je otáčky ve směru rampy dosáhnou. Pozdější průchod stejnými otáčkami se ignoruje. Osa otáček výsledku má proto každé otáčky jednou a rovnoměrně rozložené.

![Kolísající a klesající plató: jeden trigger na otáčky](tracking_first_crossing.png)

Dva rozjezdy s plató na 300 ot/min, Step = 50 rpm. Vlevo otáčky kolísají kolem cíle: 300 ot/min protnou čtyřikrát, ale blok dá jen první průchod. Vpravo plató klesne pod nastavenou hodnotu a další rampa protne 300 ot/min znovu; ani tento blok se neopakuje. Totéž platí pro rozjezd, který uprostřed poklesne a vrátí se: otáčky, kterými projde znovu, si ponechají bloky z doby před poklesem. Ramp Down je zrcadlový: první okamžik, kdy otáčky klesnou na každý cíl.

## Čištění tacha

Tacho se nejdřív vyčistí: vzorky strmější než 200 000 RPM/s a nekonečné či chybějící hodnoty se nahradí interpolací, poté se použije 50ms klouzavý průměr. Tacho se zápornými hodnotami se převrátí a záporné otáčky se ořežou na 0.

Průměr otáčky vyhladí, takže otáčky čtené v triggeru jsou vyhlazené; změna rychlejší než 50 ms se rozmaže.

![Co udělá klouzavý průměr 50 ms s krátkým poklesem a se skokem](tracking_cleaning.png)

Dvě rychlé události v surovém tachu (šedě) a vyčištěné otáčky, které triggery používají (modře). Průměrování odstraní šum, ale změnu také rozprostře přes okno 50 ms. Skok o 200 ot/min za 5 ms se změní na rampu dlouhou 50 ms. Pokles dlouhý 30 ms a hluboký 200 ot/min se stane mělčím (tady asi 140 ot/min) a širším. Pomalý rozjezd nebo dojezd to neovlivní: průměr přímé rampy je tatáž rampa.
