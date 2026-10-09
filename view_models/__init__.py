"""
View-model floor: how a result should be shown, without Qt.

Plot models, tab specs, table formatting and legend text -- data shaped for
drawing, built without importing Qt or gui/.

What does not belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), or which
curves are relevant in the first place (selection/).
"""
