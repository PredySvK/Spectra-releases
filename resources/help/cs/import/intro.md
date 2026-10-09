# Import dat

Program čte měření ze souborů a nikdy je nemění. Složku přidáte tlačítkem **Add Data Directory** na záložce *Project*. Každý podporovaný soubor v ní (a při výběru nadřazené složky i v podsložkách) se objeví v [Data Poolu](topic:data_management/intro): jeden záznam na soubor, jeden kanál na signál.

Do importu vstupují tři věci:

| Co | Odkud | Stránka |
|---|---|---|
| **Signály** | soubory měření | [Podporované formáty](topic:import/formats) |
| **Excel metadata** | tabulka vedle dat | [Metadata z Excelu](topic:import/metadata) |
| **Páry kanálů** | tabulka, kterou píše záložka Pairing | [Párování kanálů](topic:import/channel_pairing) |

## Více složek a podsložky

- **Více složek.** **Add Data Directory** složku do Data Poolu *přidá*; složky, které už v něm jsou, zůstanou. Tlačítko tedy stisknete tolikrát, kolik složek chcete. V záložce *File Browser* lze také vybrat víc složek či souborů najednou (Ctrl/Shift) a z kontextového menu zvolit **Add … to Data Pool**.
- **Podsložky.** Vybraná složka se projde celá: načte se každá její podsložka, která přímo obsahuje měření (i ona sama). Výběr nadřazené složky tak dopadne stejně, jako kdybyste ručně vybrali všechny její podsložky s běhy. Pokud vedle sebe ve vybrané složce leží `Metadata.xlsx`, platí i pro podsložky, které nemají vlastní.
- **Vlastní popisek (Test Setup).** Měření lze zařadit pod vlastní popisek, který je nejvyšší úroveň stromu v Data Poolu. V *File Browseru* zvolte **Add and assign to Test Setup...**, v *Data Poolu* **Assign … to Test Setup...**: nabídne se existující popisek nebo napíšete nový název (prázdný popisek přiřazení zruší). Podsložky nalezené při výběru nadřazené složky dostanou popisek automaticky podle názvu své složky (např. `Run 00`); složce vybrané přímo se žádný nepřidělí. Popisek se ukládá do projektu, nikdy do měřicího souboru.

![Kontextové menu v File Browseru a výsledný Data Pool](import_to_pool.cs.png)

Čtení složky běží [na pozadí](topic:jobs/intro), okno zůstává použitelné. Soubor, který nejde přečíst, se přeskočí a důvod jde do logu.
