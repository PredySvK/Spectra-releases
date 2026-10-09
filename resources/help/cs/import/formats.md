# Podporované formáty

Soubor se pozná podle přípony: `.unv`, `.uff`, `.asc`, `.xlsx`, `.txt` (velikost písmen nehraje roli). `.xlsx` a `.txt` jsou příliš běžné, proto jsou měřením jen tehdy, když je rozpoznána jejich hlavička. [`metadata.xlsx`](topic:import/metadata), README nebo poznámky se ignorují.

| Přípona | Formát | Obsah | Druh |
|---|---|---|---|
| `.unv`, `.uff` | Universal File Format, dataset 58 | [časové průběhy](topic:raw_data/intro) | měřené |
| `.asc` | Siemens Testlab ASCII | [časové průběhy](topic:raw_data/intro) | měřené |
| `.txt` | zpracované měření oddělené tabulátory | [křivky řádů](topic:order_tracking/intro) podle otáček | měřené |
| `.xlsx` | výsledkový sešit MASTA | [křivky řádů](topic:order_tracking/intro) podle otáček | simulované (páruje se přes [Párování kanálů](topic:import/channel_pairing)) |

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

První list. Každý kanál je dvojice sloupců (otáčky, amplituda):

| Řádek | Obsah |
|---|---|
| 1 | `<osa>, At housing: <design>\<místo>`, z čehož vznikne kanál `<místo>:<osa>` |
| 2 | typ výsledku, s `Order <n>` a `Damping = <x>` |
| 3 | scénář |
| 4 | `Speed (rev/min)` a `Amplitude (<jednotka>)` |
| 5… | rpm a amplituda (čísla nebo text, desetinná čárka se akceptuje) |

Design, scénář, tlumení a zbylé části řádku 2 oddělené čárkami se stanou [surovými metadaty](topic:import/metadata) (*Design*, *Scenario*, *Damping*, *Description 1…*). Řád patří ke [křivce](topic:order_tracking/orders).

## Typ kanálu

Rozhoduje nejdřív jednotka: `g` a `m/s²` dají akcelerometr, `Pa`, `mbar` a `bar` mikrofon, `rpm`, `Hz` a `rad/s` tachometr. U nejednoznačné jednotky (`V`, `mV`, žádná) rozhodují slova v názvu kanálu (acc, tacho, mic…) a `V`/`mV` bez nápovědy je napěťový kanál. Vše ostatní je obecný dynamický kanál. Typ řídí výchozí chování, např. odstranění DC.
