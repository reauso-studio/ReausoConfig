"""Configuration validation logic.

This module provides validation of config dictionaries against registered
target classes in the TargetRegistry.
"""

import inspect
from collections.abc import (
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set as AbstractSet,
)
from dataclasses import dataclass, field
from inspect import Parameter
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from rconfig.target import TargetRegistry, TargetEntry
from rconfig.errors import (
    AmbiguousTargetError,
    InvalidOverridePathError,
    MissingFieldError,
    TargetNotFoundError,
    TargetTypeMismatchError,
    TypeInferenceError,
    TypeMismatchError,
    ValidationError,
)
from rconfig._internal.path_utils import PathNavigationError, navigate_path
from rconfig._internal.type_utils import (
    TARGET_KEY,
    LAZY_KEY,
    could_be_implicit_nested,
    extract_class_from_hint,
    is_class_type,
    is_concrete_type,
    is_union_hint,
    register_inferred_target,
)


# Origins that accept list values (YAML has no native set/frozenset/tuple)
_LIST_LIKE_ORIGINS: frozenset[type] = frozenset({
    list, set, frozenset, tuple,
    Sequence, MutableSequence, AbstractSet, MutableSet,
})

# Origins that accept dict values
_DICT_LIKE_ORIGINS: frozenset[type] = frozenset({
    dict, Mapping, MutableMapping,
})


@dataclass
class ValidationResult:
    """Result of config validation.

    :param valid: True if validation passed with no errors.
    :param errors: List of validation errors found.
    """

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)


class ConfigValidator:
    """Validates config dictionaries against registered target classes.

    Performs validation including:
    - Target existence in TargetRegistry
    - Required field presence
    - Type compatibility
    - Recursive validation of nested configs
    """

    def __init__(self, store: TargetRegistry) -> None:
        """Initialize the validator.

        :param store: TargetRegistry containing registered target classes.
        """
        self._store = store

    def validate(self, config: dict[str, Any], config_path: str = "") -> ValidationResult:
        """Validate a config dictionary against its target class.

        :param config: Config dict that should contain a _target_ key.
        :param config_path: Current path for error messages (e.g., "model.encoder").
        :return: ValidationResult with any errors found.
        """
        errors: list[ValidationError] = []

        # Check _target_ exists in config
        if TARGET_KEY not in config:
            errors.append(
                AmbiguousTargetError(
                    field="(root)",
                    expected_type=object,
                    available_targets=list(self._store.known_targets.keys()),
                    is_abstract=True,
                    config_path=config_path,
                )
            )
            return ValidationResult(valid=False, errors=errors)

        target_name = config[TARGET_KEY]

        # Check target is registered
        target_error = self._target_not_found_error(target_name, config_path)
        if target_error:
            errors.append(target_error)
            return ValidationResult(valid=False, errors=errors)

        reference = self._store.known_targets[target_name]

        # Validate required fields
        missing_errors = self._missing_field_errors(config, reference, config_path)
        errors.extend(missing_errors)

        # Validate types
        type_errors = self._type_errors(config, reference, config_path)
        errors.extend(type_errors)

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _target_not_found_error(
        self, target: str, config_path: str
    ) -> TargetNotFoundError | None:
        """Return TargetNotFoundError if target is not registered, else None."""
        if target not in self._store.known_targets:
            available = list(self._store.known_targets.keys())
            return TargetNotFoundError(target, available, config_path)
        return None

    def _missing_field_errors(
        self,
        config: dict[str, Any],
        reference: TargetEntry,
        config_path: str,
    ) -> list[MissingFieldError]:
        """Return list of MissingFieldError for any required fields not present."""
        errors: list[MissingFieldError] = []

        for param_name, param in reference.decisive_init_parameters.items():
            # Skip if has default value
            if param.default is not Parameter.empty:
                continue
            # Skip if has default factory (VAR_KEYWORD, VAR_POSITIONAL)
            if param.kind in (Parameter.VAR_KEYWORD, Parameter.VAR_POSITIONAL):
                continue

            if param_name not in config:
                errors.append(
                    MissingFieldError(param_name, reference.name, config_path)
                )

        return errors

    def _type_errors(
        self,
        config: dict[str, Any],
        reference: TargetEntry,
        config_path: str,
    ) -> list[ValidationError]:
        """Return list of type validation errors for config values."""
        errors: list[ValidationError] = []

        try:
            type_hints = get_type_hints(reference.target_class)
        except Exception:
            # If we can't get type hints, skip type validation
            return errors

        for param_name, param in reference.decisive_init_parameters.items():
            if param_name not in config:
                continue

            value = config[param_name]
            expected_type = type_hints.get(param_name)

            if expected_type is None:
                continue

            field_path = f"{config_path}.{param_name}" if config_path else param_name

            # Check if value is an explicit nested config (has _target_)
            if self._is_nested_config(value):
                target_name = value[TARGET_KEY]
                self._maybe_auto_register_target(target_name, expected_type)

                # Recursively validate nested config
                nested_result = self.validate(value, field_path)
                errors.extend(nested_result.errors)

                # Also validate that the target class matches the expected type
                if nested_result.valid:
                    errors.extend(
                        self._check_target_type_compatibility(
                            value, expected_type, param_name, field_path
                        )
                    )

            # Check if value could be an implicit nested config (dict without _target_)
            elif could_be_implicit_nested(value, expected_type):
                # Try to infer target or report error
                errors.extend(
                    self._implicit_nested_errors(
                        value, expected_type, param_name, field_path
                    )
                )

            else:
                # Validate regular type
                type_error = self._type_mismatch_error(
                    param_name, value, expected_type, field_path
                )
                if type_error:
                    errors.append(type_error)

        return errors

    def _is_nested_config(self, value: Any) -> bool:
        """Check if a value is a nested config (dict with _target_)."""
        return isinstance(value, dict) and TARGET_KEY in value

    def _maybe_auto_register_target(self, target_name: str, expected_type: type) -> None:
        """Auto-register a target if not registered and matches expected type.

        Only registers if the target name matches the expected class name (case-insensitive)
        and the class is not abstract.

        :param target_name: The target name from the config.
        :param expected_type: The expected type from the parent's type hint.
        """
        if target_name in self._store.known_targets:
            return

        class_type = extract_class_from_hint(expected_type)
        if class_type is None:
            return

        if inspect.isabstract(class_type):
            return

        if target_name.lower() == class_type.__name__.lower():
            self._store.register(target_name, class_type)

    def _implicit_nested_errors(
        self,
        value: dict[str, Any],
        expected_type: type,
        field_name: str,
        field_path: str,
    ) -> list[ValidationError]:
        """Return validation errors for an implicit nested config (dict without _target_).

        If the type is concrete, infers the target and validates.
        If the type is ambiguous, returns an appropriate error.
        """
        errors: list[ValidationError] = []

        # Extract the class type from the hint
        class_type = extract_class_from_hint(expected_type)

        if class_type is None:
            # Should not happen if could_be_implicit_nested returned True
            return errors

        # Check if the type is concrete (can be inferred)
        is_concrete_result, inferred_target, matching_targets = is_concrete_type(
            self._store, class_type
        )

        if is_concrete_result:
            if inferred_target is None:
                inferred_target = register_inferred_target(self._store, class_type)
            # Type is concrete - inject the target and validate
            augmented_config = {TARGET_KEY: inferred_target, **value}
            nested_result = self.validate(augmented_config, field_path)

            if not nested_result.valid:
                # Wrap validation errors in TypeInferenceError
                errors.append(
                    TypeInferenceError(
                        field_name,
                        class_type,
                        nested_result.errors,
                        field_path,
                    )
                )
        else:
            # Type is ambiguous - report detailed error
            errors.append(
                AmbiguousTargetError(
                    field_name,
                    class_type,
                    matching_targets,
                    inspect.isabstract(class_type),
                    field_path,
                )
            )

        return errors

    def _check_target_type_compatibility(
        self,
        value: dict[str, Any],
        expected_type: type | None,
        field_name: str,
        field_path: str,
    ) -> list[ValidationError]:
        """Check that an explicit _target_ class is compatible with the expected type.

        :param value: The nested config dict with _target_.
        :param expected_type: Expected type from parent's type hint.
        :param field_name: Name of the field being validated.
        :param field_path: Full path for error messages.
        :return: List of validation errors (empty if valid).
        """
        errors: list[ValidationError] = []

        if expected_type is None:
            return errors

        # Extract the class type from the hint
        class_type = extract_class_from_hint(expected_type)

        if class_type is None:
            return errors

        target_name = value[TARGET_KEY]
        if target_name not in self._store.known_targets:
            return errors  # Target not found error already handled elsewhere

        target_class = self._store.known_targets[target_name].target_class

        # Check if target_class is a subclass of expected type
        try:
            if not issubclass(target_class, class_type):
                errors.append(
                    TargetTypeMismatchError(
                        field_name,
                        target_name,
                        target_class,
                        class_type,
                        field_path,
                    )
                )
        except TypeError:
            # issubclass can raise TypeError for some types
            pass

        return errors

    def _type_mismatch_error(
        self,
        field_name: str,
        value: Any,
        expected_type: type,
        config_path: str,
    ) -> TypeMismatchError | None:
        """Return TypeMismatchError if value doesn't match expected type, else None."""
        if self._type_matches(value, expected_type):
            return None

        return TypeMismatchError(
            field_name,
            self._type_repr(expected_type),
            type(value),
            config_path,
        )

    def _type_matches(self, value: Any, expected_type: type) -> bool:
        """Check if a value matches an expected type."""
        if self._is_unconstrained_type(expected_type):
            return True

        origin = get_origin(expected_type)
        args = get_args(expected_type)

        if value is None:
            return self._matches_none_type(expected_type, origin, args)
        if is_union_hint(expected_type):
            return self._matches_union_type(value, args)
        if origin in _LIST_LIKE_ORIGINS:
            return self._matches_list_type(value, args)
        if origin in _DICT_LIKE_ORIGINS:
            return self._matches_dict_type(value, args)
        if origin is None:
            return self._matches_basic_type(value, expected_type)
        # Unhandled parameterized generic (e.g., Callable)
        return False

    def _is_unconstrained_type(self, expected_type: Any) -> bool:
        """Check if a type hint accepts any value (Any, object, or a TypeVar)."""
        return expected_type is Any or expected_type is object or isinstance(expected_type, TypeVar)

    def _matches_none_type(
        self, expected_type: type, origin: type | None, args: tuple[type, ...]
    ) -> bool:
        """Check if None matches the expected type."""
        if is_union_hint(expected_type) and type(None) in args:
            return True
        return expected_type is type(None)

    def _matches_union_type(self, value: Any, args: tuple[type, ...]) -> bool:
        """Check if value matches any type in a Union."""
        return any(self._type_matches(value, arg) for arg in args)

    def _matches_list_type(self, value: Any, args: tuple[type, ...]) -> bool:
        """Check if value matches a list type."""
        if not isinstance(value, list):
            return False
        if not args:
            return True
        return all(self._type_matches(item, args[0]) for item in value)

    def _matches_dict_type(self, value: Any, args: tuple[type, ...]) -> bool:
        """Check if value matches a dict type."""
        if not isinstance(value, dict):
            return False
        if not args:
            return True
        key_type, value_type = args
        return all(
            self._type_matches(k, key_type) and self._type_matches(v, value_type)
            for k, v in value.items()
        )

    def _matches_basic_type(self, value: Any, expected_type: type) -> bool:
        """Check if value matches a basic (non-generic) type."""
        # Explicit nested config - validated recursively
        if isinstance(value, dict) and TARGET_KEY in value:
            return True

        # Implicit nested config (dict without _target_ matching class type)
        if isinstance(value, dict) and is_class_type(expected_type):
            return True  # Validated by _implicit_nested_errors

        # Direct type check
        return isinstance(value, expected_type)

    def _type_repr(self, t: type) -> str:
        """Get a readable string representation of a type."""
        origin = get_origin(t)
        args = get_args(t)

        if is_union_hint(t):
            if type(None) in args:
                non_none = [a for a in args if a is not type(None)]
                if len(non_none) == 1:
                    return f"{self._type_repr(non_none[0])} | None"
            return " | ".join(self._type_repr(a) for a in args)

        if origin in _LIST_LIKE_ORIGINS:
            origin_name = getattr(origin, "__name__", str(origin))
            if args:
                return f"{origin_name}[{self._type_repr(args[0])}]"
            return origin_name

        if origin in _DICT_LIKE_ORIGINS:
            origin_name = getattr(origin, "__name__", str(origin))
            if args:
                return f"{origin_name}[{self._type_repr(args[0])}, {self._type_repr(args[1])}]"
            return origin_name

        if hasattr(t, "__name__"):
            return t.__name__

        return str(t)

    def validate_override_path(
        self, path: list[str | int], config: dict[str, Any]
    ) -> type | None:
        """Validate that an override path exists and return its expected type.

        Traverses the config structure following the path, checking that each
        segment exists and is valid. Uses type hints from registered target
        classes to determine the expected type at the final path location.

        :param path: List of keys/indices representing the override path.
        :param config: The configuration dictionary to validate against.
        :return: Expected type from class type hints, or None if no hint available.
        :raises InvalidOverridePathError: If the path doesn't exist in the config.
        """
        if not path:
            raise InvalidOverridePathError(path, "Empty path")

        # Validate path exists using shared utility
        try:
            navigate_path(config, path)
        except PathNavigationError as e:
            raise InvalidOverridePathError(path, e.message) from e

        # Collect type hints (path is known valid)
        return self._collect_type_at_path(path, config)

    def _collect_type_at_path(
        self, path: list[str | int], config: dict[str, Any]
    ) -> type | None:
        """Collect type hint at the end of a validated path.

        :param path: Validated path to traverse.
        :param config: The configuration dictionary.
        :return: Expected type from class type hints, or None if no hint available.
        """
        current = config
        current_type: type | None = None

        for key in path:
            if isinstance(key, int):
                current_type = self._get_list_element_type(current_type)
                current = current[key]
            else:
                current_type = self._get_field_type(current, key)
                current = current[key]

        return current_type

    def _get_list_element_type(self, current_type: type | None) -> type | None:
        """Extract element type from a list-like type hint.

        :param current_type: Current type hint (should be a list-like type).
        :return: Element type if available, None otherwise.
        """
        if current_type is None:
            return None
        origin = get_origin(current_type)
        args = get_args(current_type)
        if origin in _LIST_LIKE_ORIGINS and args:
            return args[0]
        return None

    def _get_field_type(self, config: dict[str, Any], field_name: str) -> type | None:
        """Get the expected type for a field based on the config's target class.

        :param config: Config dict that may contain a _target_ key.
        :param field_name: Name of the field to get type for.
        :return: Expected type from class type hints, or None if not available.
        """
        if TARGET_KEY not in config:
            return None

        target_name = config[TARGET_KEY]
        if target_name not in self._store.known_targets:
            return None

        reference = self._store.known_targets[target_name]

        try:
            type_hints = get_type_hints(reference.target_class)
        except Exception:
            return None

        return type_hints.get(field_name)
