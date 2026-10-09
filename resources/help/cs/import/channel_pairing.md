# Párování kanálů

Párování říká programu, že měřený a simulovaný kanál jsou stejné fyzické místo, a lze je tedy porovnat. Sloupec *Measured* nabízí všechny kanály všech souborů [`.unv`, `.uff`, `.asc` a `.txt`](topic:import/formats). Sloupec *Simulated* nabízí výsledky MASTA.

## Záložka Pairing

Záložka *[Project](topic:general/projects)* → **Metadata and Filter Settings** ([Metadata z Excelu](topic:import/metadata)) → **Pairing**.

![Záložka Pairing](channel_pairing.cs.png)

- Vyberte kanál na každé straně a stiskněte **Pair ↓**. **Remove Selected** páry maže.
- **Remaining only** (ve výchozím stavu zapnuto) skryje už spárované kanály a drží obě strany odděleně. Vypnuto, oba seznamy ukazují všechny kanály.
- Každý seznam má vyhledávání. **Link** (výchozí vypnuto) použije text z levého hledání na oba.
- Kanál se páruje 1:1 a nelze ho spárovat sám se sebou.

## channel_pairing.xlsx

Páry jsou uloženy v `channel_pairing.xlsx` ve [složce projektu](topic:general/projects): list `ChannelPairs`, sloupce *Measured channel* a *Simulated channel*. Při otevření projektu se vytvoří prázdný a přepíše se po potvrzení dialogu. Je-li otevřený v Excelu, uložení selže s radou zavřít jej. Lze jej i ručně upravit.

Kanál se zapisuje jako `název:směr`, např. `Inverter_Cover:X`. Označení čtečky (`Set #3: `, `Col #1 [MICROPHONE]: `, `Time for `) se ignoruje. Směr je koncové `X`, `Y` nebo `Z` za `:` nebo `_`, s volitelným znaménkem, takže `Inverter_Cover:+X` a `Inverter_Cover:-X` jsou týž kanál. Kanály `.asc` směr nemají.

Řádek napůl prázdný, opakující kanál nebo párující kanál se sebou samým se přeskočí a důvod se zapíše do logu. Ostatní řádky se načtou.
