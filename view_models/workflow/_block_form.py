"""What the Properties form of one block shows, and how its entries read back as params."""
import dataclasses
import typing
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from signal_processing.workflow import spec_for
from view_models.analysis_kinds import resolve_dsp_choices_of_config

# The widget a field is drawn with. A "text" field's value is the text shown;
# every other field's value is the typed value.
WIDGET_CHOICE = "choice"
WIDGET_CHECK = "check"
WIDGET_INTEGER = "integer"
WIDGET_DECIMAL = "decimal"
WIDGET_TEXT = "text"


@dataclass(frozen=True)
class BlockFormField:
    name: str
    label: str
    widget: str
    value: Any
    choices: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class BlockForm:
    """The rows of one block's form, in the order of its config's fields.

    A display-only field (it changes how a result is drawn, not what it holds)
    and a field the Settings window owns get no row: Apply would drop the first
    and a run overwrites the second (`display_only_params`, `settings_params`,
    ADR §1.211), so a row would promise what the block never keeps.
    """
    block_type: str
    fields: tuple[BlockFormField, ...]


def _pretty(name: str) -> str:
    return name.replace("_", " ").title()


def _field_default(f: dataclasses.Field) -> Any:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        return f.default_factory()  # type: ignore[misc]
    return None


def _field_type(f: dataclasses.Field) -> Any:
    """The declared type; guarded in case `core/dsp_configs.py` ever switches to
    string annotations."""
    t = f.type
    if isinstance(t, str):
        return {"int": int, "float": float, "bool": bool, "str": str, "list": list}.get(t, str)
    return t


def _optional_inner(ftype: Any) -> Any:
    """`X` for an `Optional[X]` field, otherwise None."""
    if typing.get_origin(ftype) is typing.Union:
        args = typing.get_args(ftype)
        inner = [arg for arg in args if arg is not type(None)]
        if len(args) == 2 and len(inner) == 1:
            return inner[0]
    return None


def _choices_for(config_cls: Any, name: str) -> tuple:
    """The register's (label, value) list for a field with a closed set of values,
    the same the analysis tab's ribbon offers (#759); empty for a free field."""
    register = resolve_dsp_choices_of_config(config_cls)
    if register is None:
        return ()
    try:
        return tuple(register.parameter(name).choices)
    except ValueError:
        return ()


def _shown_fields(block_type: str) -> tuple[dataclasses.Field, ...]:
    spec = spec_for(block_type)
    hidden = set(spec.display_only_params) | set(spec.settings_params)
    return tuple(f for f in dataclasses.fields(spec.config_cls) if f.name not in hidden)


def _form_field(config_cls: Any, f: dataclasses.Field, value: Any, entered: bool) -> BlockFormField:
    """`value` is a params value, or a widget entry when `entered`."""
    label = _pretty(f.name)
    choices = _choices_for(config_cls, f.name)
    if choices:
        if value not in [data for _, data in choices]:
            # A value saved outside the list stays visible instead of being replaced.
            choices = choices + ((str(value), value),)
        return BlockFormField(f.name, label, WIDGET_CHOICE, value, choices)
    ftype = _field_type(f)
    if ftype is bool:
        return BlockFormField(f.name, label, WIDGET_CHECK, bool(value))
    if ftype is int:
        return BlockFormField(f.name, label, WIDGET_INTEGER, value)
    if ftype is float:
        return BlockFormField(f.name, label, WIDGET_DECIMAL, value)
    if entered:
        text = value
    elif ftype is list:
        text = ", ".join(str(item) for item in (value or []))
    else:
        text = "" if value is None else str(value)
    return BlockFormField(f.name, label, WIDGET_TEXT, text)


def build_block_form(block_type: str, params: Mapping[str, Any],
                     entries: Optional[Mapping[str, Any]] = None) -> BlockForm:
    """
    The form of a `block_type` block holding `params`. A key missing from
    `params` shows the config's default -- the value the ribbon would show.
    `entries` (as `resolve_block_form_params` takes them) win over `params`:
    they are what the user typed and has not applied yet.

    Raises ValueError for a block type outside `BLOCKS`.
    """
    config_cls = spec_for(block_type).config_cls
    entries = entries or {}
    rows = []
    for f in _shown_fields(block_type):
        if f.name in entries:
            rows.append(_form_field(config_cls, f, entries[f.name], entered=True))
        else:
            rows.append(_form_field(config_cls, f, params.get(f.name, _field_default(f)), entered=False))
    return BlockForm(block_type, tuple(rows))


def _read_text(f: dataclasses.Field, text: str) -> Any:
    ftype = _field_type(f)
    text = text.strip()
    if ftype is list:
        out = []
        for item in (part.strip() for part in text.split(",")):
            if not item:
                continue
            try:
                out.append(float(item))
            except ValueError:
                out.append(item)
        return out
    inner = _optional_inner(ftype)
    if inner is not None:
        # Empty means None, not "": Overall Level's f_stop=None is Full
        # Bandwidth, and "" would reach the DSP as a band edge.
        if not text:
            return None
        try:
            return inner(text)
        except (TypeError, ValueError):
            # Kept as typed: Apply refuses it (`resolve_block_params_refusal`).
            return text
    return text


def resolve_block_form_params(block_type: str, entries: Mapping[str, Any]) -> dict[str, Any]:
    """
    The params a form's `entries` stand for -- one entry per `BlockForm` field:
    the text of a "text" field, the typed value of any other. A text that does
    not convert is passed on as typed, for Apply to refuse.
    """
    config_cls = spec_for(block_type).config_cls
    out: dict[str, Any] = {}
    for f in _shown_fields(block_type):
        if f.name not in entries:
            continue
        value = entries[f.name]
        is_text = (not _choices_for(config_cls, f.name)
                   and _field_type(f) not in (bool, int, float))
        out[f.name] = _read_text(f, str(value)) if is_text else value
    return out
