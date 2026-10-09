# Graph Defaults

**Graph Defaults** určuje, jak se kreslí jednorozměrné [křivky v grafech](topic:graphs/intro). Řidší kreslení a vykreslení jen viditelné části křivky může usnadnit posun a přiblížení dlouhých záznamů. Volby mění jen obraz; o použití celého signálu v analýze pojednává [Surová data](topic:raw_data/intro).

## Způsob kreslení křivek

Na záložce **Settings** klikněte na **Graph Defaults**. Dialog se jmenuje **Default Graph Throughput Settings**.

| Nastavení | Co dělá |
|---|---|
| **Enable Downsampling** | Sníží počet kreslených bodů. Zrušením zaškrtnutí vypnete prořeďování u křivek, na které se nastavení použije. Ovládání **Automatic Optimization** a **Manual Decimation Factor** se tím znepřístupní. |
| **Automatic Optimization (Matches Monitor Width)** | Volí faktor prořeďování podle viditelného rozsahu osy X a šířky grafu. Mění se při přiblížení a změně velikosti; aktuální vykreslovač PyQtGraph míří přibližně na pět vzorků na obrazový bod. |
| **Manual Decimation Factor:** | Nastaví faktor seskupení od **2** do **10 000**. Větší faktor vykreslí méně skupin vzorků. Vykreslovač zachová nejvyšší a nejnižší bod skupiny, aby byly vidět vrcholy. |
| **Render Screen Only Data (Evict Hidden Points)** | Omezí kreslení křivky na právě viditelný rozsah osy X, což může snížit práci při prohlížení části dlouhého záznamu. Ořezává pouze tehdy, když má osa X pevný zobrazený rozsah; při automatickém rozsahu X zůstávají v kreslení všechna data X. Původní data křivky zůstávají zachována. |

**Výchozí:** Enable Downsampling zapnuto, vybrané Automatic Optimization, Manual Decimation Factor 10 a Render Screen Only Data zapnuto. Ruční faktor se použije jen při volbě **Manual Decimation Factor**.

## Použití a zapamatování voleb

Kliknutím na **Save & Apply** uložíte preference a použijete je na křivky, které jsou už otevřené v aktuálním workspace. Změna pokryje všechny otevřené grafy křivek v tomto workspace včetně křivek na druhé ose Y. Do workspace jiného okna nezasahuje. **Cancel** zavře dialog bez použití nebo uložení změněných výkonnostních voleb.

Volby se ukládají do nastavení aplikace, takže zůstanou zachovány po restartu Spectra a platí napříč projekty. Nejsou součástí [souboru projektu](topic:general/projects). Velikost a umístění dialogu se pamatují zvlášť.

## Grafy otevřené později

Slovo *Defaults* má důležitou výjimku: automatické prořeďování a ořezávání na obrazovku se zapíná jen u křivek s **více než 20 000 body X**, kde se vyplatí; kratší křivky se kreslí celé. Volby z tohoto dialogu je mohou jen vypnout: s vypnutým **Enable Downsampling** nebo **Render Screen Only Data** zůstane daná volba vypnutá i u dlouhé křivky, také po změně velikosti nebo překreslení. Chování dlouhých záznamů popisuje [Dlouhé záznamy](topic:raw_data/intro#dlouhé-záznamy).

Tato pravidla ovlivňují vykreslení; neodstraňují vzorky signálu ani nemění výsledek analýzy.
