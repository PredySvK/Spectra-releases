# Compute a result set for a batch

**Compute Batch** is the button at the end of each analysis tab. It opens **Compute Result Set**, where you choose the channel scope and, for *Order Tracking*, the orders to calculate. The run then applies that tab’s current analysis settings to the measurements currently loaded in the *Data Pool* and saves the curves as a named result set.

## Choose the measurements first

Use **Add Data Directory** in the *Project* tab to add a folder to the [Data Pool](topic:import/intro). The batch dialog’s *Input Data* section only reports how many measurements are loaded; it does not let you choose a folder or a saved measurement selection. The batch uses the currently loaded measurements and their matching source files. To run a smaller batch, first load only the measurements you want in the Data Pool. [Saved selections](topic:selections/intro) in the Explorer are not inputs to this button; they do not restrict this batch.

The project must be saved before results can be written. If needed, the app asks to save it; cancelling that save cancels the batch. Before calculating, the app registers loaded pool folders that are not yet in the project. If no measurement is loaded, or the chosen channel scope matches no channels, the calculation is skipped and the reason is written to the System Log.

## Set channels and orders

In **Channels**, choose **Acceleration**, **Sound**, or **Acceleration + Sound** under **Type**. Then choose **All channels** or **Selected channels**. With **Selected channels**, use **Choose…** to open **Select Channels**; the list is built from the channels found in the loaded measurements and filtered by the selected type. Use **Select All** or **Select None** in that picker, then confirm with **OK**. If the selection is empty, the batch cannot start. Changing **Type** clears the remembered picked channel identities because the available list has changed.

The first defaults are **Acceleration** and **All channels**. The channel type and all/selected mode are remembered separately for each analysis tab. The picked identities are also remembered per tab. These preferences are saved when you press **Compute** in the dialog, not just by opening it.

Only *Order Tracking* shows **Orders to compute & save**. Enter positive [orders](topic:order_tracking/orders) separated by commas or semicolons; use a dot for a decimal, for example `1, 2, 4.5`. The field starts with the previously saved batch orders, or the live Order Tracking **Orders** setting if no batch value has been saved yet. Invalid or empty input disables **Compute**. Other analysis tabs use their current ribbon settings and do not show this field.

## Name and run the set

Optionally enter a **Result set name**. The preview shows how the name will be cleaned for use as a folder name; a name with no usable characters disables **Compute**. Leave the field blank to let the app create a name from the analysis settings and channel scope. If a name already exists, the app adds a suffix such as `_2` rather than silently replacing it.

Press **Compute** to start. **Cancel** in the dialog closes it without starting the run or saving the choices you just made. If an existing result set has exactly the same analysis settings, the app asks whether to **Overwrite**, **Save as New**, or cancel. **Overwrite** replaces that set while preserving its identity and name; **Save as New** creates another set; **Cancel** stops before calculation.

The analysis processes each chosen channel of each measurement in the loaded pool. A cancellation during calculation removes the in-progress result set, including shards already written, so it does not appear as a completed set. If some measurements or channels fail but others succeed, the successful results are saved with a *partial* status ([Projects and result cache](topic:general/projects)) and the failures are reported in the System Log. If none produce results, nothing is committed. The button’s status line reports when the set was saved or points you to the System Log.

## Find and load the results

A result set is stored beside the project in its `cache` directory: the set has a folder containing one HDF5 shard per measurement and a `_set.json` manifest. The project records the set and its analysis parameters. The *Result Pool* lists saved sets by result kind; check a set to load its curves into the focused graph. Unchecking it removes those set’s curves from that graph. A successfully committed batch saves the result-set record to the project automatically. Save the project after loading sets into graphs to preserve each graph’s loaded-set membership.

See also [Data Pool](topic:data_management/intro), [Result Pool](topic:results/intro), [Projects and result cache](topic:general/projects), and [Jobs](topic:jobs/intro).
