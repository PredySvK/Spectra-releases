# Podporované formáty

Soubor se pozná podle přípony: `.unv`, `.uff`, `.asc`, `.xlsx`, `.txt`, `.csv` (velikost písmen nehraje roli). `.xlsx`, `.txt` a `.csv` jsou příliš běžné, proto jsou měřením jen tehdy, když je rozpoznána jejich hlavička. [`metadata.xlsx`](topic:import/metadata), README nebo poznámky se ignorují.

| Přípona | Formát | Obsah | Druh |
|---|---|---|---|
| `.unv`, `.uff` | Universal File Format, dataset 58 | [časové průběhy](topic:raw_data/intro) | měřené |
| `.asc` | Siemens Testlab ASCII | [časové průběhy](topic:raw_data/intro) | měřené |
| `.txt` | zpracované měření oddělené tabulátory | [křivky řádů](topic:order_tracking/intro) podle otáček | měřené |
| `.xlsx` | výsledkový sešit MASTA | [křivky řádů](topic:order_tracking/intro) podle otáček | simulované (páruje se přes [Párování kanálů](topic:import/channel_pairing)) |
| `.csv` | harmonická odezva ANSYS | [křivka](topic:order_tracking/intro) 1. řádu podle otáček | simulované (páruje se přes [Párování kanálů](topic:import/channel_pairing)) |

## .unv / .uff

Čte se jen **dataset 58**, jeden kanál na dataset; ostatní datasety se přeskočí. Dataset musí být *časová odezva* (typ funkce 1). Dataset se spektrem nebo FRF se v seznamu objeví, ale při otevření skončí hlášením.

| Pole | Odkud |
|---|---|
| Název kanálu | ID řádek 1 (ID řádek 5, je-li řádek 1 prázdný) |
| Jednotka | popisek jednotky ordináty (záznam 10) |
| Začátek času, časový krok | minimum a přírůstek abscisy (záznam 8) |
| Vzorkovací frekvence | 1 / časový krok |
| Počet bodů | záznam 8 |
| Uzel a směr odezvy a reference | záznam 6 |
| ID řádky 1–5 | uloženo jako surová metadata (popis nastavení, datum a čas, čas vytvoření, sekce běhu, označení hardwaru) |

Typ funkce 5 značí kanál tachometru; jinak se typ určí z jednotky a názvu (viz *Typ kanálu*). Binární soubory s rovnoměrnými reálnými daty se čtou přímo. ASCII datasety, komplexní data a nerovnoměrný krok jdou pomalejší cestou se stejným výsledkem.

## .asc

Hlavička mezi řádky `BEGIN` a `END`, pak jeden řádek na vzorek, hodnoty oddělené čárkou nebo mezerou. Soubor se čte jako UTF-8.

| Řádek hlavičky | Význam |
|---|---|
| `START = <s>` | čas prvního vzorku |
| `DELTA = <s>` | časový krok |
| `RATE = <Hz>` | vzorkovací frekvence; nahradí `DELTA`, pokud je v hlavičce později a je větší než 0 |
| `CHANNELNAME = ['a', 'b', ...]` | jeden název na sloupec |
| `UNIT = ['g', 'Pa', ...]` | jedna jednotka na sloupec |

První sloupec je časový vektor, pokud se jmenuje `time`, `elap_time`, `time1`, `sec` nebo `s`, nebo má jednotku `s` či `sec`; pak to není kanál. Jinak se čas vytvoří z `START` a `DELTA`. Počet vzorků je počet neprázdných datových řádků. Řádek s jiným počtem sloupců než hlavička je chyba.

## .txt (zpracované měření)

První řádek: `(rev/s)`, pak buňka `název (jednotka)` pro každý kanál, oddělené tabulátory. Každý další řádek je rychlost v rev/s a jedna hodnota na kanál. Rychlost se převádí na rpm (× 60). Koncovka názvu souboru `_H<n>` (např. `Run_H3.txt`) určuje [řád](topic:order_tracking/orders) křivek.

## .xlsx (MASTA)

Čtou se všechny listy s názvem `H<n>` (např. `H1`, `H4.79`, `H22`); ostatní listy se přeskočí. Sešit bez takových listů se čte z prvního listu. V Data Poolu jsou kanály pod svým listem. Každý kanál je dvojice sloupců (otáčky, amplituda):

| Řádek | Obsah |
|---|---|
| 1 | `<osa>, At housing: <design>\<místo>`, z čehož vznikne kanál `<místo>:<osa>` |
| 2 | typ výsledku, s `Order <n>` a `Damping = <x>` |
| 3 | scénář |
| 4 | `Speed (rev/min)` a `Amplitude (<jednotka>)` |
| 5… | rpm a amplituda (čísla nebo text, desetinná čárka se akceptuje) |

Design, scénář, tlumení a zbylé části řádku 2 oddělené čárkami se stanou [surovými metadaty](topic:import/metadata) (*Design*, *Scenario*, *Damping*, *Description 1…*). Řád patří ke [křivce](topic:order_tracking/orders).

## .csv (harmonická odezva ANSYS)

Jeden soubor na Design point a uzel, pojmenovaný `DP<n>_Freq_Resp_<kanál>.csv` (např. `DP0_Freq_Resp_B0_HSG_inner_Acc_Y.csv`). Jiné `.csv` ve složce, třeba export Bearing Probe, se přeskočí.

| Řádek | Obsah |
|---|---|
| 1 | `Frequency [Hz],Amplitude [<jednotka>]` |
| 2… | frekvence a amplituda |

Každý řádek smí být v uvozovkách. Znak `˛` v jednotce se čte jako `²` (`mm/s˛` → `mm/s²`). Řádek, který nejsou dvě čísla, se zahodí; krok frekvence smí být nerovnoměrný.

- Kanál se jmenuje `<kanál>` beze změny, takže se páruje stejným názvem v [`channel_pairing.xlsx`](topic:import/channel_pairing). Koncovka `_X`, `_Y` nebo `_Z` určuje směr.
- Křivka je [řád](topic:order_tracking/orders) 1 podle rpm = 60 · frekvence: nevývaha působí na frekvenci otáčení.
- **Amplitudy z ANSYS jsou ve výchozím nastavení špičkové.** Při přidání souborů se program zeptá, zda je amplituda RMS, nebo Peak (viz *Zdrojová amplituda* níže); špičková se dělí √2, takže křivka je RMS jako každá počítaná křivka řádu. Znovu ji nepřevádějte; přepínač zobrazení Peak/RMS na ní funguje jako obvykle.
- `DP<n>` se stane [surovými metadaty](topic:import/metadata) *Design point*.

Co Design point znamená (nevývaha rotoru, pružina…), patří do `Metadata.xlsx` umístěného **v každé výsledkové složce**, s `File Name` = `DP0`, `DP1`, … Řádek `DP1` popisuje soubory `DP1_…`, nikdy `DP10_…`. Použijte stejné názvy sloupců a hodnoty jako metadata měření (např. `Rotor unbalance` = `G2.5`), aby Trace filtr ukázal odpovídající měření a Design point spolu. Řádky `DP<n>` nedávejte do projektového `metadata.xlsx`: má přednost a platily by pro každou výsledkovou složku.

## Zdrojová amplituda

Soubory MASTA, zpracovaného měření a ANSYS nesou hotovou amplitudu a soubor neříká, zda je RMS, nebo Peak. Při přidání takových souborů do Data Poolu se program zeptá jednou na formát (ne na soubor) a ukáže převod, který použije: `RMS = Peak / √2`.

| Formát | Výchozí odpověď |
|---|---|
| MASTA | RMS |
| zpracované měření | RMS |
| ANSYS | Peak |

- Odpověď se uloží u každého souboru v projektu a neptá se znovu při Refresh ani při otevření projektu. Nové soubory, které se objeví ve sledované složce, se zeptají znovu.
- Cancel nepřidá do poolu nic. Chybnou odpověď opravíte tak, že soubor z poolu odeberete a přidáte znovu.
- Časové signály (`.unv`, `.uff`, `.asc`) se nikdy neptají: jejich amplitudu si program počítá sám.
- Projekt uložený před zavedením otázky otevře křivky beze změny (ANSYS Peak, ostatní RMS).

## Typ kanálu

Rozhoduje nejdřív jednotka: `g` a `m/s²` dají akcelerometr, `Pa`, `mbar` a `bar` mikrofon, `rpm`, `Hz` a `rad/s` tachometr. U nejednoznačné jednotky (`V`, `mV`, žádná) rozhodují slova v názvu kanálu (acc, tacho, mic…) a `V`/`mV` bez nápovědy je napěťový kanál. Vše ostatní je obecný dynamický kanál. Typ řídí výchozí chování, např. odstranění DC.
