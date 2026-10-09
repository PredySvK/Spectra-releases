# Result Pool

**Result Pool** zobrazuje uložené sady výsledků v aktuálním projektu. Sada obsahuje vypočtené křivky v [projektové mezipaměti výsledků](topic:general/projects). Načtením se uložené křivky přidají do aktivního grafu, kde je lze porovnat s ostatními křivkami; analýza se znovu nepočítá.

## Výběr grafu a načtení sad

Vyberte [kartu grafu](topic:graphs/intro), kterou chcete použít, a otevřete Result Pool v Exploreru. Záhlaví uvádí graf, do kterého se zaškrtnuté sady načtou. Zaškrtnutím sady ji načtete; zaškrtnutím nadpisu **Result Kind** načtete všechny dostupné sady v této skupině. Částečně zaškrtnutý nadpis znamená, že je v tomto grafu načtena jen část sad.

Ovládání Result Pool je dostupné pouze při aktivním běžném grafu. Při aktivním spektrogramu nebo Home Workspace zůstane seznam viditelný, ale bude neaktivní. [Spektrogram](topic:spectrogram/intro) zobrazuje jedinou barevnou mapu, nikoli seznam porovnávaných křivek. Do grafu lze načíst jen druhy výsledků tvořené křivkami; ostatní se přeskočí s upozorněním.

Čtení z mezipaměti probíhá na pozadí jako úloha **Load Result Sets** ([Jobs](topic:jobs/intro)). Sada zůstane zaškrtnutá, i když se její čtení teprve připravuje; opětovné zaškrtnutí nespustí duplicitní čtení. Během načítání ji můžete odškrtnout a čekající výsledek se do grafu nepřidá. Pokud čtení selže nebo úlohu zrušíte v Jobs, čekající zaškrtnutí se zruší. Jestliže by sada načetla více než výchozích 500 křivek, aplikace se před čtením zeptá **Load many curves?**; pokračujte volbou **Yes**.

Sada výsledků řádů může pro jeden zdrojový kanál načíst více křivek. Křivka, která už v grafu je z živého výpočtu, se připojí k sadě a nevykreslí se podruhé.

## Označení Parameter Set

Každý řádek sady uvádí její název, číslo **Parameter Set** a počet zdrojů. Parameter Set (použitelný jako [sloupec filtru](topic:filtering/intro)) sdružuje sady se stejným druhem výsledku a nastavením výpočtu. Čísla se řídí prvním výskytem odlišného výpočtu v seznamu sad projektu; nejsou to trvalé identifikátory. Seznam řádů, verze algoritmu ani volby pouze pro zobrazení nevytvářejí samostatné Parameter Set. Pomlčka znamená, že sada není přiřazena k Parameter Set.

## Odebrání z grafu bez smazání

Odškrtnutím sady nebo jejího nadpisu Result Kind odstraníte křivky dané sady z aktivního grafu. Změní se pouze obsah grafu: uložená sada se nesmaže z projektu ani se neodstraní její soubory mezipaměti. Křivky, které k odškrtnuté sadě nepatří, zůstanou v grafu. Živá křivka připojená k této sadě se odstraní spolu s ní. Uložená sada zůstane v Result Poolu a její soubory mezipaměti se nezmění.

## Chybějící soubory výsledků

Pokud projekt sadu stále eviduje, ale její soubor mezipaměti chybí, řádek se zobrazí šedě s varovnou ikonou a nelze jej zaškrtnout. Nápověda po najetí myší vysvětluje, že soubor chybí. Křivky znovu zpřístupníte novým výpočtem a uložením sady.

## Uložení a obnovení

Uložte projekt, aby se zachovalo, které sady jsou načtené v jednotlivých otevřených grafech. Při opětovném otevření projektu se obnoví karty grafů i zaškrtnuté sady; křivky se znovu načtou z uložené mezipaměti. Uložená data sady zůstávají v Result Pool bez ohledu na to, zda jsou právě načtena do grafu.

Viz také [Compute Batch](topic:batch/intro), [Grafy](topic:graphs/intro) a [Projekty a mezipaměť výsledků](topic:general/projects).
