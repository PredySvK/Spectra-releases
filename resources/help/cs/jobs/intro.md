# Úlohy na pozadí

Vše, čeho délka roste s daty -- výpočty, čtení měření, skenování složek, zápis sad výsledků -- běží na pozadí, takže okno zůstává použitelné. Hned běží jen krátké věci, které sami spustíte, třeba [uložení projektu](topic:general/projects) nebo čtení `channel_pairing.xlsx` ([Párování kanálů](topic:import/channel_pairing)).

## Kde úlohy vidíte

- **Stavový pruh** na konci levého sloupce dock oken ukazuje nejnovější běžící úlohu s ukazatelem postupu a tlačítkem **Cancel**, a `+N more`, když běží další. Když nic neběží, stojí tam **Idle**. Po skončení úlohy její výsledek (Done, Failed, Cancelled) chvíli zůstane na pruhu, pak se vrátí Idle. **Dvojklikem** otevřete záložku Jobs.
- **Záložka Jobs** (*Settings* &rarr; Panels &rarr; **Jobs**) vypisuje každou úlohu, nejnovější nahoře: **Job**, **Progress**, **State**, **Time**.

Úloha je fronta kroků: *Calculate &amp; Save Data* ([sada výsledků](topic:general/projects)) nad 40 měřeními je jedna úloha se 40 kroky a postupem `12/40`. Dlouhý jednotlivý krok (velká složka) posouvá ukazatel i mezi kroky. Uchovává se posledních 100 dokončených úloh.

### Stavy

| Stav | Význam |
|---|---|
| Queued / Running | čeká, nebo pracuje (s procenty) |
| Done | hotovo; `(N error(s))` znamená, že některé kroky selhaly, ale zbytek se zapsal |
| Failed | úloha jako celek nic nevytvořila |
| Cancelled | zastavili jste ji |
| Superseded | zastavena Spectrou, protože stejný úkol převzala novější úloha -- není to chyba |

*Done s chybami* je záměr: jeden nečitelný soubor nesmí připravit o ostatních třicet devět. Najeďte na řádek a uvidíte chybové zprávy (prvních deset); zůstanou tam, i když System Log už odrolovali.

**Superseded** nastane, když spustíte něco, co dělá běžící úlohu zbytečnou, například druhý požadavek na stejný graf dřív, než skončil první: nakreslí se jen poslední.

### Tiché úlohy

Hlídač složek znovu skenuje složku, kdykoli v ní přibude soubor. Takové **tiché** úlohy se nikdy nezmocní stavového pruhu; najdete je v záložce Jobs.

## Cancel

- **Cancel** na pruhu a **Cancel Selected** zastaví jednu úlohu; **Cancel All** všechny; **Clear List** odstraní dokončené úlohy z tabulky (běžící zůstanou).
- Cancel zabrání **dalším krokům** ve startu. (Dávky: [Compute Batch](topic:batch/intro).) Krok, který už běží, se nechá doběhnout a jeho výsledek se **zahodí**; dlouhé výpočty, které se průběžně ptají na zastavení, skončí dřív.
- Zrušený *Calculate &amp; Save Data* zahodí, co už zapsal, takže v projektu nezůstane rozdělaná sada výsledků.
- Zavření okna zruší všechny úlohy a počká až 2 sekundy, než skončí.

## Kolik najednou

Existují dvě dráhy, aby velká dávka nenutila grafy čekat:

- **Interactive** -- čtení a kreslení jednoho právě kliknutého kanálu: zhruba polovina vláken CPU (aspoň 2);
- **Batch** -- *Calculate &amp; Save Data* ([dávka](topic:batch/intro)) a skeny složek: všechna vlákna kromě jednoho.

Práce, u které záleží na pořadí, třeba plnění stromu Data Pool složku po složce, běží po jednom kroku.

## Selhání

Selhaný krok zapíše `ERROR: <úloha> -- <zpráva>` do System Logu a zbývající kroky úlohy pokračují.
