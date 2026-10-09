# Benchmark

Benchmark měří, jak dlouho Spectra čte měření, počítá analýzy a ve variantě Full je také vykresluje na obrazovku. Zaznamená počítač a rozdělí každý běh na kroky, takže můžete porovnat počítače nebo verze aplikace a najít, kde se čas spotřebuje. Benchmark měří rychlost; neověřuje správnost analýzy.

## Výběr varianty

Otevřete záložku **Settings** a zvolte **Run Benchmark…**. Dialog má zpočátku vybranou variantu **Full**.

| Varianta | Co měří |
|---|---|
| **Full** | Otevře skutečné okno aplikace, přejde na každou analýzu kliknutím na její záložku v ribbonu, spočítá výsledek a počká, až se dokončí vykreslení obrazovky. Zahrnuje tedy i cenu vykreslení. Vícekanálový případ Spectrogram nebo Overall Level se přeskočí, protože tyto záložky pro více kanálů neotevřou srovnávací graf. |
| **Headless** | Načte soubor a spustí analýzu přímo, bez Qt a bez vykreslení grafu. Použijte ji k porovnání výpočtu bez vykreslování na obrazovce. Zvládne vícekanálové případy u všech čtyř analýz. |

Obě varianty používají stejný plán a vytvoří Benchmark report. Full běží v samostatném procesu, takže hlavní aplikace zůstane responzivní. Spustí prázdný projekt a oddělené dočasné nastavení; nepřidává výsledky do otevřeného [projektu](topic:general/projects) ani jeho [Result Poolu](topic:results/intro).

## Výběr souborů

Pole **Plan** určuje plán TOML. Jeho seznam souborů se zobrazí pod **Files**. **Add from Data Pool** přidá všechny právě načtené soubory měření z [Data Poolu](topic:data_management/intro) bez duplicit; použije tedy celý načtený pool, ne jen zvýrazněné řádky. **Add file…** otevře výběr souboru (první filtr je UNV, viz [Podporované formáty](topic:import/formats); dostupné jsou i **All files**). Soubory můžete změnit také v plánu.

Zaškrtnutím **Generated reference signal** přidáte deterministické ukázkové měření: rozjezd dlouhý 75 sekund se vzorkovací frekvencí 25,6 kHz, 16 měřicími kanály a kanálem tacha. Spectra ho podle potřeby vytvoří jako soubor ASC v systémové dočasné složce a platný soubor znovu použije. Tento soubor je oddělený od projektu a vstupních měření.

Dodávaný `benchmark_plan.toml` je upravitelný výchozí plán. Upravte v něm cesty v `files` podle svého počítače. Plán také vybírá analýzy, počty kanálů a nastavení, která se mají měnit. Benchmark case je kombinace jednoho vstupního souboru, analýzy, počtu kanálů a nastavení DSP. Nastavení `base` platí pro případy; `sweep` mění `nfft` a `rpm_step`. V režimu `sweep` se každé nastavení mění zvlášť kolem hodnoty `base`; v režimu `product` se zkombinují všechny uvedené hodnoty. Každá analýza použije jen nastavení, která podporuje. Ostatní položky plánu určují počet `repeats` a časový limit `timeout_s` pro jeden případ.

## Quick a opakované běhy

**Quick** je ve výchozím stavu zaškrtnuté. Každý případ spustí jednou a ignoruje hodnoty `sweep` v plánu; použije pouze `base`. Pokud ho odškrtnete, spustí kombinace z režimu sweep nebo product a každý případ zopakuje tolikrát, kolik uvádí `repeats` (nejméně jednou). První běh se vykazuje zvlášť; další běhy shrnuje jejich medián. Uvidíte tak první, „studenější“ běh vedle opakovaných běhů, které už používají načtenou cestu k souboru a výpočtu.

## Porovnání s baseline

Pomocí **Compare with…** vyberte předchozí Benchmark report ve formátu JSON. Nový report doplní časové rozdíly u případů, které lze spárovat. Kladná Δ znamená, že aktuální běh trval déle než baseline; záporná Δ znamená kratší dobu. Případy přítomné jen v jednom reportu jsou uvedené bez časového rozdílu. Reporty s různým zobrazovacím backendem, například Headless a Full, se neporovnávají, protože měří odlišnou práci.

## Spuštění a zastavení

Zvolte **Output folder** a stiskněte **Run**. Ukazatel průběhu se posune po dokončení každého případu. Stisknutím **Stop** ukončíte Benchmark proces; přerušený běh nemusí vytvořit report. Případ může také skončit se stavem `skipped`, `error` nebo `timeout`. Například analýzy sledující otáčky ([tracking](topic:shared/tracking)) se přeskočí, když soubor nemá kanál tacha. Ve Full se přeskočí i vícekanálové případy [Spectrogram](topic:spectrogram/intro) a [Overall Level](topic:overall_level/intro) popsané výše. Časový limit platí pro jeden případ včetně jeho opakování; pokud práce po časovém limitu stále běží, následující případy se přeskočí.

Když nelze načíst plán nebo běh selže, dialog zobrazí chybový výstup. Opravte plán nebo cestu ke vstupu a spusťte Benchmark znovu. Benchmark reporty se zapisují až po dokončení běhu.

## Čtení reportu

Markdown report se po úspěšném běhu zobrazí v dialogu; tlačítkem **Open folder** otevřete složku s ním a s JSON reportem. Každý report se jmenuje `benchmark_<machine>_<time>.md` a `.json`. Složka se podle potřeby vytvoří. Výchozí složkou je `docs/perf` ve zdrojovém checkoutu a uživatelská složka Spectra `perf` v nainstalované aplikaci.

Report zaznamenává informace o počítači, softwaru a disku se vstupními daty a poté uvádí nastavení a stav každého případu. U úspěšných případů ukazuje první běh a při opakování také medián dalších běhů. Tabulka kroků obsahuje:

- **wall ms** — uplynulý skutečný čas kroku;
- **CPU ms** — procesorový čas procesu a všech jeho vláken během kroku. Při práci na více jádrech může převýšit wall time;
- **share** — wall time kroku jako podíl z celého běhu případu;
- **peak RAM MB** — špičku rezidentní paměti procesu vzorkovanou během kroku.

Kroky se mohou překrývat nebo běžet na více vláknech, proto jejich podíly mohou dohromady překročit 100 %. Celkový wall time případu zahrnuje celý měřený běh; dílčí hodnoty pomáhají najít, kde čas vzniká. RAM je špička procesu, ne paměť přiřazená pouze danému kroku.

Viz také [Spectrum](topic:spectrum/intro), [Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) a [Overall Level](topic:overall_level/intro), kde je popsáno, co jednotlivé analýzy počítají.
