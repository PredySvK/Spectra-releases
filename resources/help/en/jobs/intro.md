# Background jobs

Everything whose duration grows with the data -- computing, reading measurements, scanning folders, writing result sets -- runs in the background, so the window stays usable. Only short things you start yourself, such as [saving a project](topic:general/projects) or reading `channel_pairing.xlsx` ([Channel pairing](topic:import/channel_pairing)), run at once.

## Where you see jobs

- **The status strip** at the foot of the left dock column shows the newest running job with a progress bar and a **Cancel** button, and `+N more` when others run. With nothing running it reads **Idle**. When a job ends, its outcome (Done, Failed, Cancelled) stays on the strip for a moment before it returns to Idle. **Double-click** it to open the Jobs tab.
- **The Jobs tab** (*Settings* &rarr; Panels &rarr; **Jobs**) lists every job, newest on top: **Job**, **Progress**, **State**, **Time**.

A job is a queue of steps: *Calculate &amp; Save Data* ([result set](topic:general/projects)) over 40 measurements is one job with 40 steps and the progress `12/40`. A long single step (a large folder) also moves the bar between steps. The last 100 finished jobs are kept.

### States

| State | Meaning |
|---|---|
| Queued / Running | waiting, or working (with the percentage) |
| Done | finished; `(N error(s))` means some steps failed but the rest was written |
| Failed | the job as a whole produced nothing |
| Cancelled | you stopped it |
| Superseded | stopped by Spectra because a newer job took over the same task -- not an error |

*Done with errors* is deliberate: one unreadable file must not lose the other thirty-nine. Hover a row to see the error messages (the first ten); they stay there after the System Log has scrolled past them.

**Superseded** happens when you start something that makes the running job pointless, for example a second request for the same graph before the first one finished: only the latest is drawn.

### Quiet jobs

The folder watcher re-scans a folder whenever a file lands in it. Such **quiet** jobs never take over the status strip; they are listed in the Jobs tab.

## Cancel

- **Cancel** on the strip and **Cancel Selected** stop one job; **Cancel All** stops every job; **Clear List** removes finished jobs from the table (running ones stay).
- Cancel stops **further steps** from starting. (Batch details: [Compute Batch](topic:batch/intro).) A step that is already running is allowed to end and its result is **dropped**; long calculations that check for the stop end sooner.
- A cancelled *Calculate &amp; Save Data* discards what it had written, so no half-finished result set is left in the project.
- Closing the window cancels all jobs and waits up to 2 seconds for them to end.

## How many at once

There are two lanes, so a big batch cannot make the graphs wait:

- **Interactive** -- reading and drawing one channel you just clicked: about half of the CPU threads (at least 2);
- **Batch** -- *Calculate &amp; Save Data* ([batch](topic:batch/intro)) and folder scans: all threads but one.

Work for which the order matters, such as filling the Data Pool tree one folder after another, runs one step at a time.

## Failures

A failed step writes `ERROR: <job> -- <message>` to the System Log, and the remaining steps of the job carry on.
