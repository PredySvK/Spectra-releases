# Ovládanie plátna

Editor Workflow používa spoločný vzhľad pre **Block Pool**, karty workflow, plátno, **Properties** a stavový riadok. Bloky, porty, drôty a text kreslí Qt priamo podľa DPI obrazovky. Priblíženie mení pohľad; presun bloku mení jeho uloženú pozíciu. [Blokový diagram Workflow](topic:workflow/intro) opisuje výbery Input, ukladanie výsledkov a spúšťanie chainov.

## Skratky a gestá myšou

| Ovládací prvok | Gesto | Výsledok |
| --- | --- | --- |
| Karty workflow | Kliknutie na kartu | Otvorí workflow s vlastnou históriou úprav. |
| Plátno | Koliesko myši | Priblíži alebo oddiali okolo ukazovateľa. |
| Pozadie plátna | Ťahanie ľavým tlačidlom | Posunie pohľad. |
| Plátno | Ťahanie prostredným tlačidlom | Posunie pohľad. |
| Blok | Kliknutie ľavým tlačidlom | Vyberie blok a zobrazí Properties. |
| Blok | Ctrl+kliknutie | Vyberie viac blokov. |
| Blok | Ťahanie ľavým tlačidlom | Presunie blok; drôty ho sledujú. |
| Blok | Dvojklik | Zameria Properties. |
| Riadok Block Pool | Pretiahnutie na plátno | Pridá neprepojený blok na pozíciu ukazovateľa s predvolenými parametrami. |
| Riadok Block Pool | Dvojklik | Pridá blok s kompatibilným drôtom od vybraného bloku. |
| Selection | Pretiahnutie na blok Input | Ihneď zmení výber dát Input. |
| Výstupný port | Ťahanie do vstupného portu | Prepojí bloky; nahradí drôt obsadeného vstupu. |
| Ťahanie drôtu | Escape | Zruší ťahanie. |
| Drôt | Kliknutie, potom Delete; alebo pravé tlačidlo → Delete wires | Odpojí vybrané drôty. |
| Vybrané bloky | Delete; alebo pravé tlačidlo → Delete blocks | Odstráni bloky, ich drôty a pozície. |
| Blok | Pravé tlačidlo → Run Chain | Spustí jeho chain; dostupné aj v páse. |
| Editor / Properties | Ctrl+Z / Ctrl+Y; alebo tlačidlá Undo / Redo | Obnoví potvrdené úpravy; nepotvrdené hodnoty formulára sa nahradia. |
| Projekt | Ctrl+S | Uloží aktuálny workflow aj rozloženie s projektom. |

## Drôty a značky

Vstupné porty sú **vľavo**, výstupné **vpravo**. Tooltip portu uvádza názov, druh dát a povinnosť vstupu. Sivé vstupy nemôžu prijať ťahaný drôt. Nekompatibilné druhy dát a cykly sa odmietnu s dôvodom pod plátnom. Jeden výstup môže viesť do viacerých vstupov; každý vstup má jeden drôt.

Port **tacho · from measurement** berie kanál z Properties; nový drôt sa k nemu nedá pripojiť. Skôr importované tacho drôty možno zmazať. Input ukazuje Selection alebo **Whole Data Pool**. **Červený okraj** označuje blok odmietnutý validáciou (vrátane chainu s viacerými Input); tooltip vysvetlí dôvod. Odznak **💾** znamená ukladanie výstupu; tooltip uvádza názov sady výsledkov. Výber má svetlosivý okraj; neplatný vybraný blok si ponechá červený okraj.

Stavový riadok zhŕňa pripravenosť. **Run** spúšťa všetky spustiteľné chainy postupne na pozadí a hlási odmietnuté chainy; **Run Chain** spustí chain vybraného bloku. Spustiteľný chain potrebuje jeden Input s dostupným výberom dát a aspoň jeden Save blok. Pozri [Spúšťanie chainov](topic:workflow/intro).
