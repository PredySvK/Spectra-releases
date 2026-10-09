# Selections

**Selection** pojmenovává skupinu měření a kanálů podle jejich hodnot v aktuálním [Data Poolu](topic:data_management/intro). Použijte ji k opakovanému vykreslení stejné skupiny bez vybírání jednotlivých kanálů. Query Selection se při použití znovu vyhodnotí nad poolem, takže může zahrnout i později přidaná měření, která odpovídají podmínkám.

## Vytvoření Selection

V Exploreru otevřete **Selections** a stiskněte **Create Selection**. Zadejte název a zaškrtnutím hodnot v tabulce určete, která měření a kanály odpovídají výběru. Každý zobrazený sloupec je jedna podmínka: zaškrtnuté hodnoty v jednom sloupci představují alternativy, omezení v různých sloupcích se kombinují. U nové Selection ponechte ve sloupci zaškrtnuté všechny hodnoty, má-li zůstat otevřený i pro nové hodnoty v budoucích měřeních. Hodnota **(Empty)** umožňuje zahrnout měření, která v daném poli nemají hodnotu.

Například v help demo zvolte pouze `Healthy` ve sloupci Condition a `Motor_HSG` a `Bearing_HSG` ve sloupci Channel. Odpovídají oba zvolené kanály z měření Healthy; měření Damaged a kanál akustického tlaku se vynechají.

![Editor Selection s ukázkovým pravidlem a živým počtem](selection_editor.cs.png)

V tabulce jsou zpočátku dostupné sloupce pro kanál, identitu a kategoriální metadata. Tlačítkem **Configure…** zvolíte, které sloupce editor zobrazuje; konfigurace sloupců je společná pro editory Selection v projektu. Sloupce [Result Set, Order, Analysis type a Parameter Set](topic:filtering/intro) zde nejsou k dispozici. Tabulka průběžně ukazuje počet odpovídajících měření a různých názvů/směrů kanálů, nikoli všechny výskyty kanálů ve všech souborech. Například stejné dva kanály v osmi měřeních zde stále znamenají dva kanály. Tlačítko **OK** lze použít, když je název platný a odpovídá alespoň jedno měření. Tlačítkem **Cancel** zavřete dialog bez uložení Selection.

## Úprava, přejmenování nebo smazání

Klikněte pravým tlačítkem na Selection v seznamu a zvolte **Edit…**, **Rename…** nebo **Delete…**. Při úpravě můžete změnit zaškrtnuté hodnoty; název je v editoru pevný. Přejmenování je samostatná akce. Název musí být jedinečný a nesmí být **Whole Data Pool**, což je vyhrazený název pro celý pool.

Před smazáním program požádá o potvrzení. Pokud Selection používá některý workflow, potvrzovací dialog tyto workflow vypíše; po smazání budou ve stavu **Not ready**, dokud jejich vstup nenastavíte na dostupnou Selection. Přejmenování zároveň upraví vstupy workflow, které odkazují na původní název.

Selections patří do [projektu](topic:general/projects). Uložte projekt, aby se změny zachovaly i po jeho příštím otevření.

## Vykreslení Selection v grafu

Dvojklikem na Selection v seznamu **Selections** otevřete její kanály v nové kartě workspace. Selection můžete také přetáhnout na otevřený [graf](topic:graphs/intro) a přidat do něj její kanály. Při vykreslení se Selection vyhodnotí nad aktuálním Data Poolem. Pokud v něm nemá žádný kanál dostupný k vykreslení, nic se nepřidá. Při více než 50 výskytech kanálů napříč měřeními program požádá o potvrzení vykreslení všech.

Graf dostane vyhodnocené kanály a na Selection nezůstává navázaný. Pozdější úprava Selection již vykreslené kanály v grafu nezmění.

> **Selection** zde znamená uloženou Measurement selection. Liší se od **Filter selection**, která řídí viditelnost již existujících křivek v grafu. Viz [Filtrování](topic:filtering/intro).
