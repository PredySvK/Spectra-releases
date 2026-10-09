"""
Selection floor: which subset of curves or measurements is relevant.

Covers both Filter selection (which curves stay visible on an open dock) and
Measurement selection (which measurements a batch runs over) -- "Selection"
is the umbrella term for both (CONTEXT.md), never used in code for one
specific kind of selection.

What does not belong here: how a curve is drawn (view_models/), what project
is currently open (session/), or Qt (gui/).
"""
