# Filtrování

Dok **Filters** zužuje, co vidíte, aniž by sahal na data. Filtruje se dvojí:

- **křivky už nakreslené v grafu** -- **Trace filter** křivky skrývá; nikdy žádnou nepřidá, nic nepřepočítává a nemění žádný výsledek;
- volitelně i **strom Data Pool**, aby se vypsala jen odpovídající měření a kanály (**Filter Data Pool**).

Tabulka Evaluation Trace filter sleduje ([Respect Trace filter](topic:evaluation/intro)).

![Filters dock and Configure Filters dialog](configure_filters.cs.png)

## Filter cards

Dok ukazuje jednu **Filter card**: pojmenovanou záložku se seznamem sloupců. Zaškrtnuté hodnoty za ní jsou její **Filter selection**.

- **Global** -- jedna selection sdílená všemi grafy. Nabízí hodnoty z celého [Data Poolu](topic:data_management/intro) a [Result Poolu](topic:results/intro), takže jedno kliknutí změní všechny otevřené grafy.
- **Local** -- jedna selection na graf. Nabízí jen to, co kreslí graf v popředí, a filtruje jen ten graf.
- **+** přidá vlastní kartu (výchozí je Local). Vlastní Local karta patří grafu, který byl v popředí; její záložka je vidět jen dokud je ten graf v popředí. Zaškrtávátko **Global** vedle, nebo nabídka na pravé tlačítko (*Make Global* / *Make Local*, *Rename&hellip;*, *Duplicate*, *Delete*), mění rozsah. Dvě pevné záložky rozsah měnit ani se mazat nedají.

V platnosti je vždy právě jedna karta, pro všechny grafy. Přepnete kliknutím na záložku. Je-li v platnosti vlastní Local karta grafu, který opustíte, dok se vrátí na *Local* a po návratu na ten graf zase na vlastní kartu. Karty a selections se ukládají s projektem.

## Co karta nabízí

Nová karta má **jediný sloupec: Channel**. Vše ostatní přidáte přes **&#9881; Configure Filters&hellip;**:

| Skupina | Sloupce |
|---|---|
| Identity | Channel, Direction, Channel type ([Podporované formáty](topic:import/formats)), File name, Data Pool label, [Result set](topic:results/intro) |
| Raw metadata | pole přečtená ze souborů měření |
| Excel metadata | pole z tabulky metadat ([Metadata z Excelu](topic:import/metadata)) |
| Calculated | Analysis type (spektrum, order cut, ...), Order, Parameter set |

Pole Raw a Excel se tam objeví, až u nich v *[Metadata and Filter Settings](topic:import/metadata)* zaškrtnete **Use as Filter**. Každý řádek ukazuje, kolik různých hodnot sloupec právě má, *(N)*; sloupec s jednou hodnotou nebo s jinou hodnotou u každého měření je zešedlý („cannot narrow anything down"), ale vybrat jde.

V *Configure Filters* dále volíte **pozici** každého sloupce, jak se kreslí, na kolik **sloupců vedle sebe** karta běží (1 až 4) a **Default**. Sloupec s *Default* se přidá na kartu každého nového grafu navíc ke Channel. **Auto apply** ukazuje každou změnu na grafu v popředí už při úpravě; Cancel kartu vrátí.

Kreslení: **Checkbox list**, **Multi-select** (tlačítko se seznamem) nebo **Range (min..max)**. Číselné nebo datumové pole je vždy rozsah; chcete-li jeho hodnoty vybírat ze seznamu, změňte v *[Metadata and Filter Settings](topic:import/metadata)* jeho Type na Text. Seznam delší než 12 řádků se rolují uvnitř svého rámečku.

**Parameter Set** (viz [Result Pool](topic:results/intro)) je skupina křivek spočtených se stejným nastavením, číslovaná *Parameter Set 1, 2, ...* (řád do nastavení nepatří -- je to samostatný sloupec). Ukažte myší na hodnotu, uvidíte nastavení, které zastupuje.

## Jak se křivka posuzuje

Křivka zůstane vidět, jen když ji **každý sloupec** propustí, a sloupec ji propustí, je-li hodnota křivky **zaškrtnutá** (stačí kterákoli ze zaškrtnutých). Pravidla podrobně:

1. **Odškrtnuté políčko skrývá, nikdy nenabídnutá hodnota ne.** Maska skrývá jen to, k čemu karta ukázala políčko a vy jste ho odškrtli. Kanál přetažený do grafu po vašem posledním pohledu, nebo sloupec, který karta nemá, nic neskrývá. Když se objeví širší sada hodnot, zaškrtnou se za vás jen *nové* hodnoty; hodnota, kterou jste vědomě odškrtli, zůstane odškrtnutá.
2. **Odškrtnutí všeho v nabízeném sloupci skryje každou křivku**, protože není povolena žádná hodnota.
3. **(Empty)** se ve sloupci objeví, když některá křivka v něm hodnotu nemá (časová křivka nemá Order, křivka bez zdroje nemá metadata). Odškrtnutím tyto křivky skryjete.
4. **Order** se porovnává s tolerancí (relativní 10<sup>&minus;5</sup>), takže 2.3 zadané vámi odpovídá 2.3 uloženému jako float.
5. **Range** skryje křivku, jen když jste rozsah posunuli a hodnota křivky leží mimo něj. Nedotčený rozsah nic neskrývá a křivka bez hodnoty tohoto pole projde -- rozsah vypovídá jen o křivkách, které umí posoudit. U pole na úrovni kanálu se čte vlastní kanál křivky.
6. Hodnota, jejíž křivky jsou už tak všechny skryté **jinými** sloupci, je zešedlá: kliknutí na ni by nic nezměnilo.

## Filter Data Pool a Show all

- **Filter Data Pool** zúží strom Data Pool na měření a kanály odpovídající kartě. Zde platí *kladný seznam*, takže sloupec se počítá, jen když opravdu zužuje: všechny hodnoty zaškrtnuté, nebo žádná, znamená žádné omezení. Je-li zapnuto, přispívají hodnotami i vlastní měření poolu, takže filtrovat jde dřív, než se cokoli spočítá.
- **Show all** vypne najednou všechny masky na všech grafech i zúžení poolu a karty zešedne. Zaškrtnuté hodnoty zůstanou; po odškrtnutí jsou filtry zpět.
