# Blokový diagram Workflow

Workflow automatizuje výpočty. Propojíte bloky zpracování, například Remove DC → Spectrum, a spustíte je nad mnoha měřeními najednou, místo ručního otevírání každého kanálu.

- **Vstupy:** blok **Input** vybírá měření: **Whole Data Pool** nebo uloženou **Selection**.
- **Výsledky:** blok se zapnutým **Save result set** zapíše svůj výstup jako result set do cache výsledků projektu a má odznak **💾**. Bloky bez ukládání jsou jen mezikroky. Pro vykreslení zaměřte graf a zaškrtněte sadu v **Result Pool** (Explorer); viz [Result Pool](topic:results/intro).

![Karta Workflow: Block Pool, blokový diagram s dráty a Properties](workflow_canvas.cs.png)

Viz [Ovládání plátna](topic:workflow/canvas) pro úplnou tabulku zkratek, gest myší a značek na plátně.

Na kartě pásu **Workflow** vytvořte **New Workflow** nebo jej vyberte v kartách nad plátnem. Samostatné propojené části diagramu se nazývají chainy.

Vstupní porty jsou vlevo, výstupní vpravo. Najeďte na port a zobrazí se druh dat a informace, zda je vstup povinný nebo volitelný. Dráty ukazují tok dat mezi bloky. Bloky se automaticky rozmístí zleva doprava. Červený okraj znamená, že workflow zatím není platné; najeďte na blok pro zprávu validace.

## Spouštění chainů

Každý **chain** je jedna propojená část diagramu s vlastním výběrem dat v Input.
Drát mezi dvěma chainy je spojí. Chainy se odvozují z drátů a nemají samostatné
nastavení. Zprávy je označují pořadím na plátně a identifikátory Input bloků,
například **Chain 2 (input_2)**.

**Run** spustí všechny spustitelné chainy postupně na pozadí. Chain, který nelze
spustit, se ohlásí jménem a přeskočí; ostatní pokračují. Každý chain potřebuje
jeden Input s výběrem dat a alespoň jeden blok nastavený k ukládání výsledků.
Chainy s několika Input bloky **zatím nejsou podporovány** a přeskočí se.

Vyberte blok a klikněte na **Run Chain** v pásu, nebo **pravým tlačítkem na blok →
Run Chain**, pro spuštění pouze jeho chainu. Tlačítko v pásu je aktivní, když je
vybraný blok. Před spuštěním jeden dialog **Overwrite / Save as new / Cancel**
zahrne existující odpovídající sady ze všech spustitelných chainů, podle ukládaných
bloků. Cancel zruší celý požadavek; zrušení běžícího chainu zastaví i zbývající chainy.

## Značky a úpravy

Port **tacho** je označen **from measurement**, protože používá tachokanál měření. Nové dráty k němu nelze připojit; kanál vyberte v Properties bloku. Dříve uložené dráty k tacho zůstávají viditelné a lze je vybrat a smazat. Blok Input zobrazuje název Selection nebo **Whole Data Pool**. Červený okraj označuje blok odmítnutý validací; najeďte na něj pro zobrazení důvodu. Odznak **💾** označuje blok, který ukládá výstup; najeďte na něj pro zobrazení názvu result setu.

**Klikněte na drát a stiskněte Delete**, nebo na něj klikněte pravým tlačítkem a zvolte **Delete wires**, abyste jej odpojili. Vyberte bloky na plátně a stiskněte **Delete**, nebo klikněte pravým tlačítkem a zvolte **Delete blocks**. Odstraní se také jejich dráty a uložené pozice. Zpět **Ctrl+Z**, znovu **Ctrl+Y**.

## Properties

**Properties** vpravo obsahují nastavení vybraného bloku. Blok Input čte data vybraná pomocí [Selection](topic:selections/intro); blok zpracování má své parametry a volbu **Save result set**, viz [Výsledky](topic:results/intro). Nastavení bloku potvrďte tlačítkem **Apply block settings**; **Ctrl+S** je uloží s projektem.
