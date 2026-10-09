# Jednotky

Spectra drží každé číslo v jednotce, ve které bylo měření nahráno, a převádí jen to, co se *zobrazuje*. Pod „jednotkami“ se skrývají tři oddělené věci:

| Co | Kde | Kde se ukládá | Čeho se týká |
|---|---|---|---|
| **Zobrazované jednotky** (osa Y) | záložka *Settings*, **Unit Settings** | aplikace (všechny projekty) | osa hodnot grafů a [tabulka Evaluation](topic:evaluation/intro) |
| **Jednotka osy X** | záložka *Settings*, **View** | otevřený projekt | každá osa frekvence a otáček |
| **Jednotka kanálu** (oprava) | [Data Pool](topic:data_management/intro), **Fix Unit** | projekt | jeden kanál a vše, co se z něj počítá |

## Zobrazované jednotky

**Unit Settings** nabízí jednu jednotku pro každou fyzikální oblast:

| Oblast | Na výběr | Výchozí |
|---|---|---|
| Lineární zrychlení | g, m/s&sup2;, mm/s&sup2; | g |
| Akustický / kapalinový tlak | Pa, bar, mbar | Pa |
| Elektrické napětí | V, mV | V |
| Otáčky / frekvence | rpm, Hz, rad/s | rpm |

Kanál patří do oblasti podle svého **typu kanálu**: akcelerometr, mikrofon, napětí nebo tacho (jak se typ zjišťuje: [Formáty](topic:import/formats)). Kanál jiného typu (síla v N, teplota) se nikdy nepřevádí. Volba se pamatuje v aplikaci, ne v projektu, a **Reset All Settings** vrátí výchozí hodnoty.

### Jak se hodnota převádí

Převod je jeden skalární faktor $k$ mezi jednotkou kanálu a zvolenou jednotkou, použitý na hodnoty křivky. Nic se nepřepočítává -- žádné FFT, žádné trackování -- takže změna je okamžitá.

- **Časový signál a lineární spektrum** (`g RMS`, `g Peak`): $y' = k\,y$.
- **Výkon a PSD** (`(g)^2`, `(g)^2/Hz`): $y' = k^2\,y$, protože veličina je umocněná.
- Popisek se přepíše na novou jednotku: `m/s2 RMS`, `(m/s2)^2/Hz` a podobně.

Pevné vztahy: 1 g = 9,80665 m/s&sup2;; 1 m/s&sup2; = 1000 mm/s&sup2;; 1 bar = 1000 mbar = 10<sup>5</sup> Pa; 1 V = 1000 mV; 1 Hz = 60 rpm = 2&pi; rad/s. V oblasti otáček znamená frekvence v Hz *otáčky za sekundu*, proto je 1 Hz rovný 2&pi; rad/s, a ne 1 rad/s.

Nemožný převod (neznámý řetězec jednotky) hodnoty nechá beze změny a zapíše varování do System Logu.

### Co se překreslí

**Apply &amp; Save Units** přeškáluje z nedotčených dat každého grafu:

- otevřené grafy **[Time](topic:raw_data/intro)** a **[Spectrum](topic:spectrum/intro)**;
- tabulku **Evaluation**, která zobrazované jednotky sleduje ([Evaluation](topic:evaluation/intro));
- strom [Data Pool](topic:data_management/intro).

Grafy [Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) a [Overall Level](topic:overall_level/intro) se změnou *nepřeškálují*; novou jednotku převezmou při příštím vykreslení křivky.

## Jednotka osy X

**Native**, **Hz** nebo **RPM**. Je to vlastnost otevřeného [projektu](topic:general/projects) a ukládá se s ním (projekt bez záznamu se otevře jako Native).

- **Native**: každý graf si nechá svou osu -- [spektra](topic:spectrum/intro) v Hz, [řezy řádů](topic:order_tracking/orders) a [Overall Level](topic:overall_level/intro) proti otáčkám v RPM, čas v s.
- **Hz**: osa otáček (RPM) se kreslí v Hz, $f = \text{rpm}/60$.
- **RPM**: osa frekvence (Hz) se kreslí v RPM, $\text{rpm} = 60\,f$. Spektrogram se řídí oběma svými osami.

Jde jen o přeškálování zobrazení. Nic se neprojektuje: řez řádu zůstává křivkou proti otáčkám hřídele, jen se čte v Hz. Čas se nikdy nepřeškálovává. Přepnutí jednotky v projektu Untitled se na uložení neptá; v projektu se souborem ho označí jako změněný.

### Jedna doména X na graf

Graf má jednu veličinu osy X (čas, frekvence nebo otáčky). Křivka s jinou nativní veličinou se nakreslí, jen když existuje přesný převod. Jediný je **řez řádu &rarr; frekvence**: křivka na pevném řádu $o$ proti otáčkám se umístí na

$$f = \frac{o\cdot \text{rpm}}{60}$$

bod po bodu, bez interpolace. Jakákoli jiná neshoda (časový signál v grafu spektra) se nekreslí.

## Dvě jednotky v jednom grafu

Křivky stejné oblasti sdílejí levou osu bez ohledu na vlastní jednotku: křivka v m/s&sup2; vložená do grafu v g se převede na g. Křivka jiné oblasti (mikrofon v Pa v grafu akcelerometru) dostane vlastní **pravou osu Y**; obě osy se zoomují společně.

## Fix Unit

Soubor někdy uvádí špatnou jednotku (akcelerometr uložený jako `V`, nebo `g` u dat v m/s&sup2;). **Fix Unit** v kontextové nabídce kanálu v Data Pool ji opraví pro jeden kanál nebo celý výběr. Seznam nabízí nejdřív jednotky stejné oblasti, potom všechny ostatní.

- Oprava se ukládá **do projektu**, po měření a kanálu. Soubor s měřením se nikdy nemění; oprava se použije znovu při každém čtení složky.
- Mění to, co se počítá, takže uložený výsledek spočtený před opravou se pro daný kanál **nepoužije** ([Projekty a cache](topic:general/projects)).
- Bez datové složky projektu, ke které by se oprava připojila, platí jen pro aktuální sezení; System Log to řekne.
