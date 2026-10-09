"""
Session floor: what is currently open, and how it changes over time.

The open project's evolving state -- result set bookkeeping, the Data Pool,
stored Filter selections, and (later) Undo history and layout presets --
lives here, independent of view_models/.

What does not belong here: reading or writing the project file on disk
(io_modules/), how a result is displayed (view_models/), or Qt (gui).
"""

from .open_tabs import RestorePlan, RestoreTab, TabSpec, TraceSpec, build_restore_plan

__all__ = ["RestorePlan", "RestoreTab", "TabSpec", "TraceSpec", "build_restore_plan"]
