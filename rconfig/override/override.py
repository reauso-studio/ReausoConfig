"""Override parsing and application for CLI and programmatic config overrides.

This module provides functionality to parse override strings (like "model.lr=0.01")
and apply them to configuration dictionaries before instantiation.
"""

import copy
import re
from dataclasses import dataclass
from typing import Any, Literal

from rconfig.coercion import coerced_value
from rconfig.errors import InvalidOverrideSyntaxError
from rconfig.interpolation.parser import has_interpolation
from rconfig._internal.path_utils import PathNavigationError, navigate_path


@dataclass
class Override:
    """Represents a single configuration override.

    :param path: List of keys/indices to traverse (e.g., ["model", "layers", 0, "size"]).
    :param value: The value to set, add, or None for remove operations.
    :param operation: The type of override operation.
    :param source_type: Where this override came from ("cli" or "programmatic").
    :param cli_arg: Original CLI argument string (for CLI overrides).
    :param is_literal: If True, value was quoted and should not be converted to _ref_.
    """

    path: list[str | int]
    value: Any
    operation: Literal["set", "add", "remove"]
    source_type: Literal["cli", "programmatic"] = "programmatic"
    cli_arg: str | None = None
    is_literal: bool = False


# Regex patterns for parsing override keys
_IDENTIFIER_PATTERN = r"[a-zA-Z_][a-zA-Z0-9_]*"
_INDEX_PATTERN = r"\[(\d+)\]"
_SEGMENT_PATTERN = rf"({_IDENTIFIER_PATTERN})(?:{_INDEX_PATTERN})?"
_PATH_PATTERN = rf"^(\+|~)?({_SEGMENT_PATTERN}(?:\.{_SEGMENT_PATTERN})*)$"
_COMPILED_PATH_PATTERN = re.compile(_PATH_PATTERN)
_COMPILED_SEGMENT_PATTERN = re.compile(_SEGMENT_PATTERN)


def parse_override_key(key: str) -> tuple[list[str | int], Literal["set", "add", "remove"]]:
    """Parse an override key into a path and operation.

    :param key: Override key string (e.g., "model.lr", "+callbacks", "~dropout").
    :return: Tuple of (path, operation).
    :raises InvalidOverrideSyntaxError: If the key cannot be parsed.

    Examples::

        parse_override_key("model.lr")
        # (["model", "lr"], "set")

        parse_override_key("layers[0].size")
        # (["layers", 0, "size"], "set")

        parse_override_key("+callbacks")
        # (["callbacks"], "add")

        parse_override_key("~dropout")
        # (["dropout"], "remove")
    """
    match = _COMPILED_PATH_PATTERN.match(key)
    if not match:
        raise InvalidOverrideSyntaxError(key, "Invalid override key syntax")

    prefix = match.group(1)
    path_str = match.group(2)

    # Determine operation from prefix
    if prefix == "+":
        operation: Literal["set", "add", "remove"] = "add"
    elif prefix == "~":
        operation = "remove"
    else:
        operation = "set"

    # Parse path segments
    path: list[str | int] = []
    for segment_match in _COMPILED_SEGMENT_PATTERN.finditer(path_str):
        identifier = segment_match.group(1)
        index_str = segment_match.group(2)

        path.append(identifier)
        if index_str is not None:
            path.append(int(index_str))

    return path, operation


def parse_override_value(raw: str, expected_type: type | None = None) -> Any:
    """Parse a string value, optionally coercing to an expected type.

    :param raw: Raw string value from CLI or config.
    :param expected_type: Expected type from class type hints, or None for auto-inference.
    :return: Parsed value.
    :raises ValueError: If the value cannot be coerced to the expected type.

    Type coercion priority:
    1. If expected_type is provided, attempt to convert to that type
    2. Otherwise, use YAML-style inference:
       - "true"/"false" -> bool
       - Integer pattern -> int
       - Float pattern -> float
       - Everything else -> string
    """
    # Interpolations are resolved later and coerced with the rest of the config
    if has_interpolation(raw):
        return raw

    # If expected type is provided, try to coerce
    if expected_type is not None:
        return _coerce_to_type(raw, expected_type)

    # YAML-style auto-inference
    return _infer_value_type(raw)


def _coerce_to_type(raw: str, expected_type: type) -> Any:
    """Coerce a string value to the expected type.

    CLI overrides keep YAML list syntax (``[a, b]``) for list fields, since
    ``key=a,b`` already means a sweep for multirun.
    """
    return coerced_value(raw, expected_type, construct_unknown=True)


def _infer_value_type(raw: str) -> Any:
    """Infer the type of a string value using YAML-style rules."""
    # Check for boolean
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False

    # Check for None
    if raw.lower() in ("none", "null", "~"):
        return None

    # Check for integer
    try:
        return int(raw)
    except ValueError:
        pass

    # Check for float
    try:
        return float(raw)
    except ValueError:
        pass

    # Check for list or dict (YAML syntax)
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return _parse_yaml_value(raw)
        except Exception:
            pass

    # Default to string
    return raw


def _parse_yaml_value(raw: str) -> Any:
    """Parse a YAML-formatted value string."""
    try:
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe")
        return yaml.load(raw)
    except Exception as e:
        raise ValueError(f"Cannot parse YAML value: {raw}") from e


def parse_cli_arg(arg: str) -> Override | None:
    """Parse a single CLI argument as an override.

    :param arg: CLI argument string.
    :return: Override object if the arg is an override, None otherwise.

    An argument is considered an override if it matches:
    - key=value (set operation)
    - +key=value (add operation)
    - ~key (remove operation)

    Non-override args (like --help, -v) return None.
    """
    # Skip args that look like flags
    if arg.startswith("-") and not arg.startswith("~"):
        return None

    # Check for remove operation (no value required)
    if arg.startswith("~"):
        key = arg[1:]
        # Reject ~key=value syntax (remove doesn't take a value)
        if "=" in key:
            return None
        try:
            path, operation = parse_override_key(arg)
            return Override(
                path=path,
                value=None,
                operation=operation,
                source_type="cli",
                cli_arg=arg,
            )
        except InvalidOverrideSyntaxError:
            return None

    # Check for set or add operation (requires =)
    if "=" not in arg:
        return None

    key, _, value = arg.partition("=")

    try:
        path, operation = parse_override_key(key)
    except InvalidOverrideSyntaxError:
        return None

    # Check for quoted value (literal string, skip _ref_ shorthand)
    is_literal = False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]  # Strip quotes
        is_literal = True

    # Parse value (type inference happens later with type hints)
    return Override(
        path=path,
        value=value,
        operation=operation,
        source_type="cli",
        cli_arg=arg,
        is_literal=is_literal,
    )


def extract_cli_overrides(argv: list[str]) -> list[Override]:
    """Extract override-style arguments from a list of CLI args.

    :param argv: List of CLI arguments (typically sys.argv[1:]).
    :return: List of Override objects extracted from argv.

    Non-override arguments are silently ignored.
    """
    overrides = []
    for arg in argv:
        override = parse_cli_arg(arg)
        if override is not None:
            overrides.append(override)
    return overrides


def parse_dict_overrides(overrides: dict[str, Any]) -> list[Override]:
    """Convert a dictionary of overrides to Override objects.

    :param overrides: Dictionary with override keys and values.
    :return: List of Override objects.

    Examples::

        parse_dict_overrides({"model.lr": 0.01})
        # [Override(["model", "lr"], 0.01, "set")]

        parse_dict_overrides({"+callbacks": "logger", "~dropout": None})
        # [Override(["callbacks"], "logger", "add"), Override(["dropout"], None, "remove")]
    """
    result = []
    for key, value in overrides.items():
        path, operation = parse_override_key(key)
        result.append(Override(path=path, value=value, operation=operation))
    return result


def apply_overrides(
    config: dict[str, Any],
    overrides: list[Override],
    provenance: Any | None = None,
) -> dict[str, Any]:
    """Apply a list of overrides to a configuration dictionary.

    :param config: Original configuration dictionary.
    :param overrides: List of Override objects to apply.
    :param provenance: Optional Provenance object to update with override sources.
    :return: New configuration dictionary with overrides applied.

    The original config is not modified; a deep copy is made.
    Overrides are applied in order, so later overrides win on conflict.
    """
    result = copy.deepcopy(config)

    for override in overrides:
        _apply_single_override(result, override, provenance)

    return result


def _apply_single_override(
    config: dict[str, Any],
    override: Override,
    provenance: Any | None = None,
) -> None:
    """Apply a single override to a config dict (mutates in place).

    :param config: The config dict to modify.
    :param override: The override to apply.
    :param provenance: Optional Provenance object to update.
    """
    if not override.path:
        return

    current = _navigate_to_parent(config, override.path)
    final_key = override.path[-1]

    if override.operation == "set":
        _apply_set(current, final_key, override.value)
        # Update provenance for set operations
        if provenance is not None:
            _update_provenance_for_override(provenance, override)
    elif override.operation == "add":
        _apply_add(current, final_key, override.value)
        # For add operations, provenance tracking is more complex
        # (appending to a list) - skip for now
    elif override.operation == "remove":
        _apply_remove(current, final_key)
        # Remove operations don't need provenance tracking
        # (the value is being deleted)


def _update_provenance_for_override(provenance: Any, override: Override) -> None:
    """Update provenance to record that a value came from an override.

    :param provenance: The ProvenanceBuilder object to update.
    :param override: The override that was applied.
    """
    # Convert path list to dot-notation string
    path_str = ".".join(str(p) for p in override.path)

    # Get existing entry to record what we're overriding
    existing_entry = provenance.get(path_str)
    overrode = None
    if existing_entry is not None:
        overrode = f"{existing_entry.file}:{existing_entry.line}"

    # Add entry with override info using builder's add method
    provenance.add(
        path_str,
        file="<override>",
        line=0,
        overrode=overrode,
        source_type=override.source_type,
        cli_arg=override.cli_arg if override.source_type == "cli" else None,
        value=override.value,
    )


def _navigate_to_parent(config: dict[str, Any], path: list[str | int]) -> Any:
    """Navigate to the parent of the target location in the config.

    :param config: The configuration dictionary.
    :param path: Full path including the target key.
    :return: The parent container (dict or list) of the target.
    :raises KeyError: If navigation fails.
    """
    try:
        return navigate_path(config, path, stop_before_last=True)
    except PathNavigationError as e:
        raise KeyError(f"{e.message} at path {e.path[:e.segment_index+1]}") from e


def _apply_set(current: Any, final_key: str | int, value: Any) -> None:
    """Apply a set operation to the target location.

    :param current: Parent container of the target.
    :param final_key: Key or index of the target.
    :param value: Value to set.
    :raises KeyError: If the target location is invalid.
    """
    if isinstance(final_key, int):
        if not isinstance(current, list):
            raise KeyError(f"Cannot access index {final_key} on non-list")
        if final_key < 0 or final_key >= len(current):
            raise KeyError(f"List index {final_key} out of range")
        current[final_key] = value
    else:
        if not isinstance(current, dict):
            raise KeyError(f"Cannot access key '{final_key}' on non-dict")
        current[final_key] = value


def _apply_add(current: Any, final_key: str | int, value: Any) -> None:
    """Apply an add operation to append a value to a list field.

    :param current: Parent container of the target.
    :param final_key: Key of the target field.
    :param value: Value to add.
    :raises ValueError: If add operation is invalid for this target.
    :raises KeyError: If the target location is invalid.
    """
    if isinstance(final_key, int):
        raise ValueError("Cannot use add operation with list index")
    if not isinstance(current, dict):
        raise KeyError(f"Cannot access key '{final_key}' on non-dict")
    if final_key not in current:
        current[final_key] = [value]
    elif isinstance(current[final_key], list):
        current[final_key].append(value)
    else:
        raise ValueError(f"Cannot add to non-list field '{final_key}'")


def _apply_remove(current: Any, final_key: str | int) -> None:
    """Apply a remove operation to delete a key or list element.

    :param current: Parent container of the target.
    :param final_key: Key or index to remove.
    :raises KeyError: If the target doesn't exist or location is invalid.
    """
    if isinstance(final_key, int):
        if not isinstance(current, list):
            raise KeyError(f"Cannot access index {final_key} on non-list")
        if final_key < 0 or final_key >= len(current):
            raise KeyError(f"List index {final_key} out of range")
        del current[final_key]
    else:
        if not isinstance(current, dict):
            raise KeyError(f"Cannot access key '{final_key}' on non-dict")
        if final_key not in current:
            raise KeyError(f"Key '{final_key}' not found for removal")
        del current[final_key]


def _should_convert_to_ref(
    key_path: list[str | int],
    config: dict[str, Any],
) -> bool:
    """Check if CLI override should be converted to _ref_ assignment.

    Returns True if the target field exists and is a dict. This enables
    the CLI shorthand where ``model=models/vit.yaml`` is automatically
    converted to ``model._ref_=models/vit.yaml``.

    :param key_path: Path to the target field (e.g., ["model"] or ["trainer", "model"]).
    :param config: The configuration dictionary to check against.
    :return: True if the target field is a dict, False otherwise.

    Examples::

        config = {"model": {"_target_": "resnet"}, "name": "experiment"}
        _should_convert_to_ref(["model"], config)  # True (model is dict)
        _should_convert_to_ref(["name"], config)   # False (name is string)
        _should_convert_to_ref(["new"], config)    # False (doesn't exist)
    """
    try:
        target = navigate_path(config, key_path)
        return isinstance(target, dict)
    except PathNavigationError:
        # Field doesn't exist - no shorthand
        return False


def apply_cli_overrides_with_ref_shorthand(
    config: dict[str, Any],
    overrides: list[Override],
    provenance: Any | None = None,
) -> dict[str, Any]:
    """Apply CLI overrides with automatic _ref_ shorthand conversion.

    For CLI overrides where the target field is a dict and the value is not
    quoted, this function converts ``key=value`` to ``key._ref_=value``.

    :param config: Original configuration dictionary.
    :param overrides: List of Override objects to apply.
    :param provenance: Optional Provenance object to update with override sources.
    :return: New configuration dictionary with overrides applied.

    Examples::

        # Config: {"model": {"_target_": "resnet"}, "name": "exp1"}
        # Override: model=models/vit.yaml
        # Result: model._ref_ is set to "models/vit.yaml"

        # Override: name=models/vit.yaml
        # Result: name is set to "models/vit.yaml" (no conversion, name is string)

        # Override: model="models/vit.yaml" (quoted)
        # Result: model is set to "models/vit.yaml" (no conversion, quoted)
    """
    result = copy.deepcopy(config)

    for override in overrides:
        # Check if this override should be converted to _ref_
        if (
            override.source_type == "cli"
            and override.operation == "set"
            and not override.is_literal
            and isinstance(override.value, str)
            and _should_convert_to_ref(override.path, result)
        ):
            # Convert to _ref_ assignment
            ref_override = Override(
                path=override.path + ["_ref_"],
                value=override.value,
                operation="set",
                source_type=override.source_type,
                cli_arg=override.cli_arg,
                is_literal=False,
            )
            _apply_single_override(result, ref_override, provenance)
        else:
            _apply_single_override(result, override, provenance)

    return result
