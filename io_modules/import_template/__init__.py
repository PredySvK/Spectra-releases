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
library, so a project reads the same without them. `read_sample_fits` is the
wizard's check of further sample files, read like the scan does (a worker).

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
    read_library_templates,
    read_template_file,
    resolve_library_file,
    resolve_library_folder,
    write_library_template,
    write_template_file,
)
from io_modules.import_template._metadata import (
    TEMPLATE_FIELD_PREFIX,
    SourcePiece,
    build_source_pieces,
    build_template_schema_fields,
    resolve_field_label,
    resolve_piece_index,
    resolve_source_fields,
    resolve_template_field_key,
    resolve_key_value,
    resolve_number_unit,
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
    TemplateChannel,
    TemplateReading,
    Workbook,
    build_template_reading,
    build_text_format,
    resolve_metadata_source_label,
    read_workbook,
    resolve_cell_text,
    resolve_head_row_count,
    resolve_header_column,
    resolve_heading_row,
    resolve_linear_values,
    resolve_metadata_source_text,
    resolve_pick_source_text,
    resolve_read_sheets,
    resolve_x_factor,
    resolve_x_units,
)
from io_modules.import_template._sample_fit import SampleFit, read_sample_fits
from io_modules.import_template._text_table import TextFormat, resolve_text_format

__all__ = [
    "HZ_PER_UNIT",
    "RPM_PER_UNIT",
    "SECONDS_PER_UNIT",
    "TEMPLATE_FIELD_PREFIX",
    "AccReaderImportTemplate",
    "SampleFit",
    "SheetReading",
    "SourcePiece",
    "TemplateChannel",
    "TemplateReading",
    "TextFormat",
    "Workbook",
    "read_sample_fits",
    "build_source_pieces",
    "build_template_reading",
    "build_template_schema_fields",
    "build_text_format",
    "resolve_text_format",
    "resolve_metadata_source_label",
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
    "read_library_templates",
    "read_template_file",
    "read_workbook",
    "resolve_cell_text",
    "resolve_field_label",
    "resolve_head_row_count",
    "resolve_header_column",
    "resolve_heading_row",
    "resolve_installed_signature",
    "resolve_linear_values",
    "resolve_library_file",
    "resolve_library_folder",
    "resolve_metadata_source_text",
    "resolve_pick_source_text",
    "resolve_piece_index",
    "resolve_read_sheets",
    "resolve_source_fields",
    "resolve_template_cache_key",
    "resolve_template_field_key",
    "resolve_x_factor",
    "resolve_x_units",
    "resolve_key_value",
    "resolve_number_unit",
    "read_template_misfit_reason",
    "write_library_template",
    "write_template_file",
]
