# Metadata z Excelu

Tabulka může popisovat vaše měření (stav rotoru, teplotu oleje, číslo testu) a každý sloupec se stane něčím, podle čeho lze filtrovat.

## Tabulka

Stačí libovolný list se sloupcem **File Name**. Velikost písmen, mezery, `_` a `-` v jeho záhlaví nehrají roli a vyhrává první takový list. Jeden řádek na měření. Vše se čte jako text, takže `3000` zůstane `3000`. Koncové `.0` se odstraní a prázdná buňka znamená „bez hodnoty“.

Ukázkový `metadata.xlsx` vedle `Setup1-Sweep1-1_Processed.unv` (část sloupců vynechána):

| File Name | Setup | Spin cycle | Rotor unbalance | Spring | Max speed [rpm] | Spin direction | Oil temp |
|---|---|---|---|---|---|---|---|
| Setup1-Step1-1 | 1 | Step1 | Balanced | 200N | 35000 | Drive | 30 |
| Setup1-Step2-1 | 1 | Step2 | Balanced | 200N | 35000 | Reverse | 30 |
| Setup1-Sweep1-1 | 1 | Sweep1 | Balanced | 200N | 35000 | Drive | 30 |

## Kde tabulka leží

1. `metadata.xlsx` ve složce projektu (existuje po uložení projektu) má přednost.
2. `Metadata.xlsx` vedle dat, nebo ve složce, kterou jste vybrali, když jsou data v podsložkách, se použije jen pro soubory, které tabulka projektu nezmiňuje. Pokud obě tabulky popisují stejný soubor, vyhrává ta v projektu.

## Metadata jako filtr

Každý sloupec se stane polem v **Metadata and Filter Settings** (záložka *Project*). *Type* se odhadne z hodnot. Jediná odlišná hodnota udělá z celého sloupce text.

Chcete-li podle sloupce filtrovat, zaškrtněte u jeho řádku **Use as Filter** a potvrďte **Save & Apply Schema**. Pole se pak objeví v kartě Filters (přidáte ho tam přes *Configure Filters*, viz [Filtrování](topic:filtering/intro)): čísla se filtrují jako rozsah, text jako seznam hodnot k zaškrtnutí. Sloupce z Excelu začínají se zaškrtnutým **Active** i **Use as Filter**.

![Metadata and Filter Settings](metadata_editor.cs.png)

Okno má dvě karty. *Fields* uvádí všechna pole; **Active Status** určuje, zda lze pole zobrazit jako sloupec tabulky Evaluation (*Columns…*, viz [Evaluation](topic:evaluation/intro)), na filtrování nemá vliv; **Original Metadata Key** je záhlaví sloupce z vaší tabulky, **Custom Display Label Override** je název zobrazený v programu, **Type** přepíše odhadnutý typ. Level 1 jsou **surová metadata**, tedy to, co program čte ze samotného souboru měření ([Podporované formáty](topic:import/formats); signal domain, vzorkovací frekvence, jednotka a další); Level 2 jsou sloupce vaší Excel tabulky. Karta *Pairing* určuje, který měřený kanál patří ke kterému simulovanému: viz [Channel pairing](topic:import/channel_pairing).
