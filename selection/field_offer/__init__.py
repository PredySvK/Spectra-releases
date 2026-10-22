"""
selection.field_offer -- the Field offer: which metadata schema fields a user
may pick from (a Filter card column, an Evaluation table column, a Cursor Box
row), what each one is called and which section it sits in.

Selection floor: which subset of the schema fields is offered? The one place
the Active Status gate, the field label rule, the Raw / Excel
metadata split and the offer's order live.

Does NOT import Qt, gui, orchestration, view_models, session, or io_modules.
"""

from ._field_offer import (
    FieldOffer,
    OfferedField,
    active_schema_fields,
    build_field_offer,
    is_active_field,
    resolve_field_label,
    schema_field_group,
)

__all__ = [
    "FieldOffer",
    "OfferedField",
    "active_schema_fields",
    "build_field_offer",
    "is_active_field",
    "resolve_field_label",
    "schema_field_group",
]
