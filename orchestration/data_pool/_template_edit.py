"""
The order of an Import template edit, from the misfit report or from the
project's copy, without Qt (#903, K35).

The shell answers the questions -- the wizard, the consequence summary, which
misfit to fix -- through `IngestAskers`; what comes out is the one ingest run
the edit ends in, or None when nothing is to run. Nothing here changes the
project: replacing the copy is the run's first write (`PoolIngestUseCase`), so
a question the user cancels leaves the project as it was.

All internal documentation strings and variable labels are standardly written
in English.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from core.import_template import ImportTemplate
from orchestration.data_pool._ingest_request import IngestAskers, IngestRequest
from orchestration.data_pool._template_assignment import Misfit
from view_models.import_template import build_template_edit_summary


def build_copy_change_summary(session, before: ImportTemplate, after: ImportTemplate):
    """The consequences of replacing the project's copy `before` by `after`, against what the project uses."""
    return build_template_edit_summary(
        before, after, filter_cards=session.project.filter_cards,
        filter_profiles=session.filter_profiles, open_tabs=session.current_open_tabs())


def plan_template_edit(session, name: str, sample_path: str, askers: IngestAskers,
                       misfit_paths: Sequence[str] = ()) -> Optional[IngestRequest]:
    """
    Edits the project's copy of the template `name` on `sample_path`.

    From the misfit report (`misfit_paths`, the files that did not fit it) the
    wizard ends in Overwrite or Save as new; in the project it ends in Apply.
    Save as new adds the misfits with the new template. Overwrite and Apply
    show the consequence summary first: confirming makes one run that replaces
    the copy, re-reads its files and adds the misfits, and then offers the edit
    to the library; Cancel runs nothing.
    """
    template = session.resolve_import_template(name)
    if template is None or askers.edit_template is None:
        return None
    edited = askers.edit_template(template, sample_path, bool(misfit_paths),
                                  tuple(session.resolve_import_templates()))
    if edited is None:
        return None
    if edited.saved_as_new:
        return IngestRequest.add(misfit_paths, import_templates=(edited.template,)) if misfit_paths else None
    if askers.confirm_edit is None or not askers.confirm_edit(
            build_copy_change_summary(session, template, edited.template)):
        return None
    if misfit_paths:
        return IngestRequest.add(misfit_paths, import_templates=(edited.template,),
                                 replacements=(edited.template,), offer_to_library=edited.template)
    return IngestRequest.template_edit(edited.template, offer_to_library=edited.template)


def plan_misfit_fix(session, misfits: Tuple[Misfit, ...], askers: IngestAskers) -> Optional[IngestRequest]:
    """
    Shows the misfit report; the misfit the user picks opens the wizard on its
    file with the project's template it can be fixed in, and the other misfits
    of that template are added with the edit too.
    """
    if not misfits or askers.choose_misfit is None:
        return None
    names = tuple(_fixable_in(session, misfit) for misfit in misfits)
    chosen = askers.choose_misfit(misfits, tuple(bool(name) for name in names))
    if chosen is None:
        return None
    name = names[misfits.index(chosen)]
    if not name:
        return None
    return plan_template_edit(session, name, chosen.path, askers, misfit_paths=[
        misfit.path for misfit, template in zip(misfits, names) if template == name])


def _fixable_in(session, misfit: Misfit) -> str:
    """The project's template a misfit can be fixed in: the first of those it names that the project holds."""
    return next((name for name in misfit.templates if session.resolve_import_template(name) is not None), "")
