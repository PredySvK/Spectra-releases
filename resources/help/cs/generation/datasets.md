# Testovací datasety

**Realize Test Dataset** zapíše celý opakovatelný syntetický soubor měření do zvolené složky. Výsledkem jsou měření Siemens ASC ([Podporované formáty](topic:import/formats)), doplněná tabulkou metadat v Excelu a u jednoho datasetu také tabulkou párování kanálů. Data můžete použít k prozkoumání analytického postupu bez vlastní přípravy měření.

## Výběr datasetu

Na záložce *Project* otevřete ve skupině *Tools* **Realize Test Dataset**. V poli **Dataset:** vyberte dataset a potom zvolte výstupní složku. Výběr nabízí ID datasetů; jednotlivá měření v něm vybírat nelze. Zapíše se celý dataset. Aktuální knihovna obsahuje:

| Dataset | Obsah |
|---|---|
| `engine_degradation_v1` | 25 měření: pět běhů představujících 0 až 20 000 cyklů, každý s pěti průběhy otáček. Šest vibračních kanálů měří zrychlení a akustický tlak, vedle nich je kanál tacha. Signály se mezi běhy mění, takže lze porovnávat průběh degradace. |
| `help_demo_v1` | 8 měření: běhy Healthy a Damaged, každý s pomalým a rychlým rozjezdem i doběhem. Dataset má dva akcelerometrické kanály, jeden kanál akustického tlaku a kanál tacha. Signály obsahují řády, rezonance, postranní pásma a chirp 500–3 000 Hz, které se hodí k prozkoumání grafů a nastavení analýzy. |

Předvolený je první identifikátor datasetu. Dialog výběru výstupní složky začne v aktuální aktivní složce, pokud je nastavená. Zrušením kteréhokoli výběru nebo odmítnutím potvrzení se úloha nespustí. Potvrzovací okno ukáže počet zapisovaných souborů měření a upozorní, že soubory se stejnými názvy budou přepsány.

## Zápis a přidání měření

1. Vyberte dataset a výstupní složku.
2. Přečtěte upozornění na přepsání a potvrďte **Yes**.
3. Počkejte na dokončení úlohy na pozadí. Protokol uvede počet zapsaných měření a názvy souborů tabulek. Pokud se úloha zastaví nebo zápis selže, mohou ve výstupní složce zůstat již zapsané soubory; aplikace ohlásí neúplný dataset a soubory nevrací zpět.
4. Chcete-li měření analyzovat, přidejte zvolenou výstupní složku přes **Add Data Directory** ([Import dat](topic:import/intro)). Prohledání najde měření v podsložkách a načte odpovídající metadata datasetu. Vytvoření datasetu jej do aktuálního [Data Poolu](topic:data_management/intro) nepřidá automaticky.

## Doprovodné tabulky

V kořeni výstupní složky se vytvoří `metadata.xlsx`. Jeho list **Measurements** obsahuje jeden řádek pro každý soubor ASC, spárovaný přes **File Name** (název souboru bez `.asc`), a údaje o konfiguraci, průběhu otáček, rychlostech, době trvání a seedu. List `help_demo_v1` má také sloupec **Condition** s hodnotou `Healthy` nebo `Damaged`. Pokud stejný soubor popisuje projektová i tato složka metadat, přednost má řádek z projektu. Jak aplikace páruje excelová metadata s měřeními a zpřístupňuje je, popisuje [Metadata z Excelu](topic:import/metadata).

Dataset `help_demo_v1` vytvoří také `channel_pairing.xlsx` s ukázkovou dvojicí `Motor_HSG` a `Bearing_HSG`. Oba kanály jsou v tomto generovaném datasetu ASC; řádek je ukázkou párování, nikoli tvrzením, že jedno měření je simulované. Aplikace čte aktivní tabulku párování ze složky, ve které leží [projektový soubor](topic:general/projects) (`.nvhproject`). Pokud máte projekt jinde, zkopírujte do jeho složky vytvořený sešit, chcete-li toto párování použít. Viz [Párování kanálů](topic:import/channel_pairing).

Soubory datasetu používají pevné seedy, takže opakované vytvoření stejné verze knihovny dává stejné soubory ASC. Sešit metadat `engine_degradation_v1` obsahuje také list **Order Map** s popisem simulovaných vlastností a změn tacha. Help demo tento list nemá.
