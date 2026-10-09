## 📊 Vyhodnocení: Max

Evaluation vytáhne z křivek fokusovaného grafu <b>Single values</b> -- jedno číslo, které vyhodnocení extrahovalo z jedné křivky, spolu s tím, kde na křivce leží -- např. "3.2 g RMS při 4500 rpm, Acc1 Z, run_014.unv". Evaluation table níže je všechny Single values, které aktuální vyhodnocení vytvořilo, jeden řádek na křivku.

<b>Max</b> je nejjednodušší vyhodnocení: nejvyšší platná hodnota každé viditelné křivky a její poloha, bez jakéhokoli nastavení. Vždy vrátí přesně jeden řádek na křivku -- nikdy žádný, nikdy víc než jeden.

- <b>Amplituda (RMS vs. Peak):</b> Hodnoty se počítají v nativní [jednotce](topic:units/intro) kanálu. Přepínání mezi zobrazením RMS a Peak probíhá bez přepočtu vyhodnocení. <b>Peak = &radic;2 &times; RMS</b> představuje amplitudu sínusu se stejnou energií, nikoli skutečné maximum raw časového signálu. Hlavička sloupce Value vždy nese aktivní jednotku a režim.
- <b>Formát (Linear / Power / PSD):</b> Pro spektrální křivky přepíná formát zobrazení pomocí sdílené tabulky škálování ([Formát amplitudy](topic:shared/amplitude_format)) bez přepočtu vyhodnocení. Vypnuto, pokud nejsou přítomna spektra.
- <b>Jednotky:</b> Tabulka respektuje globální nastavení jednotek (např. g &harr; m/s²). Poloha maxima (at X) se při žádném přepnutí nemění.
- <b>Třídění:</b> Kliknutím na záhlaví libovolného sloupce lze řadit. Čísla se řadí číselně; prázdné řádky „&mdash;" zůstávají vždy na konci při vzestupném i sestupném řazení.
- <b>Kopírování a export CSV:</b> Tlačítko Kopírovat nebo Ctrl+C zkopíruje tabulku (či vybrané řádky) do schránky (oddělené tabulátory s hlavičkou pro Excel). Tlačítko Export CSV uloží tabulku do CSV souboru.
- <b>Columns&hellip; (Sloupce):</b> Výběr metadatových a identifikačních sloupců zobrazených v tabulce Evaluation (Identity, Raw metadata, Excel metadata, Calculated metadata). Nabízeny jsou pouze aktivní pole schématu (povolená v Metadata Editoru). Vybrané sloupce se pamatují pro každý dok i po uložení a otevření projektu. Číselné sloupce se řadí numericky a prázdné buňky zůstávají při řazení vždy dole.
- <b>„&mdash;" (pomlčka):</b> Křivka bez jediné platné hodnoty -- řádový řez celý pod frekvenčním rozlišením nebo nad Nyquistovou frekvencí souboru -- přesto dostane řádek, jen prázdný. Pomlčka neznamená vyřazenou křivku.
- <b>Které křivky:</b> Max čte [řádové řezy](topic:order_tracking/orders), [spektra](topic:spectrum/intro) a křivky [Overall Level](topic:overall_level/intro). [Spektrogram](topic:spectrogram/intro) (2D mapa, ne křivka) a [časový graf](topic:raw_data/intro) nenabízejí Maxu nic, takže karta místo prázdné tabulky zobrazí hlášku.
- <b>Respect Trace filter:</b> Ve výchozím stavu zapnuto -- tabulka pokrývá jen křivky, které graf právě zobrazuje (vlastní maska Trace filtru grafu). Vypnutím se vyhodnotí každá křivka, kterou dok drží, včetně těch, co maska skrývá. Pamatuje se zvlášť pro každý dok. Viz [Filtrování](topic:filtering/intro).
