# Blokový diagram Workflow

Workflow automatizuje výpočty. Prepojíte bloky spracovania, napríklad Remove DC → Spectrum, a spustíte ich nad mnohými meraniami naraz namiesto ručného otvárania každého kanála.

- **Vstupy:** blok **Input** vyberá merania: **Whole Data Pool** alebo uloženú **Selection**.
- **Výsledky:** blok so zapnutým **Save result set** zapíše svoj výstup ako result set do cache výsledkov projektu a má odznak **💾**. Bloky bez ukladania sú len medzikroky. Na vykreslenie zamerajte graf a zaškrtnite sadu v **Result Pool** (Explorer); pozri [Result Pool](topic:results/intro).

Na karte pásu **Workflow** vytvorte **New Workflow** alebo ho vyberte na kartách nad plátnom. Kompletnú tabuľku skratiek, gest myšou a značiek nájdete v téme [Ovládanie plátna](topic:workflow/canvas).

**Block Pool** obsahuje Input Data a typy blokov spracovania. Pretiahnutie typu na plátno pridá neprepojený blok na pozíciu ukazovateľa. Dvojklik pridá blok s drôtom od vybraného bloku, ak je výstup kompatibilný s primárnym vstupom; inak zostane neprepojený. Nový blok používa predvolené nastavenia svojho typu. Input Data má na začiatku vybraný celý Data Pool.

## Properties

**Properties** vpravo obsahujú nastavenia vybraného bloku. Input číta dáta vybrané cez [Selection](topic:selections/intro); blok spracovania má svoje parametre a voľbu **Save result set**, pozri [Výsledky](topic:results/intro). Nastavenia bloku potvrďte cez **Apply block settings**; **Ctrl+S** ich uloží s projektom.

## Drôty a značky

Ťahajte z výstupného portu vpravo do vstupného vľavo. Sivé vstupy nemôžu prijať drôt; nekompatibilný druh dát alebo cyklus sa odmietne s dôvodom pod plátnom. Jeden výstup môže viesť do viacerých vstupov. Nový drôt do obsadeného vstupu nahradí pôvodný. **Escape** zruší ťahanie. Tooltip portu uvádza druh dát a povinnosť vstupu.

Port **tacho · from measurement** používa tachokanál vybraný v Properties. Nový drôt sa k nemu nedá pripojiť; skôr uložené tacho drôty zostávajú viditeľné a možno ich zmazať. Input ukazuje názov Selection alebo **Whole Data Pool**. Červený okraj označuje blok odmietnutý validáciou; tooltip vysvetlí dôvod. Odznak **💾** označuje ukladanie výstupu a tooltip uvádza názov sady výsledkov. Stav pod plátnom zhŕňa pripravenosť workflow na beh.

Kliknutím na drôt a klávesou **Delete**, alebo pravým tlačidlom → **Delete wires**, odpojíte vybrané drôty. Bloky vyberiete kliknutím; **Ctrl+kliknutie** vyberie viac blokov. **Delete** alebo pravé tlačidlo → **Delete blocks** odstráni vybrané bloky aj ich drôty a uložené pozície.

## Spúšťanie chainov

**Chain** je jedna prepojená časť diagramu s vlastným Input a výberom dát. Drôt medzi dvoma chainmi ich spojí. Chainy sa odvodzujú z drôtov a nemajú samostatné nastavenia. Správy ich označujú poradím na plátne a identifikátormi Input, napríklad **Chain 2 (input_2)**.

**Run** spúšťa všetky spustiteľné chainy postupne na pozadí. Odmietnutý chain sa ohlási názvom a preskočí; ostatné pokračujú. Každý chain potrebuje jeden Input s dostupným výberom dát a aspoň jeden blok s ukladaním. Chainy s viacerými Input zatiaľ nie sú podporované.

Vyberte blok a použite **Run Chain** v páse alebo pravé tlačidlo na blok → **Run Chain**. Spustí sa len jeho chain. Tlačidlo v páse je aktívne, keď je vybraný blok. Pred behom jeden dialóg **Overwrite / Save as new / Cancel** zahrnie existujúce zodpovedajúce sady zo všetkých spustiteľných chainov, podľa ukladaných blokov. Cancel zruší celý požiadavok. Zrušenie bežiaceho chainu zastaví aj zostávajúce chainy.
