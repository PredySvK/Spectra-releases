"""
Import template: the shape of the user's saved description of how one kind of
table file is read. Plain, versioned, serialisable data -- no code, no regex.

`ImportTemplate.to_dict` / `from_dict` are what a template file and a project's
copy of the template are made of. Reading a file by a template lives in
io_modules/import_template.
"""

from core.import_template._import_template import (
    COLUMN_DELIMITERS,
    DATA_KIND_ORDER_CUT,
    DATA_KIND_ORDER_RESIDUAL,
    DATA_KIND_OVERALL_LEVEL,
    DATA_KIND_SPECTRUM,
    DATA_KIND_TIME_SIGNAL,
    DATA_KINDS,
    DECIMAL_SEPARATORS,
    DEFAULT_DELIMITERS,
    FIELD_KINDS,
    FORMAT_VERSION,
    LAYOUT_SHARED_X,
    LAYOUT_SINGLE_CURVE,
    LAYOUT_XY_PAIRS,
    LAYOUTS,
    PICK_FILE_NAME,
    PICK_FOLDER,
    PICK_HEADER,
    PICK_SHEET,
    PICK_SOURCES,
    SHEET_RULES,
    SHEETS_ALL,
    SHEETS_FIRST_N,
    SHEETS_LISTED,
    SHEETS_WITHOUT_LAST_N,
    ImportTemplate,
    MetadataPiece,
    MetadataSource,
    NamePart,
    TextPick,
)

__all__ = [
    "COLUMN_DELIMITERS",
    "DATA_KIND_ORDER_CUT",
    "DATA_KIND_ORDER_RESIDUAL",
    "DATA_KIND_OVERALL_LEVEL",
    "DATA_KIND_SPECTRUM",
    "DATA_KIND_TIME_SIGNAL",
    "DATA_KINDS",
    "DECIMAL_SEPARATORS",
    "DEFAULT_DELIMITERS",
    "FIELD_KINDS",
    "FORMAT_VERSION",
    "LAYOUT_SHARED_X",
    "LAYOUT_SINGLE_CURVE",
    "LAYOUT_XY_PAIRS",
    "LAYOUTS",
    "PICK_FILE_NAME",
    "PICK_FOLDER",
    "PICK_HEADER",
    "PICK_SHEET",
    "PICK_SOURCES",
    "SHEET_RULES",
    "SHEETS_ALL",
    "SHEETS_FIRST_N",
    "SHEETS_LISTED",
    "SHEETS_WITHOUT_LAST_N",
    "ImportTemplate",
    "MetadataPiece",
    "MetadataSource",
    "NamePart",
    "TextPick",
]
