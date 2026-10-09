# Projekty a cache

**Projekt** (`*.nvhproject`) eviduje všechna vaše rozhodnutí o sadě měření. Nikdy neobsahuje vzorky: měření zůstávají, kde jsou, a spočtené výsledky leží ve složce `cache` vedle souboru projektu.

## Co projekt obsahuje

- **datové složky** (kořeny [Data Pool](topic:data_management/intro)) a záznam o každém nalezeném souboru s měřením, včetně metadat, oprav jednotek a nastavení testu ([Import dat](topic:import/intro));
- seznam **sad výsledků** (result sets), které byly spočteny a uloženy ([Result Pool](topic:results/intro));
- uložené [výběry](topic:selections/intro), workflow, **Filter cards** ([Filtrování](topic:filtering/intro)) a schéma metadat ([Metadata](topic:import/metadata));
- rozložení oken, otevřené záložky a [jednotku osy X](topic:units/intro).

Není v projektu: zobrazované jednotky (drží je aplikace) a párování kanálů, které se čte ze souboru `channel_pairing.xlsx` ([Párování kanálů](topic:import/channel_pairing)).

## Cache výsledků

**Calculate &amp; Save Data** zapíše **sadu výsledků** (viz [Result Pool](topic:results/intro)): složku `cache/<název>/` s jedním souborem HDF5 na měření a malým manifestem `_set.json`. To, co spočtete živě vložením kanálu do [grafu](topic:graphs/intro), se *nezapisuje*.

Když později vložíte kanál do grafu, Spectra nejdřív hledá uložený výsledek, který požadavek už zodpovídá, a vykreslí ho z disku místo výpočtu. **Use cached results** (*Settings*, skupina Cache) toto hledání vypíná, takže se každý požadavek počítá; volba se pamatuje v aplikaci.

### Kdy se uložený výsledek použije

Výsledek se použije, jen když platí **všechno** z toho:

1. existuje sada výsledků stejného **druhu** ([spektrum](topic:spectrum/intro), [spektrogram](topic:spectrogram/intro), [řez řádu](topic:order_tracking/orders), [Overall Level](topic:overall_level/intro)), která toto měření pokrývá;
2. její stav je **complete** -- *partial* sada (některý kanál nebo soubor selhal) se nepoužije nikdy;
3. byla spočtena **verzí algoritmu**, kterou toto sestavení pro daný druh má;
4. všechna nastavení výpočtu se shodují **přesně** (velikost FFT, okno, překryv, průměrování, trackování, pásmo a další);
5. soubor s měřením má stále **stejnou velikost v bajtech**;
6. požadovaný kanál a každý požadovaný řád v souboru je;
7. byla spočtena v **aktuální jednotce** kanálu (viz [Fix Unit](topic:units/intro));
8. když soubor obsahuje dva kanály stejného jména, uložená křivka pochází ze stejného kanálu (stejný index).

Pokud cokoli chybí, celý požadavek se spočte normálně -- uložená a čerstvá data se nikdy nemíchají. Když vyhovuje víc sad, vyhrává ta uložená se **všemi kanály**, potom nejnovější.

Na čem **nezáleží**:

- nastavení, která mění jen to, jak se výsledek *kreslí*: amplituda RMS/Peak, formát spektra, dB škála, barevná škála spektrogramu ([Formát amplitudy](topic:shared/amplitude_format));
- seznam řádů u sady [řezů řádů](topic:order_tracking/orders): sada uložená s řády 1, 2, 4,5 zodpoví požadavek na řád 2. (Residual je jiný: závisí na celém seznamu řádů, takže potřebuje stejný.)
- **jméno, umístění a čas změny** souboru: přejmenovaný nebo zkopírovaný soubor výsledky zachová; porovnává se jen jeho velikost.

### Kdy se výsledek zneplatní

Žádný časovač ani příkaz „obnovit“ neexistuje; uložený výsledek prostě přestane odpovídat:

| Co se stalo | Důsledek |
|---|---|
| změnilo se nastavení výpočtu | jiný požadavek, shoda není; stará sada zůstává |
| soubor s měřením změnil velikost (znovu nahrán, upraven) | miss |
| opravila se jednotka kanálu | miss pro daný kanál |
| DSP daného druhu se změnilo v novém vydání Spectra | miss jen pro daný druh; ostatní druhy zůstávají platné |
| sada je *partial* | nepoužije se nikdy |

Sada, která už neodpovídá, zůstává na disku, dokud ji nenahradíte. Uložení se stejným nastavením jako existující sada nabídne její **přepsání**: nové soubory se zapíšou vedle starých a na konci se vymění, takže zrušený nebo neúspěšný běh nechá starou sadu nedotčenou. Když se po výměně nepodaří uložit projekt, vrátí se zpět projekt i složky.

### Komprese

*Result cache compression* -- **None** (nejrychlejší, výchozí), **lzf** (rychlá), **gzip** (nejmenší) -- platí jen pro to, co se zapíše **příště**. HDF5 přečte každou variantu, takže stávající sady zůstávají čitelné a smíšené sady jsou v pořádku.

### Bezpečné smazat

Cache jsou odvozená data. `cache/index.json`, který umožňuje hledání zamítnout kandidáty bez otevření jediného souboru HDF5, se znovu vytvoří z manifestů, kdykoli chybí nebo je zastaralý. Smazání složky sady výsledků ztratí jen tento výpočet. Sady zapsané staršími vydáními Spectra (jeden soubor HDF5 na sadu) se dál čtou.

### Scan cache

Odděleně od výsledků: pro každou datovou složku drží `cache/scan/` přečtený soupis kanálů a metadata, takže opakovaný sken znovu čte jen soubory, jejichž velikost nebo čas změny se změnily. Cache zapsaná starším formátem se zahodí. Smazání stojí jen nový sken a nic víc (opravy jednotek jsou v projektu, ne tady). Projekt bez souboru drží scan cache v dočasné oblasti počítače (`NVH_Tool\untitled_scan`); ty starší než 14 dní se při startu odstraní.
