"""
view_models.curve_metadata -- One typed Curve metadata record per curve.

Architecture:
- View-model floor (Floor 3): what value does each curve have for every column a
  Filter card can show, without Qt?
- build_curve_metadata turns a batch of traces into one record each: the built-in
  columns (Channel as base name, Direction, Channel type, File name, Data Pool
  label, Result set, Analysis type, Order, Parameter set) plus every schema field,
  typed (numbers as numbers, dates as ISO text). A column a curve has no value
  for is absent. It needs the whole batch because Parameter sets are labelled
  across the batch.

What does NOT belong here: turning a value into text (the reader's job: Cursor
Box, Evaluation table), deciding which columns are offered (Filter), or the
per-field value itself (selection.source_facets.curve_field_value).
"""

from ._curve_metadata import build_curve_metadata

__all__ = ["build_curve_metadata"]
