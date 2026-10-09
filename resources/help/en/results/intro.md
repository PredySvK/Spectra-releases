# Result Pool

The **Result Pool** lists saved result sets in the current project. A result set contains computed curves in the project's [result cache](topic:general/projects). Loading one puts those stored curves onto the focused graph so you can compare them with curves already there; it does not run the analysis again.

## Choose a graph and load sets

Focus the [graph](topic:graphs/intro) tab you want to use, then open the Result Pool in the Explorer. The header names the graph that will receive checked sets. Check a result set to load it, or check a **Result Kind** heading to load all readable sets in that group. A partly checked heading means some, but not all, of its sets are loaded in this graph.

Result Pool controls are available only when a regular graph is focused. With a spectrogram or the Home Workspace focused, the result list remains visible but is disabled. [Spectrograms](topic:spectrogram/intro) show one colour map rather than a list of comparison curves. Only result kinds made of curves can be loaded into a graph; other kinds are skipped with a warning.

Reading the cache runs in the background as **Load Result Sets** [jobs](topic:jobs/intro). A checked set stays checked while its read is pending, and checking it again does not submit a duplicate read. You can uncheck it while it is loading; the pending result is then discarded instead of being added later. If a read fails or is cancelled from Jobs, the pending check state is cleared. If a set would load more than the default 500 curves, the app asks **Load many curves?** before reading it; choose **Yes** to continue.

Loading may add several curves per source channel for an order result set. A curve already present from a live computation is adopted into the set instead of being drawn twice.

## Parameter Set labels

Each set row shows its label, **Parameter Set** number, and source count. Parameter Sets (used as a [filter column](topic:filtering/intro)) group result sets with the same result kind and computation settings. Numbers follow the first occurrence of each distinct computation in the project’s result-set list; they are not permanent IDs. Order lists, algorithm versions, and display-only options do not create separate Parameter Sets. A dash means the set is not assigned a Parameter Set.

## Unload without deleting

Uncheck a set or its Result Kind heading to remove that set's curves from the focused graph. This only changes the graph contents: it does not delete the saved result set from the project or erase its cache files. Curves not associated with the unchecked set remain in the graph. A live curve adopted into that set is removed with it. The saved set stays in the Result Pool and its cache files are left intact.

## Missing result files

If the project still lists a result set but its cache file is missing, the row is shown in grey with a warning icon and cannot be checked. The tooltip explains that the file is missing. Recompute and save the set to make its curves available again.

## Save and restore

Save the project to keep which result sets are loaded on each open graph. When you reopen the project, its graph tabs and checked sets are restored; the curves are read from the saved cache again. The set's stored data remains in the Result Pool whether or not it is currently loaded on a graph.

See also [Compute Batch](topic:batch/intro), [Graphs](topic:graphs/intro), and [Projects and result cache](topic:general/projects).
