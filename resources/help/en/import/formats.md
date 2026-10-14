# Supported formats

A file is picked up by its suffix: `.unv`, `.uff`, `.asc`, `.xlsx`, `.txt`, `.csv` (case does not matter). `.xlsx`, `.txt` and `.csv` are too common to trust, so they count as measurements only when their header is recognised. [`metadata.xlsx`](topic:import/metadata), a README or your notes are ignored.

| Suffix | Format | What it holds | Kind |
|---|---|---|---|
| `.unv`, `.uff` | Universal File Format, dataset 58 | [time waveforms](topic:raw_data/intro) | measured |
| `.asc` | Siemens Testlab ASCII | [time waveforms](topic:raw_data/intro) | measured |
| `.txt` | tab-separated processed measurement | [order curves](topic:order_tracking/intro) against speed | measured |
| `.xlsx` | MASTA result workbook | [order curves](topic:order_tracking/intro) against speed | simulated (paired via [Channel pairing](topic:import/channel_pairing)) |
| `.csv` | ANSYS harmonic response | a first [order curve](topic:order_tracking/intro) against speed | simulated (paired via [Channel pairing](topic:import/channel_pairing)) |

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

Every sheet named `H<n>` (for example `H1`, `H4.79`, `H22`) is read; other sheets are skipped. A workbook without such sheets is read from its first sheet. In the Data Pool the channels are listed under their sheet. Every channel is a pair of columns (speed, amplitude):

| Row | Content |
|---|---|
| 1 | `<axis>, At housing: <design>\<location>`, which gives the channel `<location>:<axis>` |
| 2 | result type, with `Order <n>` and `Damping = <x>` |
| 3 | scenario |
| 4 | `Speed (rev/min)` and `Amplitude (<unit>)` |
| 5… | rpm and amplitude (numbers or text, decimal comma accepted) |

Design, scenario, damping and the remaining comma-separated parts of row 2 become [raw metadata](topic:import/metadata) (*Design*, *Scenario*, *Damping*, *Description 1…*). The order belongs to the [curve](topic:order_tracking/orders).

## .csv (ANSYS harmonic response)

One file per Design point and node, named `DP<n>_Freq_Resp_<channel>.csv` (for example `DP0_Freq_Resp_B0_HSG_inner_Acc_Y.csv`). Any other `.csv` in the folder, such as a Bearing Probe export, is skipped.

| Line | Content |
|---|---|
| 1 | `Frequency [Hz],Amplitude [<unit>]` |
| 2… | frequency and amplitude |

Every line may be wrapped in double quotes. A `˛` in the unit is read as `²` (`mm/s˛` → `mm/s²`). A row that is not two numbers is dropped; the frequency steps may be uneven.

- The channel is named `<channel>`, unchanged, so it pairs by the same name in [`channel_pairing.xlsx`](topic:import/channel_pairing). A trailing `_X`, `_Y` or `_Z` gives the direction.
- The curve is [order](topic:order_tracking/orders) 1 against rpm = 60 · frequency: an unbalance load acts at the rotation frequency.
- **ANSYS amplitudes are peak by default.** When you add the files the program asks whether the amplitude is RMS or Peak (see *Source amplitude* below); peak is divided by √2, so the curve is RMS like every computed order curve. Do not convert them again; the Peak/RMS display switch works on them as usual.
- `DP<n>` becomes [raw metadata](topic:import/metadata) *Design point*.

What a Design point means (rotor unbalance, spring…) goes into a `Metadata.xlsx` placed **in each result folder**, with `File Name` = `DP0`, `DP1`, … A `DP1` row describes `DP1_…` files, never `DP10_…`. Use the same column names and values as the measurement metadata (for example `Rotor unbalance` = `G2.5`) so the Trace filter shows the matching measurement and Design point together. Do not put `DP<n>` rows into the project's own `metadata.xlsx`: it takes precedence and would apply them to every result folder.

## Source amplitude

MASTA, processed measurement and ANSYS files carry a ready-made amplitude, and the file does not say whether it is RMS or Peak. When you add such files to the Data Pool, the program asks once per format (not per file) and shows the conversion it will apply: `RMS = Peak / √2`.

| Format | Default answer |
|---|---|
| MASTA | RMS |
| processed measurement | RMS |
| ANSYS | Peak |

- The answer is stored with each file in the project and is not asked again on Refresh or when the project is opened. New files that appear in a watched folder ask again.
- Cancel adds nothing to the pool. To correct a wrong answer, remove the file from the pool and add it again.
- Time signals (`.unv`, `.uff`, `.asc`) are never asked about: the program computes their amplitude itself.
- A project saved before the question existed keeps its curves unchanged (ANSYS Peak, others RMS).

## Channel type

The unit decides first: `g` and `m/s²` give an accelerometer, `Pa`, `mbar` and `bar` a microphone, `rpm`, `Hz` and `rad/s` a tacho. For an ambiguous unit (`V`, `mV`, none) words in the channel name decide (acc, tacho, mic…), and `V`/`mV` with no hint is a voltage channel. Anything else is a general dynamic channel. The type steers defaults such as DC removal.
