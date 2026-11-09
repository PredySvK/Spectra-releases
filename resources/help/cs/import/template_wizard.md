# Import wizard

Tabulkový soubor (`.xlsx`, `.txt`, `.csv`) se čte přes **Import template**: ta říká, kde jsou záhlaví, které sloupce jsou křivky a jak kanál dostane jméno, řád a metadata z okolních textů. Když žádná šablona vašim souborům nesedí, průvodce ji vytvoří z jednoho nebo více vzorových souborů. Šablona se uloží do vaší knihovny; vzorové soubory se nikdy nemění.

Záložka *[Project](topic:general/projects)* → **Import Templates…** → **New…** → vyberte jeden nebo více vzorových souborů stejného druhu. **Edit…** otevře průvodce na vzorku s už načtenou vybranou šablonou.

Průvodce má čtyři kroky, pojmenované v řádku nahoře, a dál pustí, jen když je krok úplný. Mezi kroky se chodí tlačítky **Next** (Alt+Right) a **< Back** (Alt+Left); červený řádek vedle tlačítek říká, co chybí. Příklady níže používají sešit MASTA s order cuts.

## 1. Samples and what it is

![Krok 1](wizard_samples.cs.png)

- **Add files…** přidá další vzorky. Více vzorků ukáže, co se mezi soubory mění, a průvodce nabídne i ostatní soubory stejné přípony ve složce. Vzorek jiné přípony se odmítne s udáním důvodu.
- **Data kind** říká, co křivky jsou: order cut, spektrum, Overall Level, order residual nebo časový signál. Průvodce to odhadne a uvede buňku, ze které odhadoval.
- **Origin**, **Values** a **Amplitude in the file** soubor neřekne, proto začínají bez odpovědi (červená hvězdička) a **Next** zůstává vypnuté, dokud neodpovíte. Špatná odpověď by změnila čísla bez jakéhokoli znamení. Values *In dB* se ptají na referenční úroveň; *From the header* se nabízí, jen když hlavička amplitudy říká Peak, RMS nebo Peak-to-Peak.
- **Channel type**: *Automatic* se řídí jednotkou.
- Časový signál se ještě ptá, odkud je čas (první sloupec, pevná vzorkovací frekvence, nebo text vybraný v kroku 3).

## 2. Table

![Krok 2](wizard_table.cs.png)

Náhled pod nastavením ukazuje list; barvy jsou vysvětleny pod ním.

- **Headings**: řádek záhlaví se najde podle textu první buňky (funguje, když se pozice mezi soubory liší), nebo podle čísla. Klikem na **číslo řádku** v náhledu ho posunete; další klik nastaví první datový řádek.
- **Sheets**: které listy se čtou: všechny (list bez řádku záhlaví se přeskočí), prvních N, bez posledních N, nebo vyjmenované. Textový soubor listy nemá, ale ptá se na kódování, oddělovač a desetinný znak, zobrazené jako zjištěné.
- **Columns**: *X/Y pairs*, *Shared X* (jeden sloupec X, mnoho Y) nebo *One curve per sheet*. Rozložení, které průvodce odhadl, je označeno.
- **Units**: zjištěné z hlaviček; jednotku X nebo amplitudy přepíšete, když jsou hlavičky špatně nebo chybí. Konflikt je napsán červeně.

## 3. Texts → roles

![Krok 3](wizard_roles.cs.png)

Každý text kolem křivky (buňky záhlaví, jméno listu, souboru a složky) se rozdělí na **čipy**. Čip může hrát roli: **Channel name**, **Axis**, **Order**, nebo pole **Metadata**. Průvodce sloty nejdřív vyplní podle toho, jak se čipy mezi kanály mění; sloty ukazují vybraný kanál.

- **+ Pick** aktivuje slot, pak klikněte na buňku záhlaví (nebo na text *Sheet* / *File* / *Folder* nad náhledem) a vyberte čip. Esc výběr zastaví. Bez aktivního slotu klik nabídne každou roli pro každý čip.
- Jméno se skládá z čipů v pořadí textu: čip přesunete tažením, **✕** ho z jména vyjme, pravé tlačítko ho rozdělí. Osa je uzamčený poslední čip; je-li i ve jménu, upozornění to řekne.
- **Order** bere čip, nebo jedno číslo zadané pro všechny kanály.
- Čip s rolí je v buňce označen pruhem v barvě role (dvě role, dva pruhy).
- Tabulka pod náhledem ukazuje, co z rolí vyjde u každého kanálu. Klik na řádek vybere kanál; **Problem** říká, co selhává.

## 4. Check and save

![Krok 4](wizard_check.cs.png)

- **Template name** a **File name pattern** (které soubory šablona čte, např. `*.xlsx`). Jméno vestavěné šablony se odmítne.
- Tabulka vypisuje každý kanál, který šablona čte, s řádem, jednotkami a počtem bodů.
- **Advanced** obsahuje volitelnou kontrolu duplicitních křivek (stejný kanál a řád s rovnými hodnotami po převodu na RMS) s volbou ponechat jednu z nich. Běží jen na prvním vzorku.
- **Save** zapíše šablonu do vaší knihovny a přidá s ní soubory. Vestavěnou šablonu lze uložit jen pod novým jménem (**Save as**). Když byl průvodce otevřen na šabloně projektu, tlačítko je **Apply to project**, případně **Overwrite** / **Save as new**.

Viz také: [Import dat](topic:import/intro), [Podporované formáty](topic:import/formats).
