# Generování signálu

**Generate Debug Signal** vytvoří syntetický časový signál s více kanály pro zkoušení importu a analýzy. Nastavíte profil otáček a přidáte do každého kanálu složky signálu, v náhledu zkontrolujete aktivní kanál a potom záznam exportujete jako soubor Siemens Testlab ASC ([Podporované formáty](topic:import/formats)).

## Otevření generátoru

Na záložce **Project** zvolte ve skupině *Tools* **Generate Debug Signal**.

![Dialog Signal Generator](signal_generator.cs.png)

## Doba záznamu, vzorkování a seed

| Nastavení | Výchozí | Povolený rozsah | Co ovlivňuje |
|---|---:|---:|---|
| **Duration [s]** | 30 s | 0,1–1000 s po 0,01 s | Délka záznamu. Počet vzorků je celá část součinu doby a vzorkovací frekvence. |
| **Sampling [Hz]** | 10 000 Hz | 100–102 400 Hz po celých číslech | Vzorkovací frekvence všech kanálů i tacha. Frekvence nad polovinou této hodnoty se mohou aliasovat. |
| **Seed** | prázdný (`random`) | 0–2 147 483 647 | Seed generátoru náhodných čísel pro šum a šum tacha. Pevná hodnota umožní zopakovat stejný záznam se stejným nastavením. |

Je-li Seed prázdný, při exportu se vygeneruje nový seed (vždy v povoleném rozsahu) a zobrazí se ve zprávě o úspěchu; jeho zadáním do pole Seed a se stejným nastavením export zopakujete. Živý náhled používá vlastní pevný seed šumu, takže jeho šum se nepřizpůsobí seedu exportu. Při novém otevření dialogu se nastavení generátoru vrátí na výchozí hodnoty; předdefinovanou konfiguraci lze načíst přes **Load Preset…**. Dialog si zapamatuje velikost a polohu okna.

## Profil otáček

**Tacho Settings** určuje čistý profil otáček, ze kterého se počítají složky [řádu](topic:order_tracking/orders). **Start** má výchozí hodnotu 0 RPM a **Stop** 35 000 RPM; obě hodnoty lze nastavit od 0 do 100 000 RPM. **Direction** nabízí:

| Směr | Profil |
|---|---|
| **Ramp Up** | Roste od Start do Stop. |
| **Ramp Down** | Klesá od Stop do Start. |
| **Ramp Up & Down** | V první polovině záznamu roste od Start do Stop, ve druhé polovině se vrací na Start. |

![Nastavení tacha s úseky konstantních otáček a šumem](signal_generator_tacho.cs.png)

Výchozí profil je přímá rampa. Zaškrtnutím **Enable Plateaus** rozdělíte rampu na **Steps** (1–50, výchozí 3). **Plateau Ratio** (0,01–0,99, výchozí 0,5) je podíl každého kroku, po který se nová rychlost drží; zbytek zabere přechod k této rychlosti. Například 0,5 rozdělí čas kroku rovnoměrně mezi rampu a podržení rychlosti. Ovládací prvky kroků a poměru jsou dostupné jen při zapnutých úsecích konstantních otáček.

## Složky kanálu

Vyberte typ složky, zadejte hodnoty a stiskněte **Add Component**. Složky kanálu se sčítají. **Amp** je základní špičková amplituda sinusových složek **Order**, **Sine signal** a **Chirp**. U šumových složek nastavuje Amp směrodatnou odchylku výstupu. Hodnoty se vyjadřují ve zvolené [jednotce](topic:units/intro) kanálu.

| Typ | **Value** | **Amp** a další pole |
|---|---|---|
| **Order** | Řád od 0 do 100 000 | Sinusová vlna, jejíž frekvence sleduje otáčky: řád × RPM / 60. **Amp End** může její amplitudu lineárně zvýšit nebo snížit během záznamu. **Mod Ord** a **Mod Dep** přidávají amplitudovou modulaci a postranní pásma. **Res Hz** a **Amplif** přidávají rezonanční obálku závislou na otáčkách, když řád prochází rezonanční frekvencí. |
| **Sine signal** | Pevná frekvence v Hz, od 0 do 100 000 | Sinusová vlna s pevnou frekvencí nezávislou na otáčkách. **Amp End** lineárně mění amplitudu během záznamu. **Mod Ord** je modulační frekvence v Hz; **Mod Dep** je hloubka od 0 do 1. |
| **Chirp** | Počáteční frekvence v Hz, od 0 do 100 000 | Lineární frekvenční průběh od **Value** do **End Freq [Hz]** během záznamu, nezávislý na otáčkách. **Amp End** a modulace fungují stejně jako u pevné sinusové vlny. Amplification u Chirp není k dispozici. |
| **White Noise** | — | Bílý Gaussův šum; Amp nastavuje jeho směrodatnou odchylku. |
| **Pink Noise** | — | Šum s větším zastoupením nižších frekvencí a stejnou energií v každé oktávě; Amp nastavuje směrodatnou odchylku. |
| **Brown Noise** | — | Šum s výraznějším zastoupením nižších frekvencí než u pink noise; Amp nastavuje směrodatnou odchylku. |
| **Resonance** | — | Širokopásmový šum tvarovaný kolem **Res Freq [Hz]**. Amp nastavuje směrodatnou odchylku; **Q factor** určuje ostrost rezonance (hodnoty pod 1 se chovají jako 1). |

Při přidávání složky pomocí ovládacích prvků nad tabulkou omezují číselná pole **Value** na 0–100 000 (výchozí 1), **Amp** a **Amp End** na 0–1 000 000 (obě výchozí 1), **Mod Ord** na 0–100 000 (výchozí 0), **Mod Dep** na 0–1 (výchozí 0), rezonanční nebo koncovou frekvenci na 0–100 000 Hz (výchozí 0) a **Amplification** nebo **Q factor** na 0–100 (výchozí 1). Tyto limity platí pro číselná pole; buňky tabulky lze upravit také přímo. Zobrazená pole závisí na typu složky. U **Order** je **Res Hz** rezonanční frekvence v Hz a **Amplif** řídí rezonanční obálku; použije se pouze při frekvenci nad 0 Hz a Amplif větším než 1. U **Chirp** pole frekvence znamená koncovou frekvenci. U složky s **Amp End** změna **Amp** před přidáním složky mění také Amp End, dokud Amp End neupravíte přímo. Pokud mají **Mod Ord** a **Mod Dep** přidávat modulaci, musí být obě hodnoty větší než nula. Hloubka modulace násobí základní amplitudu hodnotou mezi 1 − hloubka a 1 + hloubka.

## Náhled kanálu

Graf **Tacho Profile** zobrazuje otáčky v čase. **Active Channel Vibration Preview** zobrazuje pouze zvolený kanál; jiný kanál zobrazíte přepnutím záložky. Jednotka svislé osy odpovídá jednotce kanálu. **X-Axis** přepne vodorovnou osu grafu vibrací mezi **Time** a **RPM**; graf tacha zůstává v čase. **Start [s]** a **End [s]** určují zobrazený časový úsek. **View All** zobrazí celý záznam. **View 4 period** vybere krátký úsek podle nejnižšího kladného řádu nebo sinusového signálu při aktuálním začátku úseku; periodu pro Chirp ani šum nepočítá.

Náhled se po změně nastavení aktualizuje. Používá čistý profil otáček: **Tacho Noise** ovlivňuje jen sloupec tacha v exportovaném souboru, ne náhled ani výpočet vibrací.

## Šum v exportovaném tachu

Zaškrtnutím **Tacho Noise** zpřístupníte jeho nastavení. **Jitter [rpm]** určuje směrodatnou odchylku přidaného Gaussova kolísání rychlosti (0–5 000 RPM). **Region** vybírá `all`, `start` nebo `end`; **Region frac** (0,01–1,00, výchozí 1,00) nastavuje část záznamu ovlivněnou jitterem na zvoleném konci. Při `all` jitter ovlivní celý záznam. **Dropout rate** (0–1, výchozí 0) je pravděpodobnost výpadku pro každý vzorek v celém záznamu bez ohledu na Region. Při výpadku se zaznamenaná rychlost násobí hodnotou **Dropout gain** (0–1, výchozí 0,5). Výsledné otáčky se oříznou na nulu. Změny se týkají pouze kanálu `Tacho_Master` v exportu; vibrační kanály dál používají čistý profil otáček.

## Načtení předvolby

Zvolte **Load Preset…**, vyberte **Dataset**, potom jednu z uvedených naměřených položek a potvrďte výběr. Předvolba nahradí současné nastavení generování včetně kanálů a složek. Zároveň nastaví náhled na celý záznam; zvolená osa náhledu zůstane beze změny. Načtené hodnoty můžete před exportem upravit. Výběr načte nastavení signálu jedné položky; nezapisuje celý dataset.

## Export souboru ASC

1. Nastavte záznam a zvolte **Export Signal**.
2. V dialogu uložení vyberte umístění a název souboru Siemens ASCII. Po zrušení dialogu se soubor negeneruje.
3. Aplikace záznam vytvoří a zapíše na pozadí. Po úspěšném dokončení vypíše počet vzorků a seed a přidá nový soubor ASC do *[Data Poolu](topic:data_management/intro)*.

Jedinou volbou **Export Format** je **ASC (Siemens Testlab)**. Soubor obsahuje časový sloupec, `Tacho_Master` v RPM a jeden vibrační sloupec pro každý kanál včetně jeho názvu a jednotky. Pokud název souboru nekončí `.asc`, přípona se doplní. Názvy kanálů obsahující čárku, hranatou závorku nebo apostrof nelze zapsat do hlavičky ASC a export selže; důvod se zobrazí v aplikačním logu.

Pokud nejvyšší frekvence řádu nebo pevného sinusového signálu (včetně kladného modulačního postranního pásma) překročí polovinu vzorkovací frekvence, zpráva o úspěchu zobrazí varování Nyquistovy frekvence. Soubor se přesto zapíše; varování upozorňuje, že se složka ve vzorkovaných datech bude aliasovat.

Celou knihovnu popisují [Testovací datasety](topic:generation/datasets). Při analýze exportovaného záznamu postupujte podle [Rychlého startu](topic:quick_start/workflow) a nejprve jej otevřete jako [surový signál](topic:raw_data/intro).
