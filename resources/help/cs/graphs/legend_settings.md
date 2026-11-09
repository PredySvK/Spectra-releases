# Legend Settings

**Curve name** křivky je řádek, který ji pojmenovává: v legendě grafu, jako **Curve** v [Cursor Boxu a Track table](topic:tools/cursor) a v údaji [Band RMS](topic:tools/band_rms). Ve výchozím stavu zní `[soubor] kanál Result name [jednotka]`, například `[run.unv] B1 Out:+Z Order 2 [g RMS]`.

## Otevření okna

Klikněte pravým tlačítkem do grafu a vyberte **Legend Settings…**, nebo najeďte myší na legendu a klikněte na malé ozubené kolečko, které se objeví v jejím pravém horním rohu. Kolečko je vidět jen při najetí myší na legendu, takže není v exportovaném obrázku; při přesunu legendy ho následuje. Okno se otevře nad tímto grafem a mění jen tento graf. Spektrogram legendu nemá, proto tuto položku nenabízí.

## Výběr částí

Každý řádek je jedna část Curve name. Zaškrtnutím řádek použijete; jeho **Priority** (šipky nebo napsané číslo) je jeho místo ve jméně, 1 je první.

Okno nabízí každé pole, které nabízí [Configure Filters](topic:filtering/intro), ve stejných sekcích, a navíc dva vlastní řádky:

- **Identity:** File name, Channel, Direction, Channel type, Data Pool label, Result set a **Unit** (jednotka křivky jako na ose, například `g RMS` nebo `dB`).
- **Raw metadata** a **Excel metadata:** každé pole se zapnutým Active Status v Metadata and Filter Settings.
- **Calculated:** Analysis type, Order, Parameter set a **Result name**: `Order 2`, `OAL`, `OAL 10–500 Hz`, `Residual`; prázdné u obyčejného spektra nebo časového signálu.

Pole metadat ukazuje jen svou hodnotu, bez názvu pole, například `Parameter Set 2` nebo `Front`. Po úpravě metadat měření ukáže legenda novou hodnotu při nejbližším překreslení grafu.

Části se spojí mezerou v pořadí Priority. File name a Unit zůstávají v hranatých závorkách jako ve výchozím stavu; část, pro kterou křivka nemá hodnotu, se vynechá. Křivka na pravé ose Y si za jménem ponechá poznámku `▸ right axis`. Jméno se samo přizpůsobí změně jednotky nebo zobrazení.

## Auto apply, Restore Defaults

Se zapnutým **Auto apply** graf ukazuje každou změnu hned; **Cancel** vrátí graf do původního stavu. Zapnutí Auto apply i velikost a poloha okna se pamatují. **Restore Defaults** vrátí oba sloupce na File name, Channel, Result name a Unit v tomto pořadí. **OK** ponechá volbu pro tento graf a uloží ji s projektem.

## Výchozí legenda nových grafů

Sloupec **Default** funguje jako v [Configure Filters](topic:filtering/intro): zaškrtněte ho na zaškrtnutém řádku a každý nový graf začne s touto částí, v pořadí Priority. Odškrtnutím řádku se jeho Default zruší. **OK** uloží Default pro všechny projekty; graf uložený bez vlastní legendy také vezme Default.
