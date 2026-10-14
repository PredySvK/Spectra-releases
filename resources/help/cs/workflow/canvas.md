# Ovládání plátna

Editor Workflow používá společný vzhled pro **Block Pool**, karty workflow, plátno, **Properties** a stavový řádek. Bloky, porty, dráty a text kreslí Qt přímo podle DPI obrazovky. Přiblížení mění pohled; přesun bloku mění jeho uloženou pozici. [Blokový diagram Workflow](topic:workflow/intro) popisuje výběry Input, ukládání výsledků a spouštění chainů.

## Zkratky a gesta myší

| Ovládací prvek | Gesto | Výsledek |
| --- | --- | --- |
| Karty workflow | Kliknutí na kartu | Otevře workflow s vlastní historií úprav. |
| Plátno | Kolečko myši | Přiblíží nebo oddálí kolem ukazatele. |
| Pozadí plátna | Tažení levým tlačítkem | Posune pohled. |
| Plátno | Tažení prostředním tlačítkem | Posune pohled. |
| Blok | Kliknutí levým tlačítkem | Vybere blok a zobrazí Properties. |
| Blok | Ctrl+kliknutí | Vybere více bloků. |
| Blok | Tažení levým tlačítkem | Přesune blok; dráty jej sledují. |
| Blok | Dvojklik | Zaměří Properties. |
| Řádek Block Pool | Přetažení na plátno | Přidá nepropojený blok na pozici ukazatele s výchozími parametry. |
| Řádek Block Pool | Dvojklik | Přidá blok s kompatibilním drátem od vybraného bloku. |
| Selection | Přetažení na blok Input | Ihned změní výběr dat Input. |
| Výstupní port | Tažení do vstupního portu | Propojí bloky; nahradí drát obsazeného vstupu. |
| Tažení drátu | Escape | Zruší tažení. |
| Drát | Kliknutí, potom Delete; nebo pravé tlačítko → Delete wires | Odpojí vybrané dráty. |
| Vybrané bloky | Delete; nebo pravé tlačítko → Delete blocks | Odstraní bloky, jejich dráty a pozice. |
| Blok | Pravé tlačítko → Run Chain | Spustí jeho chain; dostupné také v pásu. |
| Editor / Properties | Ctrl+Z / Ctrl+Y; nebo tlačítka Undo / Redo | Obnoví potvrzené úpravy; nepotvrzené hodnoty formuláře se nahradí. |
| Projekt | Ctrl+S | Uloží aktuální workflow i rozložení s projektem. |

## Dráty a značky

Vstupní porty jsou **vlevo**, výstupní **vpravo**. Tooltip portu uvádí název, druh dat a povinnost vstupu. Šedé vstupy nemohou přijmout tažený drát. Nekompatibilní druhy dat a cykly se odmítnou s důvodem pod plátnem. Jeden výstup může vést do více vstupů; každý vstup má jeden drát.

Port **tacho · from measurement** bere kanál z Properties; nový drát k němu nelze připojit. Dříve importované tacho dráty lze smazat. Input ukazuje Selection nebo **Whole Data Pool**. **Červený okraj** označuje blok odmítnutý validací (včetně chainu s několika Input); tooltip vysvětlí důvod. Odznak **💾** znamená ukládání výstupu; tooltip uvádí název sady výsledků. Výběr má světle šedý okraj; neplatný vybraný blok si ponechá červený okraj.

Stavový řádek shrnuje připravenost. **Run** spouští všechny spustitelné chainy postupně na pozadí a hlásí odmítnuté chainy; **Run Chain** spustí chain vybraného bloku. Spustitelný chain potřebuje jeden Input s dostupným výběrem dat a alespoň jeden Save blok. Viz [Spouštění chainů](topic:workflow/intro).
