"""
Orchestration floor: what runs, in what order, when X happens.

Plans and runs batches, dispatches analytical computation, and drives the
single JobRunner port (the layer diagram). It never asks a human and
never waits on Qt -- a decision that needs a human comes back as data (e.g.
"this result set already exists") for gui/ to turn into a dialog.

What does not belong here: drawing or Qt widgets (gui/), how a result is
formatted for display (view_models/), what project is currently open
(session/), or the maths itself (signal_processing/) -- orchestration calls
those, it does not reimplement them.
"""
