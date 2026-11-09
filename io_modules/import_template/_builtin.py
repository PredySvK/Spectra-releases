"""
The Import templates shipped with the installation. Read-only: a project gets a
copy of one when the user adds data with it, and reads from that copy.
"""

from typing import List

from core.import_template import ImportTemplate

# MASTA's reordered export (#860): per column pair
#   row 1  "<source>, <n>th harmonic, Order <n>"
#   row 2  "<result>, <axis>, At <location>: <design>-Damping = <d>"
#   row 3  scenario
#   row 4  "Speed (rev/min)" | "Amplitude  (<unit>)"
# A bare "Amplitude" is Peak (readers §1.220). The two sheets are the two rotor
# variants; the Rotor field comes from the 4th chip of the sheet name. The name
# is the location and the order (so the pairs of one sheet, which differ only in
# the order, have different names); the axis comes after them. The texts are
# split at the wizard's delimiters, so a built-in opened in the wizard keeps
# its chip numbers (#1038).
_ROW_1 = {"source": "header", "row_above": 3}
_ROW_2 = {"source": "header", "row_above": 2}
_SHEET = {"source": "sheet"}
_BUILTIN = [
    {
        "format_version": 2,
        "name": "MASTA (new layout, both rotors, Excel file)",
        "file_pattern": "*.xlsx",
        "sheets": ["AccAMP,IHUS, Drive,AsymRot", "AccAMP,IHUS,Drive,SymRot"],
        "sheet_rule": "listed",
        "sheet_count": 1,
        "anchor_text": "Speed (rev/min)",
        "layout": "xy_pairs",
        "data_kind": "order_cut",
        "simulated": True,
        "amplitude": "peak",
        "texts": [
            {**_ROW_1, "delimiters": ",:;\\-"},
            {**_ROW_2, "delimiters": ",:;\\-", "cuts": [{"chip": 2, "cuts": [{"cut": "after_text", "text": "At "}]}]},
            {**_SHEET, "delimiters": "_,;- "},
        ],
        "roles": {
            "name": [{**_ROW_2, "chip": 2, "piece": 1}, {**_ROW_1, "chip": -1}],
            "axis": {**_ROW_2, "chip": 1},
            "order": {**_ROW_1, "chip": -1},
            "fields": [{"field": "Rotor", "chip": {**_SHEET, "chip": 3}}],
        },
    },
]


def read_builtin_templates() -> List[ImportTemplate]:
    """The built-in templates, in the order they are offered."""
    return [ImportTemplate.from_dict(data) for data in _BUILTIN]


def read_builtin_template(name: str) -> ImportTemplate:
    """The built-in template of this name; KeyError if there is none."""
    for template in read_builtin_templates():
        if template.name == name:
            return template
    raise KeyError(name)
