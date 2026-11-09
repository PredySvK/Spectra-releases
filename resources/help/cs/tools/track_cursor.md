# Track cursor

**Track cursor** čte **všechny křivky grafu při jednom X**. Nakreslí svislou čáru přes [křivkový graf](topic:graphs/intro) a vedle ní **Track table** s hodnotou každé křivky na čáře -- hodí se, když porovnáváte mnoho křivek při stejné frekvenci, řádu nebo otáčkách. Pro jeden přesný bod jedné křivky použijte [Kurzor](topic:tools/cursor).

## Zapnutí

- Otevřete záložku **[Tools](topic:tools/intro)** a klikněte na box **Track** ve skupině **Cursors**, nebo
- stiskněte **T**, když má graf fokus (nejdřív na graf klikněte).

Přepínač je jedno nastavení pro **všechny** otevřené grafy. Dalším stiskem **T** nebo kliknutím na box Track cursor vypnete. Track cursor je **ve výchozím stavu vypnutý**; box svítí, když je zapnutý. Funguje jen na křivkových grafech: spektrogram čáru nemá (**T** na něm přepínač přesto přepne, nic se nekreslí).

Box má dole v řadě tři malá kulatá tlačítka: **Track cursor Settings** (ozubené kolečko, vlevo), **Highlight** (baterka, uprostřed) a **Pin** (vpravo). Zapnuté tlačítko je vyplněné; po najetí myší se zobrazí tooltip. Highlight a Pin jsou dostupné, jen když je Track cursor zapnutý, a oba se pamatují i po restartu.

![Box Track a jeho tlačítka v záložce Tools a čára s Track table nad třemi spektry](track_cursor.cs.png)

## Čára a Track table

Čára se poprvé objeví uprostřed grafu a při zoomu, posunu nebo přidání křivek zůstane na grafu. Když odstraníte poslední křivku, zapomene své místo a s další křivkou se vrátí doprostřed. Řídí se osou X grafu, i logaritmickou. [Trace filter](topic:filtering/intro), který skryje všechny křivky, skryje i čáru; v tabulce jsou jen křivky, které právě vidíte.

**Track table** se vznáší vpravo nahoře v grafu. První řádek je X na čáře; pod ním jsou křivky, každá se sloupci, které zvolíte v Track cursor Settings (výchozí **Channel** a **Y**).

- Řádky jsou seřazeny od nejvyššího Y. Křivka bez hodnoty na čáře (čára je mimo její rozsah X, nebo hodnota chybí) ukazuje „—“ a je poslední.
- Křivky na pravé ose Y ([dvě jednotky v jednom grafu](topic:units/intro)) tvoří vlastní skupinu pod tenkou čárou, každá skupina od nejvyšší hodnoty.
- Buňka delší než 32 znaků končí „…“. Řádky, které se nevejdou do výšky grafu, ustoupí řádku **… and N more**, sloupce, které se nevejdou do šířky, ustoupí **+N columns** na konci záhlaví, takže tabulka zůstane vždy uvnitř grafu, i po změně velikosti okna.
- Tabulku přesunete tažením; zůstane, kde ji necháte, dokud Track cursor nevypnete. Tažení tabulky graf automaticky nepřeškáluje.

Čísla se řídí předponou zobrazení a desetinnými místy z Settings → Units, jako v Cursor Boxu; tisíce v X jsou oddělené (15 466 RPM).

## Pin

**Pin** (tlačítko ve skupině **Cursors**) určuje, jak se čára pohybuje. Ve výchozím stavu je **zapnutý**.

- **Připnutý:** čára zůstává na místě. Čáru (pod myší se ztluští) posunete tažením; tažení kdekoli jinde v grafu dál posouvá graf.
- **Odepnutý:** čára sleduje myš po ose X, dokud je myš nad grafem, a po jejím odchodu zůstane na posledním místě. Tažení tabulky čáru neposune.

## Zvýraznění

Je-li **Highlight** Track cursoru zapnutý, každá křivka, kterou čára protne, dostane v tom místě plnou tečku ve vlastní barvě, i křivky, které tabulka složí do „… and N more“. Zároveň se všechny křivky ztlumí podle **Other curves opacity**, i křivka, kterou čára neprotíná; při 0 % křivky zmizí a zůstanou jen tečky. Tečky se nikdy neztlumí a legenda zůstane beze změny. Highlight je na začátku vypnutý.

Je-li zapnutý i [Highlight](topic:tools/cursor#zvýraznění) Cursoru, křivka pod myší se vykreslí tlustěji v plné barvě nad ztlumenými; mimo všechny křivky platí jen vzhled Track cursoru. Vypnutím kteréhokoli Highlightu dostanou křivky zpět svůj vlastní vzhled.

## Track cursor Settings

Ozubené kolečko na boxu **Track** otevře stejné okno jako [Nastavení kurzoru](topic:tools/cursor#nastavení-kurzoru), pro sloupce Track table. Zaškrtněte pole, které se má zobrazit jako sloupec; jeho **Priority** (šipky nebo zadané číslo) je jeho místo, 1 je vlevo. Sekce **Values** obsahuje název křivky, Y a RMS / Peak (bez X a Z: X je první řádek tabulky); sekce metadat nabízejí pole se zaškrtnutým **Active Status** v [Metadata and Filter Settings](topic:import/metadata). Křivka bez pole ukazuje „—“ a pole, které nemá žádná křivka, sloupec nedostane.

Volba patří jen Track table: Cursor Box nemění, ukládá se pro **všechny projekty** a přežije restart. **OK** překreslí všechny otevřené Track table najednou.

- **Other curves opacity** (vlevo dole) je stejné nastavení jako v Cursor Settings: jak viditelné zůstanou křivky, když je zapnutý některý Highlight (výchozí 25 %).
- **Table background opacity** (vedle) jde od 0 % (neviditelné) do 100 % (plné), výchozí 90 %.
- **Auto apply** ukazuje změny v grafech už při práci; **Cancel** je vrátí.
- **Restore Defaults** vrátí celé okno do výchozího stavu: Channel a Y a oba posuvníky. Do **OK** se nic neuloží.
