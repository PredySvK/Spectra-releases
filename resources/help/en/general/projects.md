# Projects and cache

A **project** (`*.nvhproject`) records every decision you made about a set of measurements. It never contains samples: the measurements stay where they are, and computed results live in a `cache` folder next to the project file.

## What a project holds

- the **data folders** ([Data Pool](topic:data_management/intro) roots) and an entry for every measurement file found there, with its metadata, unit corrections and test setup ([Importing data](topic:import/intro));
- the list of **result sets** that were computed and saved ([Result Pool](topic:results/intro));
- saved [selections](topic:selections/intro), workflows, **Filter cards** ([Filtering](topic:filtering/intro)) and the metadata schema ([Metadata](topic:import/metadata));
- the window layout, open tabs and the [X axis unit](topic:units/intro).

Not in the project: the display units (kept by the application) and the channel pairing, which is read from `channel_pairing.xlsx` ([Channel pairing](topic:import/channel_pairing)).

## Result cache

**Calculate &amp; Save Data** writes a **result set** (see [Result Pool](topic:results/intro)): a folder `cache/<name>/` with one HDF5 file per measurement and a small manifest `_set.json`. What you compute live by dropping a channel on a [graph](topic:graphs/intro) is *not* written there.

Later, when you drop a channel on a graph, Spectra first looks for a saved result that already answers the request, and draws it from disk instead of computing it. **Use cached results** (*Settings*, Cache group) turns this lookup off, so every request is computed; the choice is remembered by the application.

### When a saved result is reused

A result is reused only if **all** of these hold:

1. there is a result set of the same **kind** ([spectrum](topic:spectrum/intro), [spectrogram](topic:spectrogram/intro), [order cut](topic:order_tracking/orders), [Overall Level](topic:overall_level/intro)) that covers this measurement;
2. its status is **complete** -- a *partial* set (some channel or file failed) is never used;
3. it was computed by the **algorithm version** this build has for that kind;
4. every computation setting matches **exactly** (FFT size, window, overlap, averaging, tracking, band, and so on);
5. the measurement file still has the **same size in bytes**;
6. the requested channel, and every requested order, is in the file;
7. it was computed in the channel's **current unit** (see [Fix Unit](topic:units/intro));
8. when a file holds two channels with the same name, the stored curve came from the same channel (same index).

If anything is missing, the whole request is computed normally -- cached and fresh data are never mixed. When several sets qualify, the one saved with **all channels** wins, then the newest.

What does **not** matter:

- settings that change only how the result is *drawn*: amplitude RMS/Peak, spectrum format, dB scale, spectrogram colour scale ([Amplitude format](topic:shared/amplitude_format));
- the list of orders of an order-cut set: a set saved with orders 1, 2, 4.5 answers a request for order 2. (A Residual is different: it depends on the whole order list, so it needs the same one.)
- the file's **name, location and modification time**: a renamed or copied file keeps its results; only its size is compared.

### When it is invalidated

There is no timer and no refresh command; a saved result simply stops matching:

| What happened | Result |
|---|---|
| a computation setting changed | another request, no match; the old set stays |
| the measurement file changed size (re-recorded, edited) | miss |
| the channel unit was corrected | miss for that channel |
| the DSP of that kind was changed in a new Spectra release | miss for that kind only; other kinds stay valid |
| the set is *partial* | never used |

A set that no longer matches stays on disk until you replace it. Saving with exactly the same settings as an existing set offers to **overwrite** it: the new files are written beside the old ones and swapped in at the end, so a cancelled or failed run leaves the old set untouched. If saving the project fails after the swap, both the project and the folders are rolled back.

### Compression

*Result cache compression* -- **None** (fastest, default), **lzf** (fast), **gzip** (smallest) -- applies only to what is written **next**. HDF5 reads every variant, so existing sets stay readable and mixed sets are fine.

### Safe to delete

The cache is derived data. `cache/index.json`, which lets a lookup reject candidates without opening any HDF5 file, is rebuilt from the manifests whenever it is missing or stale. Deleting a result-set folder loses only that computation. Result sets written by older Spectra releases (one HDF5 file per set) are still read.

### Scan cache

Separate from results: for each data folder `cache/scan/` keeps the parsed channel inventory and metadata, so a rescan re-reads only files whose size or modification time changed. A cache written in an older format is discarded. Deleting it costs a re-scan and nothing else (unit corrections live in the project, not here). A project without a file keeps its scan caches in a temporary area of the PC (`NVH_Tool\untitled_scan`); those older than 14 days are removed at startup.
