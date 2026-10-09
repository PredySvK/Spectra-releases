# Kurzor

**Kurzor** přečte hodnotu z grafu přesně. Když je zapnutý, pohybujte myší nad [křivkovým grafem](topic:graphs/intro) nebo [spektrogramem](topic:spectrogram/intro): malé okno vedle myši ukáže bod pod ní -- bez odhadování z mřížky.

## Zapnutí

- Otevřete záložku **[Tools](topic:tools/intro)** a klikněte na box **Cursor** ve skupině **Cursors**, nebo
- stiskněte **C**, když má graf fokus (nejdřív na graf klikněte).

Přepínač je jedno nastavení pro **všechny** otevřené grafy. Dalším stiskem **C** nebo kliknutím na box kurzor vypnete. Kurzor je **ve výchozím stavu zapnutý**; box svítí modře, když je zapnutý, a je šedý, když je vypnutý. Cursor, Highlight i Pin si aplikace pamatuje i po restartu.

Box má dole v řadě tři malá kulatá tlačítka: **Cursor Settings** (ozubené kolečko, vlevo), **Highlight** (baterka, uprostřed) a **Pin** (vpravo). Zapnuté tlačítko je vyplněné tyrkysově; po najetí myší se zobrazí tooltip. Pin je dostupný, jen když je Cursor zapnutý.

![Box Cursor a jeho tlačítka na záložce Tools a okno kurzoru nad spektrem](cursor.cs.png)

## Co okno ukazuje

Na křivkových grafech se kurzor přichytí k nejbližšímu **skutečnému vzorku** nejbližší viditelné křivky -- naměřené hodnotě, nikdy interpolaci. „Nejbližší" se posuzuje na obrazovce v pixelech, takže to působí stejně bez ohledu na to, jak odlišná jsou měřítka X a Y. Vybere se jen křivka do zhruba **10 pixelů** od myši; nad prázdným místem okno není.

| Řádek | Význam |
|---|---|
| **Curve** | název křivky z legendy (křivkové grafy) |
| **X** | X vzorku (nebo čas / otáčky pod myší na spektrogramu) v jednotce osy |
| **Y** | hodnota vzorku (nebo frekvence na spektrogramu) s jednotkou zobrazení. V grafu se dvěma osami Y ([dvě jednotky v jednom grafu](topic:units/intro)) se u křivky na pravé ose píše **Y (Secondary)** |
| **Z** | amplituda pod myší na spektrogramu v zobrazené jednotce a barevné škále |
| **Amplitude** | **RMS** nebo **Peak** ([Formát amplitudy](topic:shared/amplitude_format)), má-li křivka takovou hodnotu |

Čísla mají 4 platné číslice; velmi malé (pod 0,001) nebo velké (od 100 000) hodnoty přejdou na vědecký zápis a hodnoty v dB mají jedno desetinné místo.

Zvažují se jen křivky, které právě vidíte: křivky skryté [filtrem Trace](topic:filtering/intro) nebo X doménou grafu se nikdy nevyberou, stejně jako [Band RMS](topic:tools/band_rms) Cursory.

### Spektrogramy

Při najetí myší na spektrogram se zobrazí nitkový kříž (crosshair) a Cursor Box s hodnotami X, Y a Z přesně pod kurzorem myši (bez přichytávání).
- **X** je čas nebo rychlost/RPM v zobrazené jednotce osy.
- **Y** je frekvence v zobrazené jednotce osy.
- **Z** je hodnota pixelu pod myší v aktuální barevné škále a jednotce (lineární fyzikální jednotka nebo dB).

Čáry kříže plynule sledují myš a skryjí se při opuštění spektrogramu nebo stisknutí tlačítka myši.

## Chování

- Okno plave vpravo dole od myši a u okraje grafu se překlopí na druhou stranu, takže se neuřízne.
- Zmizí, dokud je stisknuté tlačítko myši (posun, zoom, tažení [Band RMS](topic:tools/band_rms) Cursoru nebo křivky do jiného grafu), když myš opustí graf a když v dosahu není žádná křivka (nebo mimo spektrogram).

## Zvýraznění

**Highlight** je samostatný přepínač ve skupině **Cursors**, nezávislý na Cursoru. Je-li zapnutý, křivka pod myší (stejné pravidlo nejbližší křivky jako u Cursoru, do asi 10 pixelů) se vykreslí tlustěji a všechny ostatní křivky se ztlumí na asi 25 %. Zapnete jej tlačítkem **Highlight** nebo klávesou **H**, když má graf fokus.

Všechny křivky se vrátí do normálu, když myš opustí graf, vzdálí se od všech křivek, stiskne se tlačítko myši, graf se překreslí nebo se Highlight vypne.

## Pin

**Pin** (tlačítko ve skupině **Cursors**, nebo klávesa **P**, když má graf fokus) ukotví Cursor Box na místě: přestane sledovat myš, ale jeho obsah se dál aktualizuje podle polohy myši. Box přesunete tažením za něj samotný; tažení kdekoli jinde v grafu dál posouvá graf nebo přetahuje křivku do jiného grafu. Po odepnutí box zmizí, dokud se myš znovu nepohne.

## Nastavení kurzoru

Tlačítkem **Cursor Settings…** ve skupině **Cursors** vyberete, co box zobrazuje. Zaškrtněte pole, které se má zobrazit; jeho **Priority** (šipky nebo zadané číslo) je jeho řádek, 1 je nahoře. Sekce **Values** obsahuje X, Y, Z, název křivky a RMS / Peak; sekce metadat nabízejí pole označená **Use as Filter** v [Metadata and Filter Settings](topic:import/metadata), s hodnotami dané křivky (například Direction, File name nebo pole z Excelu).

Jeden seznam platí pro křivkové grafy i spektrogramy; pole, které se nehodí (Z na křivkovém grafu, metadata na spektrogramu), se přeskočí. Volba se ukládá pro **všechny projekty** a přežije restart. Metadatové pole, které otevřený projekt nemá, se v boxu jednoduše vynechá.

Vlevo dole nastavuje **Other curves opacity (Highlight)**, jak viditelné zůstanou ostatní křivky, když je zapnutý Highlight: 0 % je neviditelné, 100 % bez ztlumení (výchozí 25 %). Táhněte posuvník nebo hodnotu napište; ukládá se stejně jako seznam polí.
