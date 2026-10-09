# core/graphic_configs.py
"""
Central Application Configuration Schema.
Defines all default environment parameters, performance constraints, and registry keys.
Acts as a single source of truth for settings management across the entire workspace.
All internal documentation strings and variable labels are standardly written in English.
"""

# MASTER DEFAULTS REGISTRY: Easily scalable schema layout.
# Adding any new configuration row here automatically injects it into the app lifecycle.
GRAPHIC_SYSTEM_DEFAULTS = {
    "perf_downsample_enabled": (True, bool),
    "perf_auto_mode_active": (True, bool),
    "perf_manual_factor": (10, int),
    "perf_render_screen_only": (True, bool),

    # You can easily stack future UI preferences here without altering core code files:
    # "ui_theme_dark": (False, bool),
    # "plot_line_width": (1, int)
}












