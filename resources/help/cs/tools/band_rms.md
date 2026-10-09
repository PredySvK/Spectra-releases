# Band RMS

Band RMS odečítá efektivní hodnotu signálu ve frekvenčním pásmu grafu **[Spectrum 1D](topic:spectrum/intro)**. Stínované pásmo má dva posuvné okraje; hodnota se při jejich posouvání průběžně aktualizuje.

## Zobrazení pásma

Na pásu karet *Spectrum 1D* zaškrtněte **Band RMS Cursors**. Ve výchozím stavu je políčko vypnuté. Pásmo se zobrazí na grafu, jehož záložka je právě vpředu, pokud obsahuje spektrum. Je-li aktivní jiný druh záložky, aplikace zapíše upozornění a pásmo tam nevykreslí.

Po prvním vykreslení spektra pokrývá výchozí pásmo 10 až 35 % jeho frekvenčního rozsahu. Tažením kteréhokoli okraje rozsah změníte. Tažením stínovaného pásma mezi okraji posunete celé pásmo a zachováte jeho šířku. Okraje zůstávají v zobrazeném rozsahu spektra.

![Pásmo Band RMS na spektru](band_rms.cs.png)

## Co hodnota měří

Hodnota se počítá ze **základní křivky** grafu, tedy ze spektra, které graf otevřelo. Další křivky přidané pro porovnání do stejné hodnoty nevstupují. Band RMS je vždy efektivní hodnota ve [fyzikální jednotce](topic:units/intro) kanálu, například g nebo Pa; nejde o zobrazenou hodnotu Peak spektra.

Výpočet integruje energii po binech spektra. Pokud okraj protíná bin, bin přispívá úměrně části své frekvenční šířky, která leží uvnitř pásma. Posun okraje uvnitř binu proto mění hodnotu plynule, místo aby se celý bin náhle započítal nebo vynechal. Odmocnina ze součtu energií je Band RMS.

Zapsáno vzorcem: $L_\mathrm{RMS}=\sqrt{\sum_k w_k E_k}$, kde $E_k$ je energie po binech ve čtverci jednotky kanálu a $w_k$ je podíl binu $k$ uvnitř pásma od 0 do 1. Například když jeden bin obsahuje 4 g² a ostatní jsou nulové, celé zahrnutí tohoto binu dá 2 g RMS; polovina dá $\sqrt{2}\approx1{,}414$ g RMS.

Formát spektra **Linear**, **Power** nebo **PSD**, volba amplitudy **RMS / Peak** a lineární či **dB** osa určují způsob zobrazení spektra. Výpočet Band RMS pro stejné spektrum nemění. Hodnota zůstává ve fyzikální jednotce kanálu a je označená RMS. Možnosti zobrazení spektra popisuje [Amplituda a Formát](topic:shared/amplitude_format).

V *Settings* → *View* přepíná **X axis unit** měřítko vodorovného zobrazení a popisky. Spektrum se počítá ve frekvenci; i když je osa zobrazená v RPM, pásmo zůstává uložené v Hz a před integrací se převede zpět. Změna tohoto zobrazení nemění měřený rozsah ani jeho hodnotu.

## Které křivky funkci podporují

Výpočet potřebuje 1D spektrum základní křivky. Časový signál, který spočítáte v **Spectrum 1D**, tuto podmínku splňuje. Předpočítaný importovaný výsledek, který už je křivkou řádu, například výsledek MASTA ([Podporované formáty](topic:import/formats)), je [řez řádem](topic:order_tracking/orders), nikoli spektrum, a pásmo Band RMS nemá. Pokud zobrazené spektrum nemá energii po binech binů, hodnota se zobrazí jako **Band RMS unavailable**.

## Co se ukládá

Políčko **Band RMS Cursors** se ukládá do nastavení aplikace odděleně od projektu a slouží jako předvolba pro nově vykreslená spektra. Přepnutí zobrazí nebo skryje pásmo pouze na právě aktivní záložce grafu; pásma na ostatních již otevřených grafech tím nepřepne.

Posunutý rozsah patří danému grafu, dokud je otevřený. Uložený [projekt](topic:general/projects) po otevření obnoví spektrum grafu, vlastní rozsah Band RMS však neukládá. Pokud je předvolba aplikace zapnutá, znovu otevřený graf začne s výchozím rozsahem.

Band RMS je jedno číslo z jednoho spektra. [Overall Level](topic:overall_level/intro) sleduje energii pásma v průběhu záznamu jako křivku. Nástroj pro odečítání jednotlivých bodů grafu popisuje [Cursor a Highlight](topic:tools/cursor).
