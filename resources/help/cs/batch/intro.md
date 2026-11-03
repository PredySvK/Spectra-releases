# Výpočet sady výsledků pro více měření

Tlačítko **Compute Batch** na konci každé analytické záložky otevře dialog **Compute Result Set**. V něm zvolíte rozsah kanálů a u *Order Tracking* také řády k výpočtu. Výpočet pak použije aktuální nastavení dané analytické záložky na měření právě načtená v *[Data Poolu](topic:import/intro)* a křivky uloží jako pojmenovanou sadu výsledků.

## Nejdříve vyberte měření

Na záložce *Project* použijte **Add Data Directory** a přidejte složku do Data Poolu. Část *Input Data* v dialogu pouze uvádí počet načtených měření; neumožňuje vybrat složku ani uložený výběr měření. Dávka použije aktuálně načtená měření a jejich odpovídající zdrojové soubory. Chcete-li zpracovat menší dávku, načtěte nejprve do Data Poolu jen požadovaná měření. [Uložené výběry](topic:selections/intro) v Exploreru nejsou vstupem tohoto tlačítka; rozsah této dávky neomezují.

Před zápisem výsledků musí být projekt uložený. Pokud je třeba, aplikace nabídne uložení; jeho zrušením se zruší i dávka. Před výpočtem aplikace zaregistruje složky Data Poolu, které ještě nejsou v projektu. Pokud není načtené žádné měření nebo zvolený typ neodpovídá žádným kanálům, výpočet se přeskočí a důvod se zapíše do System Logu.

## Nastavte kanály a řády

Dialog počítá celý Data Pool, bez ohledu na to, co zobrazuje Filtr. V části **Data Pool channels** zvolte **All** (akcelerometry a mikrofony), **Accelerometer** nebo **Microphone**. Tacho kanál se nikdy nepočítá jako kanál; jako otáčky se dál používá v Order Tracking a Overall Level. Pod volbou dialog ukáže, kolik měření a kanálů se spočítá; je-li to nula, tlačítko **Compute** je vypnuté.

Výchozí volba je **All**. Volba se pamatuje samostatně pro každou analytickou záložku a uloží se po stisknutí **Compute**, nikoli pouhým otevřením dialogu. Název result setu nese typ, například `Spectrum_4096_Accelerometer`; u **All** zůstává `…_All_Channels`.

Pole **Orders to compute & save** se zobrazuje pouze u *Order Tracking*. Zadejte kladné [řády](topic:order_tracking/orders) oddělené čárkami nebo středníky; desetinná část používá tečku, například `1, 2, 4.5`. Pole předvyplní naposledy uložené dávkové řády, případně živé nastavení **Orders** v Order Tracking, pokud dávkové řády ještě uložené nejsou. Neplatný nebo prázdný vstup tlačítko **Compute** vypne. Ostatní analytické záložky používají svá aktuální nastavení v ribbonu a toto pole nezobrazují.

## Pojmenujte a spusťte sadu

Volitelně zadejte **Result set name**. Náhled ukáže upravený název použitelný jako název složky; pokud po úpravě nezbývá žádný platný znak, tlačítko **Compute** se vypne. Nechte pole prázdné a aplikace vytvoří název z nastavení analýzy a rozsahu kanálů. Pokud již sada se zadaným názvem existuje, aplikace přidá příponu, například `_2`, místo tichého přepsání.

Stisknutím **Compute** spustíte výpočet. Tlačítko **Cancel** v dialogu jej zavře bez spuštění výpočtu a bez uložení právě zvolených možností. Pokud již existuje sada se zcela shodným nastavením analýzy, aplikace nabídne **Overwrite**, **Save as New** nebo zrušení. **Overwrite** nahradí obsah sady, ale zachová její identitu a název; **Save as New** vytvoří další sadu; **Cancel** zastaví běh před výpočtem.

Výpočet zpracuje každý zvolený kanál každého měření v načteném poolu. Zrušení během výpočtu odstraní rozpracovanou sadu včetně již zapsaných částí, takže se nezobrazí jako dokončená sada. Pokud některá měření nebo kanály selžou, ale jiné přinesou výsledky, úspěšné výsledky se uloží se stavem *partial* ([Projekty a mezipaměť výsledků](topic:general/projects)) a chyby se zapíší do System Logu. Pokud žádné měření výsledky neposkytne, sada se neuloží. Stavový řádek pod tlačítkem oznámí uložení sady nebo odkáže na System Log.

## Najděte a načtěte výsledky

Sada výsledků se ukládá vedle projektu do jeho adresáře `cache`: složka sady obsahuje jeden HDF5 soubor pro každé měření a manifest `_set.json`. Projekt eviduje sadu i její parametry analýzy. *[Result Pool](topic:results/intro)* zobrazuje uložené sady podle typu výsledku; zaškrtnutím sady načtete její křivky do aktivního grafu. Zrušením zaškrtnutí se křivky této sady z grafu odstraní. Úspěšné dokončení dávky automaticky uloží záznam sady do projektu. Po načtení sad do grafů projekt uložte, aby se zachovalo, které sady jsou v jednotlivých grafech načtené.

Viz také [Data Pool](topic:data_management/intro), [Result Pool](topic:results/intro), [Projekty a mezipaměť výsledků](topic:general/projects) a [Jobs](topic:jobs/intro).
