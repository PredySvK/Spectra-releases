# Graph Rendering

**Graph Rendering** určuje, jak se kreslí jednorozměrné [křivky v grafech](topic:graphs/intro). Řidší kreslení a vykreslení jen viditelné části křivky může usnadnit posun a přiblížení dlouhých záznamů. Volby mění jen obraz; o použití celého signálu v analýze pojednává [Surová data](topic:raw_data/intro).

## Způsob kreslení křivek

Otevřete okno **Settings** ozubeným kolem v titulkovém pruhu a vyberte stránku **Graphic › Graph Rendering**.

| Nastavení | Co dělá |
|---|---|
| **Enable downsampling** | Sníží počet kreslených bodů. Zrušením zaškrtnutí vypnete prořeďování u křivek, na které se nastavení použije. Ovládání **Automatic (matches monitor width)** a **Manual factor** se tím znepřístupní. |
| **Automatic (matches monitor width)** | Volí faktor prořeďování podle viditelného rozsahu osy X a šířky grafu. Mění se při přiblížení a změně velikosti; aktuální vykreslovač PyQtGraph míří přibližně na pět vzorků na obrazový bod. |
| **Manual downsampling factor** | Nastaví faktor seskupení od **2** do **10 000**. Větší faktor vykreslí méně skupin vzorků. Vykreslovač zachová nejvyšší a nejnižší bod skupiny, aby byly vidět vrcholy. |
| **Render screen only** | Omezí kreslení křivky na právě viditelný rozsah osy X, což může snížit práci při prohlížení části dlouhého záznamu. Ořezává pouze tehdy, když má osa X pevný zobrazený rozsah; při automatickém rozsahu X zůstávají v kreslení všechna data X. Původní data křivky zůstávají zachována. |

**Výchozí:** Enable downsampling zapnuto, vybrané Automatic (matches monitor width), Manual factor 10 a Render screen only zapnuto. Ruční faktor se použije jen při volbě **Manual factor**.

**Other curves opacity** nastavuje, jak viditelné zůstanou ostatní křivky, když je zapnutý [Highlight](topic:tools/cursor): 0 % je skryje, 100 % je neztlumí (výchozí 25 %). Je to stejná hodnota jako **Other curves opacity (Highlight)** v dialogu nastavení Cursoru; změna na jednom místě se projeví i na druhém.

## Použití a zapamatování voleb

Kliknutím na **Apply** uložíte preference a použijete je na křivky, které jsou už otevřené v aktuálním workspace. Změna pokryje všechny otevřené grafy křivek v tomto workspace včetně křivek na druhé ose Y. Do workspace jiného okna nezasahuje. **Revert** zahodí nepoužité úpravy; **Close** se při zbývajících úpravách zeptá, co s nimi.

Volby se ukládají do nastavení aplikace, takže zůstanou zachovány po restartu Spectra a platí napříč projekty. Nejsou součástí [souboru projektu](topic:general/projects). Velikost, umístění a poslední stránka okna Settings se pamatují zvlášť.

## Grafy otevřené později

Slovo *Defaults* má důležitou výjimku: automatické prořeďování a ořezávání na obrazovku se zapíná jen u křivek s **více než 20 000 body X**, kde se vyplatí; kratší křivky se kreslí celé. Volby na této stránce je mohou jen vypnout: s vypnutým **Enable downsampling** nebo **Render screen only** zůstane daná volba vypnutá i u dlouhé křivky, také po změně velikosti nebo překreslení. Chování dlouhých záznamů popisuje [Dlouhé záznamy](topic:raw_data/intro#dlouhé-záznamy).

Tato pravidla ovlivňují vykreslení; neodstraňují vzorky signálu ani nemění výsledek analýzy.
