# Supported formats

A file is picked up by its suffix: `.unv`, `.uff`, `.asc`, `.xlsx`, `.txt` (case does not matter). `.xlsx` and `.txt` are too common to trust, so they count as measurements only when their header is recognised. [`metadata.xlsx`](topic:import/metadata), a README or your notes are ignored.

| Suffix | Format | What it holds | Kind |
|---|---|---|---|
| `.unv`, `.uff` | Universal File Format, dataset 58 | [time waveforms](topic:raw_data/intro) | measured |
| `.asc` | Siemens Testlab ASCII | [time waveforms](topic:raw_data/intro) | measured |
| `.txt` | tab-separated processed measurement | [order curves](topic:order_tracking/intro) against speed | measured |
| `.xlsx` | MASTA result workbook | [order curves](topic:order_tracking/intro) against speed | simulated (paired via [Channel pairing](topic:import/channel_pairing)) |

## .unv / .uff

Only **dataset 58** is read, one channel per dataset; other datasets are skipped. A dataset must be a *time response* (function type 1). A spectrum or FRF dataset is listed, but refuses to open with a message.

| Field | Read from |
|---|---|
| Channel name | ID line 1 (ID line 5 when line 1 is empty) |
| Unit | ordinate axis unit label (record 10) |
| Time start, time step | abscissa minimum and increment (record 8) |
| Sampling rate | 1 / time step |
| Number of points | record 8 |
| Response and reference node and direction | record 6 |
| ID lines 1–5 | kept as raw metadata (setup description, date and time, creation timestamp, run section, hardware label) |

Function type 5 marks a tacho channel; otherwise the type comes from the unit and name (see *Channel type*). Binary files with evenly spaced real data are read directly. ASCII datasets, complex data and uneven spacing take a slower path with the same result.

## .asc

A header block between `BEGIN` and `END` lines, then one row per sample with values separated by commas or whitespace. The file is read as UTF-8.

| Header line | Meaning |
|---|---|
| `START = <s>` | time of the first sample |
| `DELTA = <s>` | time step |
| `RATE = <Hz>` | sampling rate; replaces `DELTA` when it comes later in the header and is above 0 |
| `CHANNELNAME = ['a', 'b', ...]` | one name per column |
| `UNIT = ['g', 'Pa', ...]` | one unit per column |

The first column is a time vector when its name is `time`, `elap_time`, `time1`, `sec` or `s`, or its unit is `s` or `sec`; it is then not a channel. Otherwise time is built from `START` and `DELTA`. The number of samples is the number of non-empty data rows. A row whose column count differs from the header is an error.

## .txt (processed measurement)

First line: `(rev/s)`, then one `name (unit)` cell per channel, separated by tabs. Every following line is a speed in rev/s and one value per channel. Speed is converted to rpm (× 60). A `_H<n>` ending of the file name (for example `Run_H3.txt`) sets the [order](topic:order_tracking/orders) of the curves.

## .xlsx (MASTA)

First sheet. Every channel is a pair of columns (speed, amplitude):

| Row | Content |
|---|---|
| 1 | `<axis>, At housing: <design>\<location>`, which gives the channel `<location>:<axis>` |
| 2 | result type, with `Order <n>` and `Damping = <x>` |
| 3 | scenario |
| 4 | `Speed (rev/min)` and `Amplitude (<unit>)` |
| 5… | rpm and amplitude (numbers or text, decimal comma accepted) |

Design, scenario, damping and the remaining comma-separated parts of row 2 become [raw metadata](topic:import/metadata) (*Design*, *Scenario*, *Damping*, *Description 1…*). The order belongs to the [curve](topic:order_tracking/orders).

## Channel type

The unit decides first: `g` and `m/s²` give an accelerometer, `Pa`, `mbar` and `bar` a microphone, `rpm`, `Hz` and `rad/s` a tacho. For an ambiguous unit (`V`, `mV`, none) words in the channel name decide (acc, tacho, mic…), and `V`/`mV` with no hint is a voltage channel. Anything else is a general dynamic channel. The type steers defaults such as DC removal.
