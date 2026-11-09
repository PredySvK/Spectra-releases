"""
Reading a file by an Import template: the reader, the one reading the reader and
the import wizard's preview share, the built-in templates, the user's library
and the registry of the open project's copies.

`AccReaderImportTemplate` keeps the reader protocol (MeasurementReader).
`build_template_reading` is what a template finds in a `Workbook` in memory --
the scan and the wizard both call it, so the preview never differs from the
result; `read_workbook` is its disk read (run it on a worker; a text file's encoding,
delimiter and decimal separator are detected or set, `TextFormat`). The metadata a
template takes from the file name, folder, sheet and column header is kept on
the channels under `resolve_template_field_key`, and
`build_template_schema_fields` is its Raw metadata schema. Readers consult
only the registry (`install_project_templates`), never the built-ins or the
library, so a project reads the same without them.
The wizard reads all its samples whole (`read_samples`, a `SampleRead` each)
and finds the further files of the first one's kind (`read_more_samples`), both
on a worker; `resolve_header_unit` and `resolve_source_amplitude` say what a
heading cell states before any template override.
A template splits the texts around a channel (file name, folder, sheet, header rows) into chips (`build_text_chips`, own cuts
`build_cut_spans`, the number in a chip `resolve_chip_number`) and its roles
name the chips (`build_chip_roles` is what they make of one channel's texts,
`resolve_chip_source_text` the text of a source for one channel); a sheet without the heading row is a `SkippedSheet`, not a misfit.

What does not belong here: the template's shape (core/import_template), the
wizard's state (view_models/import_template), or which project holds which
copy (session).
"""

from io_modules.import_template._builtin import (
    read_builtin_templates,
    read_builtin_template,
)
from io_modules.import_template._library import (
    delete_library_template,
    write_library_template_from_file,
    read_library_problems,
    read_library_templates,
    read_template_file,
    resolve_library_file,
    resolve_library_folder,
    write_library_template,
    write_template_file,
)
from io_modules.import_template._metadata import (
    TEMPLATE_FIELD_PREFIX,
    build_template_schema_fields,
    resolve_template_field_key,
)
from io_modules.import_template._reader import (
    AccReaderImportTemplate,
    discard_import_template_caches,
    read_template_candidates,
    read_template_match,
    resolve_template_name_fit,
    read_template_misfit_reason,
)
from io_modules.import_template._registry import (
    resolve_installed_template,
    install_project_templates,
    resolve_installed_templates,
    resolve_installed_signature,
    resolve_template_cache_key,
)
from io_modules.import_template._table import (
    HZ_PER_UNIT,
    RPM_PER_UNIT,
    SECONDS_PER_UNIT,
    SheetReading,
    SkippedSheet,
    TemplateChannel,
    TemplateReading,
    Workbook,
    build_template_reading,
    build_text_format,
    read_workbook,
    resolve_cell_text,
    resolve_chip_source_text,
    resolve_head_row_count,
    resolve_header_column,
    resolve_header_unit,
    resolve_heading_row,
    resolve_linear_values,
    resolve_read_sheets,
    resolve_source_amplitude,
    resolve_source_text,
    resolve_x_factor,
    resolve_x_units,
)
from io_modules.import_template._samples import SampleRead, read_more_samples, read_samples
from io_modules.import_template._text_chips import (
    TextChip,
    TextChips,
    build_cut_spans,
    NAME_JOIN,
    ChipRoles,
    build_chip_roles,
    resolve_axis_text,
    build_text_chips,
    resolve_chip_label,
    resolve_chip_number,
    resolve_text_source_label,
)
from io_modules.import_template._text_table import TextFormat, resolve_text_format

__all__ = [
    "HZ_PER_UNIT",
    "NAME_JOIN",
    "RPM_PER_UNIT",
    "SECONDS_PER_UNIT",
    "TEMPLATE_FIELD_PREFIX",
    "AccReaderImportTemplate",
    "ChipRoles",
    "SampleRead",
    "SheetReading",
    "SkippedSheet",
    "TemplateChannel",
    "TemplateReading",
    "TextChip",
    "TextChips",
    "TextFormat",
    "Workbook",
    "read_more_samples",
    "read_samples",
    "build_cut_spans",
    "build_template_reading",
    "build_template_schema_fields",
    "build_text_chips",
    "build_chip_roles",
    "build_text_format",
    "resolve_text_format",
    "delete_library_template",
    "discard_import_template_caches",
    "resolve_installed_template",
    "write_library_template_from_file",
    "install_project_templates",
    "resolve_installed_templates",
    "read_builtin_templates",
    "read_template_candidates",
    "read_template_match",
    "resolve_template_name_fit",
    "read_builtin_template",
    "read_library_problems",
    "read_library_templates",
    "read_template_file",
    "read_workbook",
    "resolve_axis_text",
    "resolve_cell_text",
    "resolve_chip_source_text",
    "resolve_chip_label",
    "resolve_chip_number",
    "resolve_text_source_label",
    "resolve_head_row_count",
    "resolve_header_column",
    "resolve_header_unit",
    "resolve_heading_row",
    "resolve_installed_signature",
    "resolve_linear_values",
    "resolve_library_file",
    "resolve_library_folder",
    "resolve_read_sheets",
    "resolve_source_amplitude",
    "resolve_source_text",
    "resolve_template_cache_key",
    "resolve_template_field_key",
    "resolve_x_factor",
    "resolve_x_units",
    "read_template_misfit_reason",
    "write_library_template",
    "write_template_file",
]
