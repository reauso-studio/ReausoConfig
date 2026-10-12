"""Conversion of raw string values to declared type hints.

Strings reach typed fields from environment variables, CLI overrides,
interpolation results and quoted YAML literals. This module converts such a
string to the type a field declares, so that ``"false"`` becomes ``False`` for a
``bool`` field and ``"INFO"`` becomes ``LogLevel.INFO`` for an enum field.
"""

from enum import Enum
from pathlib import PurePath
from typing import Annotated, Any, TypeVar, get_args, get_origin

from rconfig._internal.type_utils import (
    extracted_container_element_type,
    is_union_hint,
)


TRUE_TOKENS = frozenset({"true", "yes", "1", "on"})
FALSE_TOKENS = frozenset({"false", "no", "0", "off"})
NONE_TOKENS = frozenset({"none", "null", "~"})

_SEQUENCE_ORIGINS = frozenset({list, tuple, set, frozenset})
_MAPPING_ORIGINS = frozenset({dict})


def coerced_value(
    raw: str,
    hint: Any,
    *,
    split_lists: bool = False,
    construct_unknown: bool = False,
) -> Any:
    """Convert a raw string to the given type hint.

    Hints that accept any string (``str``, ``Any``, ``object``, type variables,
    or no hint at all) return the string unchanged.

    :param raw: The raw string value.
    :param hint: The declared type hint of the target field.
    :param split_lists: If True, a sequence hint accepts a comma-separated
                        string (``"a, b"``). Otherwise only ``[a, b]`` syntax.
    :param construct_unknown: If True, other classes are called with the raw
                              string (``hint(raw)``). Otherwise the string is
                              returned unchanged for the validator to judge.
    :return: The converted value.
    :raises ValueError: If the string cannot be converted to the hint.
    """
    hint = _unwrapped_annotation(hint)

    if _accepts_any_string(hint):
        return raw
    if is_union_hint(hint):
        return _coerced_union_value(raw, hint, split_lists, construct_unknown)
    if hint is type(None):
        return _coerced_none(raw)
    if hint is bool:
        return _coerced_bool(raw)
    if isinstance(hint, type) and issubclass(hint, Enum):
        return _coerced_enum_member(raw, hint)
    if hint in (int, float):
        return _coerced_number(raw, hint)
    if isinstance(hint, type) and issubclass(hint, PurePath):
        return hint(raw)

    origin = get_origin(hint) or hint
    if origin in _SEQUENCE_ORIGINS:
        return _coerced_sequence(raw, hint, split_lists, construct_unknown)
    if origin in _MAPPING_ORIGINS:
        return _parsed_yaml(raw, typed=True)

    if construct_unknown and callable(hint):
        try:
            return hint(raw)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Cannot convert '{raw}' to {_hint_name(hint)}") from e
    return raw


def _unwrapped_annotation(hint: Any) -> Any:
    """Strip ``Annotated[...]`` and ``NewType`` wrappers from a hint."""
    while True:
        if get_origin(hint) is Annotated:
            hint = get_args(hint)[0]
            continue
        supertype = getattr(hint, "__supertype__", None)
        if supertype is not None and not isinstance(hint, type):
            hint = supertype
            continue
        return hint


def _accepts_any_string(hint: Any) -> bool:
    """Check if a hint accepts any string as-is."""
    return hint is None or hint is str or hint is Any or hint is object or isinstance(hint, TypeVar)


def _coerced_union_value(raw: str, hint: Any, split_lists: bool, construct_unknown: bool) -> Any:
    """Convert a string to the first union member that accepts it.

    A none-token becomes None when the union includes None, and a union that
    includes ``str`` keeps the string unchanged.
    """
    members = get_args(hint)
    if type(None) in members and raw.strip().lower() in NONE_TOKENS:
        return None
    if str in members:
        return raw

    candidates = [member for member in members if member is not type(None)]
    failure_count = 0
    for member in candidates:
        try:
            value = coerced_value(
                raw, member, split_lists=split_lists, construct_unknown=construct_unknown
            )
        except ValueError:
            failure_count += 1
            continue
        if value is not raw:
            return value

    if failure_count == len(candidates):
        raise ValueError(f"Cannot convert '{raw}' to {_hint_name(hint)}")
    return raw


def _coerced_none(raw: str) -> None:
    """Convert a none-token to None."""
    if raw.strip().lower() in NONE_TOKENS:
        return None
    raise ValueError(f"Cannot convert '{raw}' to None; expected one of {', '.join(sorted(NONE_TOKENS))}")


def _coerced_bool(raw: str) -> bool:
    """Convert a boolean token to a bool, rejecting anything else.

    Unrecognised tokens raise instead of reading as False, so a typo such as
    ``ture`` cannot silently disable a flag.
    """
    token = raw.strip().lower()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    raise ValueError(
        f"Cannot convert '{raw}' to bool; expected one of "
        f"{'/'.join(sorted(TRUE_TOKENS))} or {'/'.join(sorted(FALSE_TOKENS))}"
    )


def _coerced_enum_member(raw: str, enum_class: type[Enum]) -> Enum:
    """Convert a string to an enum member, matching by value first, then by name."""
    for member in enum_class:
        if member.value == raw or str(member.value) == raw:
            return member
    for member in enum_class:
        if member.name == raw:
            return member
    valid_values = ", ".join(str(member.value) for member in enum_class)
    raise ValueError(f"Cannot convert '{raw}' to {enum_class.__name__}; valid values: {valid_values}")


def _coerced_number(raw: str, number_type: type) -> int | float:
    """Convert a string to an int or float."""
    try:
        return number_type(raw)
    except ValueError as e:
        raise ValueError(f"Cannot convert '{raw}' to {number_type.__name__}") from e


def _coerced_sequence(raw: str, hint: Any, split_lists: bool, construct_unknown: bool) -> Any:
    """Convert a string to a list, coercing each item to the element type.

    ``[a, b]`` is parsed as YAML. With ``split_lists``, any other string is
    split on commas and each item is stripped; empty items are dropped.
    Without an element type, YAML items keep their inferred types.
    """
    has_element_type = bool(get_args(hint))
    stripped = raw.strip()

    if stripped.startswith("["):
        items = _parsed_yaml(stripped, typed=not has_element_type)
    elif split_lists:
        items = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        return _parsed_yaml(raw, typed=True)

    if not isinstance(items, list) or not has_element_type:
        return items
    return [
        _coerced_item(item, extracted_container_element_type(hint, index), construct_unknown)
        for index, item in enumerate(items)
    ]


def _coerced_item(item: Any, hint: Any, construct_unknown: bool) -> Any:
    """Convert a parsed sequence item, recursing into nested lists."""
    if isinstance(item, str):
        return coerced_value(item, hint, construct_unknown=construct_unknown)
    if isinstance(item, list) and get_origin(hint) in _SEQUENCE_ORIGINS:
        return [
            _coerced_item(nested, extracted_container_element_type(hint, index), construct_unknown)
            for index, nested in enumerate(item)
        ]
    return item


def _parsed_yaml(raw: str, *, typed: bool) -> Any:
    """Parse a YAML flow value.

    :param typed: If True, scalars get YAML types (int, bool, ...). If False,
                  every scalar stays a string for later coercion.
    """
    from ruamel.yaml import YAML

    try:
        return YAML(typ="safe" if typed else "base").load(raw)
    except Exception as e:
        raise ValueError(f"Cannot parse YAML value: {raw}") from e


def _hint_name(hint: Any) -> str:
    """Readable name of a type hint for error messages."""
    return getattr(hint, "__name__", None) or str(hint)
