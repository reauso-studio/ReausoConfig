"""Coercion of string values in a resolved config tree to declared field types.

After interpolation, a config can hold strings where its target classes declare
other types, e.g. ``debug: "false"`` from ``${env:DEBUG}`` for a ``bool`` field.
ConfigCoercer walks the tree alongside the target classes' type hints and
converts each such string, before validation checks the types strictly.
"""

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from functools import singledispatchmethod
from types import MappingProxyType
from typing import Any, get_origin, get_type_hints

from rconfig._internal.path_utils import build_child_path, get_value_at_path
from rconfig._internal.type_utils import (
    RCONFIG_INTERNAL_KEYS,
    REQUIRED_KEY,
    TARGET_KEY,
    extract_class_from_hint,
    extracted_container_element_type,
    is_concrete_type,
    is_union_hint,
    resolved_union_candidate,
    unwrapped_hint,
)
from rconfig.coercion.string_coercion import coerced_value
from rconfig.errors import ValueCoercionError
from rconfig.target import TargetRegistry


INSTANCE_KEY = "_instance_"


@dataclass(frozen=True)
class CoercionResult:
    """Result of coercing a config tree.

    :param config: The config with coerced values (a new tree; the input is unchanged).
    :param errors: Values that could not be converted, in tree order.
    :param coerced_paths: Config paths whose value was converted, with the new value.
    """

    config: dict[str, Any]
    errors: tuple[ValueCoercionError, ...]
    coerced_paths: MappingProxyType[str, Any]


@dataclass(frozen=True)
class _FieldLocation:
    """Where a value sits: the containing object's path and the field label."""

    parent_path: str
    field: str

    @property
    def path(self) -> str:
        return build_child_path(self.parent_path, self.field)

    def item(self, index: int) -> "_FieldLocation":
        """Location of a list item of this field."""
        return _FieldLocation(self.parent_path, f"{self.field}[{index}]")


class ConfigCoercer:
    """Converts string values in a config tree to their fields' declared types.

    Only strings are converted, and only where a type hint is known: fields of
    registered targets, of nested classes inferred from a parent's type hint,
    and items of typed lists and dicts. Fields typed ``str`` or ``Any`` and
    untyped dicts are left unchanged. Registration is never modified.

    :param store: TargetRegistry used to look up target classes.
    """

    def __init__(self, store: TargetRegistry) -> None:
        self._store = store

    def coerced(
        self,
        config: dict[str, Any],
        unresolved: dict[str, Any] | None = None,
    ) -> CoercionResult:
        """Return the config with string values converted to declared types.

        :param config: The resolved config (after interpolation).
        :param unresolved: The same config before interpolation, used to name
                           the expression a failing value came from.
        :return: CoercionResult with the new config, errors and converted paths.
        """
        coercion_pass = _CoercionPass(self._store, unresolved)
        coerced_config = coercion_pass.coerced_object(config, None, "")
        return CoercionResult(
            config=coerced_config,
            errors=tuple(coercion_pass.errors),
            coerced_paths=MappingProxyType(coercion_pass.coerced_paths),
        )


class _CoercionPass:
    """State of a single coercion walk over one config tree."""

    def __init__(self, store: TargetRegistry, unresolved: dict[str, Any] | None) -> None:
        self._store = store
        self._unresolved = unresolved
        self.errors: list[ValueCoercionError] = []
        self.coerced_paths: dict[str, Any] = {}

    def coerced_object(self, value: dict[str, Any], hint: Any, path: str) -> dict[str, Any]:
        """Return a config object with its fields coerced to the target class's hints."""
        field_hints = self._field_hints(value, hint)
        if field_hints is None:
            return value

        return {
            key: (
                item
                if key in RCONFIG_INTERNAL_KEYS or key not in field_hints
                else self._coerced_node(item, field_hints[key], _FieldLocation(path, key))
            )
            for key, item in value.items()
        }

    # === Dispatch on value type ===

    @singledispatchmethod
    def _coerced_node(self, value: Any, hint: Any, location: _FieldLocation) -> Any:
        """Values that are neither strings nor containers are left unchanged."""
        return value

    @_coerced_node.register
    def _(self, value: str, hint: Any, location: _FieldLocation) -> Any:
        if value == REQUIRED_KEY:
            return value
        try:
            converted = coerced_value(value, hint, split_lists=True)
        except ValueError as e:
            self.errors.append(self._coercion_error(value, hint, location, str(e)))
            return value

        if converted is not value:
            self.coerced_paths[location.path] = converted
        return converted

    @_coerced_node.register
    def _(self, value: dict, hint: Any, location: _FieldLocation) -> Any:
        unwrapped = unwrapped_hint(hint)
        if get_origin(unwrapped) in (dict, Mapping, MutableMapping):
            return {
                key: self._coerced_node(
                    item,
                    extracted_container_element_type(unwrapped, str(key)),
                    _FieldLocation(location.path, str(key)),
                )
                for key, item in value.items()
            }
        return self.coerced_object(value, hint, location.path)

    @_coerced_node.register
    def _(self, value: list, hint: Any, location: _FieldLocation) -> Any:
        unwrapped = unwrapped_hint(hint)
        return [
            self._coerced_node(
                item,
                extracted_container_element_type(unwrapped, index),
                location.item(index),
            )
            for index, item in enumerate(value)
        ]

    # === Helpers ===

    def _field_hints(self, value: dict[str, Any], hint: Any) -> dict[str, Any] | None:
        """Type hints of the class a config object maps to, or None if unknown."""
        if INSTANCE_KEY in value:
            return None

        target_class = self._target_class(value, hint)
        if target_class is None:
            return None

        try:
            return get_type_hints(target_class)
        except Exception:
            return None

    def _target_class(self, value: dict[str, Any], hint: Any) -> type | None:
        """The class a config object maps to: its registered target, or the hint's class."""
        target_name = value.get(TARGET_KEY)
        if isinstance(target_name, str) and target_name in self._store.known_targets:
            return self._store.known_targets[target_name].target_class

        if hint is None:
            return None

        class_type = extract_class_from_hint(hint)
        if class_type is not None:
            is_concrete, _, _ = is_concrete_type(self._store, class_type)
            return class_type if is_concrete else None

        unwrapped = unwrapped_hint(hint)
        if is_union_hint(unwrapped):
            return resolved_union_candidate(unwrapped, value, self._store)
        return None

    def _coercion_error(
        self, value: str, hint: Any, location: _FieldLocation, reason: str
    ) -> ValueCoercionError:
        """Build an error naming the unresolved expression the value came from."""
        return ValueCoercionError(
            field=location.field,
            expected=_hint_repr(hint),
            value=value,
            reason=reason,
            config_path=location.path,
            source_expression=self._source_expression(location.path),
        )

    def _source_expression(self, path: str) -> str | None:
        """The unresolved interpolation at a path, if the value came from one."""
        if self._unresolved is None:
            return None
        try:
            original = get_value_at_path(self._unresolved, path)
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(original, str) and "${" in original:
            return original
        return None


def _hint_repr(hint: Any) -> str:
    """Readable name of a type hint for error messages."""
    if isinstance(hint, type):
        return hint.__name__
    return str(hint).replace("typing.", "")
