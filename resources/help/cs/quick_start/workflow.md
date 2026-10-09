# Postup krok za krokem

Stejných osm kroků platí pro každý druh měření.

1. **[Projekt](topic:general/projects).** Na záložce *Project* stiskněte **New** pro prázdný projekt (nebo **Open** pro existující).
2. **[Přidání dat](topic:import/intro).** Stiskněte **Add Data Directory** a vyberte složku s měřeními. Objeví se na záložce *Data Pool* v Exploreru, seskupená podle test setupu a měření.
3. **[Pohled na surový signál](topic:raw_data/intro).** Při aktivní záložce *Project* dvakrát klikněte na kanál v Data Poolu. Otevře se jako časový signál v nové záložce workspace. Před analýzou zkontrolujte, že vypadá rozumně.
4. **Výpočet.** Přepněte na analytickou záložku ([Overall Level](topic:overall_level/intro), [Order Tracking](topic:order_tracking/intro), [Spectrogram 2D](topic:spectrogram/intro) nebo [Spectrum 1D](topic:spectrum/intro)), nastavte [velikost FFT](topic:shared/fft_size) a [okno](topic:shared/windows) a dvakrát klikněte na kanál. Více vybraných kanálů se otevře v jednom srovnávacím grafu. Po změně nastavení stiskněte **Refresh**. **[Compute Batch](topic:batch/intro)** udělá totéž pro celou složku a výsledek uloží do [Result Poolu](topic:results/intro).
5. **[Filtrování](topic:filtering/intro).** V doku *Filters* odškrtněte hodnoty, které nechcete vidět (např. jeden kanál). Graf tyto křivky skryje. **Filter Data Pool** zúží stejným způsobem strom Data Poolu; **Show all** vypne všechny filtry, aniž by zapomněl váš výběr.
6. **[Vytažení maxim](topic:evaluation/intro).** Otevřete záložku *Evaluation* v doku *Output* dole. Zvolte **Max** pro nejvyšší hodnotu každé křivky, nebo **Top-N maxima**, **Typed orders**, **Dominant orders**. Tabulka uvádí každou hodnotu i s pozicí na ose X.
7. **Export.** Stiskněte **Export CSV** na záložce [Evaluation](topic:evaluation/intro), nebo vyberte řádky, stiskněte Ctrl+C a vložte je do tabulky.
8. **[Uložení](topic:general/projects).** Na záložce *Project* stiskněte **Save**. Otevřené grafy, filtry a nastavení se po novém otevření projektu vrátí.

![Kam kliknout v jednotlivých osmi krocích](workflow_steps.cs.png)
