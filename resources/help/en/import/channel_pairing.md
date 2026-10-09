# Channel pairing

Pairing tells the program that a measured channel and a simulated channel are the same physical point, so they can be compared. The *Measured* column offers every channel of every `.unv`, `.uff`, `.asc` and `.txt` file ([Supported formats](topic:import/formats)). The *Simulated* column offers the MASTA results.

## Pairing tab

*[Project](topic:general/projects)* tab → **Metadata and Filter Settings** ([Metadata from Excel](topic:import/metadata)) → **Pairing**.

![Pairing tab](channel_pairing.en.png)

- Pick a channel on each side and press **Pair ↓**. **Remove Selected** deletes pairs.
- **Remaining only** (on by default) hides channels that are already paired and keeps the two sides apart. Off, both lists show every channel.
- Each list has a search. **Link** (off by default) makes the left search text apply to both.
- A channel pairs 1:1 and cannot be paired with itself.

## channel_pairing.xlsx

The pairs are kept in `channel_pairing.xlsx` in the [project](topic:general/projects) folder: sheet `ChannelPairs`, columns *Measured channel* and *Simulated channel*. It is created empty when the project is opened and rewritten when you confirm the dialog. If Excel has it open, saving fails with a hint to close it. You can also edit it by hand.

A channel is written as `name:direction`, for example `Inverter_Cover:X`. The reader's label (`Set #3: `, `Col #1 [MICROPHONE]: `, `Time for `) is ignored. A direction is a trailing `X`, `Y` or `Z` after `:` or `_`, with an optional sign, so `Inverter_Cover:+X` and `Inverter_Cover:-X` are the same channel. `.asc` channels have no direction.

A row that is half empty, repeats a channel or pairs a channel with itself is skipped and the reason is written to the log. The other rows still load.
