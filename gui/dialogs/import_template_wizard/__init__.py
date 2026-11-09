"""
gui.dialogs.import_template_wizard -- The import wizard: builds an Import template on several
samples, in four steps and a preview (`TemplateWizardDialog`, #1028).

What does NOT belong here: the wizard's state and the preview's computation
(view_models/import_template), reading the samples (io_modules/import_template).
"""

from view_models.import_template import ENDING_LIBRARY, ENDING_MISFIT, ENDING_PROJECT, SAVED_NEW, SAVED_OVERWRITE

from ._wizard_dialog import TemplateWizardDialog

__all__ = [
    "ENDING_LIBRARY", "ENDING_MISFIT", "ENDING_PROJECT", "SAVED_NEW", "SAVED_OVERWRITE",
    "TemplateWizardDialog",
]
