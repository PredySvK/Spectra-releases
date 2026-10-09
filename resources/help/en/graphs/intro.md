# Reading and navigating graphs

A graph tab can show several curves together. Use the mouse to inspect a region, then return to the full view when you need the whole measurement again. The graph title also explains when a curve is hidden because it cannot share the graph's axes.

## Move and zoom

- **Pan:** drag with the left mouse button to move the view.
- **Zoom:** turn the mouse wheel over the plot to zoom around the pointer. Hold the right mouse button and move the mouse to scale both the X and Y axes.
- **Show all:** right-click the plot and choose **View All**. You can also move the pointer over the plot and click the **A** autoscale button in its lower-left corner when it appears.

Dragging inside the plot pans the view. To add the same channel to another graph, drag it from the channel list in the Explorer onto the destination graph.

## Compare curves

Double-clicking several selected channels in the Data Pool opens them together in one comparison graph. The comparison graph is of the active analysis tab's kind and holds what opening the channels one by one would give: [Overall Level](topic:overall_level/intro) curves in *Overall Level*, every order listed in the ribbon for each channel in *[Order Tracking](topic:order_tracking/intro)*, [spectra](topic:spectrum/intro) in *Spectrum 1D*, and [time signals](topic:raw_data/intro) in *Project* and the other tabs. *[Spectrogram 2D](topic:spectrogram/intro)* holds one channel, so it opens the first and the System Log names the others. [Imported order cuts](topic:import/formats) mixed with other channels open only in *Order Tracking* and are skipped, with a warning, elsewhere. A channel whose file has no [tacho](topic:shared/tracking) is refused with an error in the log while the other channels still open; a new comparison graph nothing could be loaded into closes again. You can also drag a channel from the Explorer onto an existing graph to add it. A graph can contain multiple curves, but it has one X-axis domain. Curves with a different X quantity are shown only when the application has an exact conversion for that curve. For example, an order curve can be shown against frequency when its order is known; a time curve cannot be placed on a frequency axis ([units](topic:units/intro)). The title identifies curves that do not fit the current X axis.

The active graph is the selected workspace tab. Ribbon actions that operate on a graph use that tab, and may require a particular analysis type. Select the graph tab you intend to work with before using those actions.

## Axes and legend

Frequency can be shown on the axis in Hz or RPM, and you can switch between them ([X axis unit](topic:units/intro)).

For controls that affect curve rendering, see [Graph Defaults](topic:settings/graph_defaults). To load saved curves into the active graph, see [Result Pool](topic:results/intro).

For the hover readout and the selected-curve highlight, see [Cursor and Highlight](topic:tools/cursor).
