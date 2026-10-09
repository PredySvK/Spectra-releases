# Vyhodnocení (Evaluation)

**Evaluation** mění křivky jednoho grafu na čísla. Otevřete záložku *Evaluation* ve spodním panelu, klikněte na graf, zvolte Evaluation a tabulka vypíše jednu **Single value** na křivku (u Top-N maxima i víc): číslo, kde na křivce leží a ze které křivky pochází. Evaluation nikdy nevytvoří novou křivku a nemění data.

![Dok Filters a tabulka Evaluation](filter_evaluation.cs.png)

Každý graf si pamatuje vlastní Evaluation, její parametry a sloupce; ukládají se s projektem. Tabulka sleduje graf v popředí a přepočítá se, když se změní jeho obsah nebo [Trace filter](topic:filtering/intro). Výpočet běží na pozadí; je-li záložka skrytá, jen se označí jako zastaralá a přepočte se při jejím otevření.

## Čtyři Evaluation

| Evaluation | Čte | Řádků na křivku | Stránka |
|---|---|---|---|
| **Max** | spektra, order cuts, Overall Level | právě 1 (pomlčka, pokud křivka nemá platný vzorek) | [Max](topic:evaluation/max) |
| **Top-N maxima** | spektra, order cuts, Overall Level | 0 až N, od nejvyššího | [Top-N maxima](topic:evaluation/topn_maxima) |
| **Typed orders** | jeden spektrogram sledovaný podle rpm | jeden na každý zadaný řád | [Typed orders](topic:evaluation/typed_orders) |
| **Dominant orders** | jeden spektrogram sledovaný podle rpm | 0 až N, nalezené automaticky | [Dominant orders](topic:evaluation/dominant_orders) |

Časový graf nebo graf, jehož křivky zvolená Evaluation nečte, místo tabulky ukáže zprávu *This dock has no curves Evaluation supports.* Bez otevřeného grafu záložka hlásí *No graph is open.* Prázdná tabulka to také napíše (*No evaluation results for the current parameters.*, případně varianta pro Typed / Dominant orders).

## Sloupce

Prvních osm sloupců je vždy, v tomto pořadí. Další přidává **Columns&hellip;** (níže).

| Sloupec | Co obsahuje |
|---|---|
| **Channel** | název kanálu a směr, např. *Acc1 Z* |
| **Measurement** | soubor, z něhož je křivka spočtená |
| **Source** | štítek [result setu](topic:results/intro), nebo *Live* u křivky spočtené na místě |
| **Order / Band** | pro co je křivka spočtená: *Order 4.79* u [order cutu](topic:order_tracking/orders), pásmo jako *10-Full Bandwidth* nebo *100-2000 Hz* u [Overall Level](topic:overall_level/band); u [spektra](topic:spectrum/intro) prázdné. Typed orders a Dominant orders přidávají šířku řádu, např. *Order 4.79 (&plusmn;0.2)* |
| **Value (jednotka)** | získané číslo na čtyři platné číslice, jednotka v hlavičce (např. *Value (g)*, v režimu Peak *Value (g Peak)*). Mají-li řádky různé jednotky, hlavička říká jen *Value (RMS)* nebo *Value (Peak)* a každá buňka nese svou jednotku |
| **at X (jednotka)** | kde na ose X křivky hodnota leží: rpm, Hz, s nebo řád, v globální [jednotce osy X](topic:units/intro). Jednotka je v hlavičce, mají-li ji všechny řádky stejnou |
| **Edge** | *Yes*, leží-li hodnota na prvním nebo posledním platném vzorku své křivky, tedy skutečné maximum může ležet za spočteným rozsahem. Jinak prázdné |
| **Parameter Set** | *Parameter Set 1*, *2*, ... -- křivky spočtené se stejným nastavením mají stejné číslo ([Result Pool](topic:results/intro)), takže poznáte dvě [velikosti FFT](topic:shared/fft_size). Prázdné, pokud křivka žádný nemá |

Křivka bez platného vzorku (řád pod frekvenčním rozlišením nebo nad Nyquistem) řádek přesto dostane: Value a at X ukazují **&mdash;**. Pomlčka neznamená vynechanou křivku.

## Lišta nástrojů

- **Evaluation:** výběr výše. Jeho parametry se zobrazí vedle.
- **Amplitude (RMS / Peak):** ([Formát amplitudy](topic:shared/amplitude_format)) Peak = &radic;2 &times; RMS. Jde jen o zobrazení; nic se nepřepočítává a poloha se nemění.
- **Format (Linear / Power / PSD):** jak se zobrazí řádky se spektry; aktivní jen, obsahuje-li tabulka spektra. Order cuts a Overall Level tuto volbu nemají.
- **Units:** řídí se globálním nastavením jednotek ([Jednotky](topic:units/intro)); tabulka se při změně aktualizuje.
- **Copy** nebo Ctrl+C zkopíruje vybrané řádky, nebo celou tabulku, když nic vybráno není, odděleně tabulátory a s hlavičkami pro Excel. Totéž nabízí nabídka na pravé tlačítko.
- **Export CSV** zapíše **celou** tabulku (ne jen výběr) v právě zobrazeném pořadí, včetně hlaviček. Texty buněk jsou ty z obrazovky, takže *Value* má čtyři platné číslice.
- **Columns&hellip;** přidá další sloupce ve čtyřech skupinách: *Identity* (Channel, Direction, Channel type, File name, Data Pool label, Result set), *Raw metadata*, *Excel metadata* a *Calculated metadata* (Analysis type, Order, Parameter set). Nabízejí se jen pole aktivní v [Metadata Editoru](topic:import/metadata); pole, které později deaktivujete, zůstane vybrané, ale z tabulky zmizí. Výběr se pamatuje pro každý graf a ukládá s projektem.
- **Respect Trace filter:** ve výchozím stavu zapnuto, takže tabulka pokrývá jen křivky, které graf zobrazuje. Vypnuto vyhodnotí každou křivku grafu, i ty, které filtr skrývá. Pamatuje se pro každý graf.
- **?** otevře stránku zvolené Evaluation.

Kliknutím na hlavičku sloupce řadíte. Čísla se řadí číselně, řády a pásma podle svého čísla, text abecedně bez ohledu na velikost písmen. Prázdné buňky a pomlčky zůstávají dole při obou směrech.

## Jak číst čísla

Hodnota se vždy počítá v jednotce kanálu z energie po binech (viz [Formát amplitudy](topic:shared/amplitude_format)); přepínače Amplitude, Format a Units ji jen přepisují. Proto se poloha při přepnutí nemění a Top-N maxima i Dominant orders měří prominenci v dB lineární RMS amplitudy: výběr nezávisí na zobrazení.
