"""What the Input block's selection combo offers, and which item it shows."""
from dataclasses import dataclass
from typing import Optional, Sequence

from core.workflow_graph import InputSpec
from selection.measurement_selection import WHOLE_POOL_SELECTION_NAME

NO_SELECTION_LABEL = "(none)"


@dataclass(frozen=True)
class InputOptions:
    """Items as (label, `InputSpec`) and the index of the one shown.

    An item carries its meaning as data, not as text: a user selection may share
    its label with the whole-pool item.
    """
    items: tuple[tuple[str, InputSpec], ...]
    current_index: int


def build_input_options(selection_names: Sequence[str], spec: Optional[InputSpec]) -> InputOptions:
    """No selection, the whole Data Pool, then the project's selections; the
    Input's `spec` picks one, a vanished selection shows as no selection."""
    names = list(selection_names)
    items = ((NO_SELECTION_LABEL, InputSpec()),
             (WHOLE_POOL_SELECTION_NAME, InputSpec(whole_pool=True)),
             *((name, InputSpec(selection_name=name)) for name in names))
    if spec is not None and spec.whole_pool:
        current = 1
    elif spec is not None and spec.selection_name in names:
        current = 2 + names.index(spec.selection_name)
    else:
        current = 0
    return InputOptions(tuple(items), current)
