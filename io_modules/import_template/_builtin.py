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
# variants; the Rotor field comes from the 4th piece of the sheet name.
_BUILTIN = [
    {
        "format_version": 1,
        "name": "MASTA (new layout, both rotors, Excel file)",
        "file_pattern": "*.xlsx",
        "sheets": ["AccAMP,IHUS, Drive,AsymRot", "AccAMP,IHUS,Drive,SymRot"],
        "sheet_rule": "listed",
        "sheet_count": 1,
        "anchor_text": "Speed (rev/min)",
        "layout": "xy_pairs",
        "data_kind": "order_cut",
        "channel_name": [
            {"row_above": 2, "after": "At ", "before": ":"},
            ":",
            {"row_above": 2, "split": ",", "piece": 1},
            " Order ",   # the pairs of one sheet differ only in the order (row 1), so the name must carry it
            {"row_above": 3, "after": "Order "},
        ],
        "order": {"row_above": 3, "after": "Order "},
        "simulated": True,
        "source_amplitude": "peak",
        "metadata": [
            {
                "source": "sheet",
                "delimiters": ",",
                "pieces": [{"position": 3, "field": "Rotor"}],
                "drop_unknown": True,
            },
        ],
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
