# Paired order curves

When you add an [order curve](topic:order_tracking/orders) to a graph, the app can add its paired curve from another channel in the same project. This is useful when you want to compare the same order on a measured channel and its paired counterpart. Pairing is optional: it must be configured in the project, and the counterpart must be available among the measurements currently loaded in the [Data Pool](topic:data_management/intro).

## What gets added

The app looks for a matching channel pair at the same order as a newly added order curve. A [time waveform](topic:raw_data/intro) can supply a curve at that order; an imported order curve is used only if its stored order matches. The partner is added to the same graph through the normal channel-drop route, so it is read or computed using that route's requirements.

Pairs work in both directions: if channel A is paired with channel B, adding an order curve for either side can find the other. The search covers all currently loaded measurement files, not only the file of the curve you added. If several loaded files contain a matching counterpart, each distinct channel/order candidate can be added. A partner already plotted at that order is skipped, so repeated additions do not duplicate the same curve.

Only newly added order curves can start this search. A curve added automatically as a partner does not start another search, so the app does not follow a chain of pairings. If you later add a curve yourself, that curve can look for its own partner.

## When no partner appears

No extra curve is added when the project has no channel pairing, the paired channel is not present in a currently loaded measurement, the available channel is not a time waveform or imported order curve, or an imported order curve has a different order. An imported order file that cannot be read is skipped; the original curve remains in the graph. Other failures are reported in the application log as **Companion curves** errors.

To create or edit channel pairs, see [Channel pairing](topic:import/channel_pairing). A pair applies across files in the project; pairing setup and its file format are described on that page.
