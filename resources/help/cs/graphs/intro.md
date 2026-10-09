# Prohlížení a ovládání grafů

V kartě grafu lze zobrazit několik křivek současně. Myší si přibližte oblast, kterou chcete prozkoumat, a pak se vraťte k celému záznamu. Název grafu také vysvětluje, když se křivka skryje, protože nemůže sdílet osy grafu.

## Posun a přiblížení

- **Posun:** tažením levým tlačítkem myši posunete zobrazení.
- **Přiblížení:** kolečkem myši nad grafem přiblížíte oblast kolem ukazatele. Podržíte-li pravé tlačítko myši a pohybujete myší, mění se měřítko osy X i Y současně.
- **Zobrazit vše:** klikněte pravým tlačítkem do grafu a vyberte **View All**. Můžete také najet ukazatelem do grafu a po zobrazení kliknout na tlačítko automatického měřítka **A** v levém dolním rohu.

Tažení uvnitř grafu posouvá zobrazení. Chcete-li stejný kanál přidat do jiného grafu, přetáhněte ho ze seznamu kanálů v Exploreru na cílový graf.

## Porovnání křivek

Dvojklikem na několik vybraných kanálů v Data Poolu otevřete všechny v jednom porovnávacím grafu. Porovnávací graf je druhu aktivní analytické záložky a obsahuje totéž, co by dalo otevření kanálů jednoho po druhém: křivky [Overall Level](topic:overall_level/intro) v *Overall Level*, u každého kanálu všechny řády uvedené v pásu karet v *[Order Tracking](topic:order_tracking/intro)*, [spektra](topic:spectrum/intro) v *Spectrum 1D* a [časové signály](topic:raw_data/intro) v *Project* a ostatních záložkách. *[Spectrogram 2D](topic:spectrogram/intro)* obsahuje jeden kanál, proto otevře první a ostatní vypíše System Log. [Importované řezy řádů](topic:import/formats) smíchané s jinými kanály se otevřou jen v *Order Tracking*, jinde se přeskočí s upozorněním. Kanál, jehož soubor nemá [tacho](topic:shared/tracking), je odmítnut chybou v logu a ostatní kanály se přesto otevřou; nový porovnávací graf, do kterého se nic nenačetlo, se znovu zavře. Kanál můžete přidat i přetažením z Exploreru na existující graf. Graf může obsahovat více křivek, ale má jedinou doménu osy X. Křivky s jinou veličinou X se zobrazí jen tehdy, když pro ně aplikace zná přesný převod. Například křivku řádu lze zobrazit proti frekvenci, pokud je znám řád; časovou křivku nelze umístit na frekvenční osu. Název grafu upozorní na křivky, které se na aktuální osu X nehodí.

Aktivním grafem je vybraná karta pracovního prostoru. Akce pásu karet, které pracují s grafem, používají tuto kartu a mohou vyžadovat určitý typ analýzy. Před jejich použitím vyberte kartu grafu, se kterou chcete pracovat.

## Osy a legenda

Frekvenci lze na ose zobrazit v Hz nebo RPM a lze to přepnout ([jednotka osy X](topic:units/intro)).

Nastavení vykreslování křivek popisuje [Graph Defaults](topic:settings/graph_defaults). Načítání uložených křivek do aktivního grafu najdete v [Result Poolu](topic:results/intro).

Informace při najetí myší a zvýraznění vybrané křivky popisuje [Kurzor a zvýraznění](topic:tools/cursor).
