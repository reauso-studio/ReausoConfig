"""Custom exceptions for ReausoConfig.

This module defines the exception hierarchy used throughout the library
for configuration loading, validation, and instantiation errors.
"""

import re
from pathlib import Path
from typing import Any

from rconfig._internal.path_utils import StrOrPath, ensure_path


# Matches environment variable references inside an interpolation expression
_ENV_REFERENCE_PATTERN = re.compile(r"env:([A-Za-z_][A-Za-z0-9_]*)")


def _format_location(config_path: str) -> str:
    """Format a config path for error messages.

    :param config_path: Path in config (e.g., "model.encoder").
    :return: Formatted location string or empty string if path is empty.
    """
    return f" at '{config_path}'" if config_path else ""


class ConfigError(Exception):
    """Base exception for all ReausoConfig errors."""


class ConfigFileError(ConfigError):
    """Raised when a config file cannot be read or parsed.

    :param path: Path to the problematic config file. Accepts str, Path, or any os.PathLike.
    :param reason: Description of what went wrong.
    :param hint: Optional hint for how to fix the error.
    """

    def __init__(self, path: StrOrPath, reason: str, hint: str = "") -> None:
        self.path = ensure_path(path)
        self.reason = reason
        self.hint = hint
        message = f"Failed to load config file '{self.path}': {reason}"
        if hint:
            message += f"\nHint: {hint}"
        super().__init__(message)


class TargetNotFoundError(ConfigError):
    """Raised when a _target_ identifier is not registered in ConfigStore.

    :param target: The unregistered target identifier.
    :param available: List of currently registered target names.
    :param config_path: Path in config where error occurred (e.g., "model.encoder").
    """

    def __init__(
        self,
        target: str,
        available: list[str],
        config_path: str = "",
    ) -> None:
        self.target = target
        self.available = available
        self.config_path = config_path

        location = _format_location(config_path)
        available_str = ", ".join(f"'{name}'" for name in available) if available else "(none)"
        super().__init__(
            f"Target '{target}'{location} is not registered. "
            f"Available targets: {available_str}\n"
            f"Hint: Register the target using @config.register('{target}') decorator "
            f"or config.register(MyClass, '{target}')."
        )


class ValidationError(ConfigError):
    """Base exception for validation errors.

    :param config_path: Path in config where error occurred (e.g., "model.encoder").
    """

    def __init__(self, message: str, config_path: str = "") -> None:
        self.config_path = config_path
        super().__init__(message)


class MissingFieldError(ValidationError):
    """Raised when a required field is missing from the config.

    :param field: Name of the missing field.
    :param target: Target class name that requires this field.
    :param config_path: Path in config where error occurred.
    """

    def __init__(self, field: str, target: str, config_path: str = "") -> None:
        self.field = field
        self.target = target

        location = _format_location(config_path)
        super().__init__(
            f"Missing required field '{field}' for target '{target}'{location}\n"
            f"Hint: Add the '{field}' field to your config or provide a default value "
            f"in the target class.",
            config_path,
        )


class TypeMismatchError(ValidationError):
    """Raised when a field value has an incompatible type.

    :param field: Name of the field with wrong type.
    :param expected: Expected type or type description.
    :param actual: Actual type of the provided value.
    :param config_path: Path in config where error occurred.
    """

    def __init__(
        self,
        field: str,
        expected: type | str,
        actual: type,
        config_path: str = "",
    ) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual

        expected_name = expected if isinstance(expected, str) else expected.__name__
        location = _format_location(config_path)
        super().__init__(
            f"Type mismatch for field '{field}'{location}: "
            f"expected {expected_name}, got {actual.__name__}\n"
            f"Hint: Provide a value of type '{expected_name}' or check your config.",
            config_path,
        )


class ValueCoercionError(TypeMismatchError):
    """Raised when a string value cannot be converted to the field's declared type.

    String values from environment variables, interpolations or quoted YAML are
    converted to the declared type before validation. This error reports a
    value that could not be converted, along with the expression it came from.

    :param field: Name of the field (with index for list items, e.g. "ports[0]").
    :param expected: Readable name of the expected type.
    :param value: The string value that could not be converted.
    :param reason: Why the conversion failed.
    :param config_path: Full config path of the value (e.g. "server.port").
    :param source_expression: The unresolved interpolation the value came from, if any.
    """

    def __init__(
        self,
        field: str,
        expected: str,
        value: str,
        reason: str,
        config_path: str = "",
        source_expression: str | None = None,
    ) -> None:
        self.field = field
        self.expected = expected
        self.actual = type(value)
        self.value = value
        self.reason = reason
        self.source_expression = source_expression
        self.env_vars = tuple(_ENV_REFERENCE_PATTERN.findall(source_expression or ""))

        location = _format_location(config_path)
        origin = ""
        if source_expression is not None:
            origin = f"\nValue came from '{source_expression}'"
            if self.env_vars:
                origin += f" (environment variable {', '.join(self.env_vars)})"
        ValidationError.__init__(
            self,
            f"Invalid value for field '{field}'{location}: {reason}{origin}\n"
            f"Hint: Provide a value that can be read as '{expected}'.",
            config_path,
        )


class AmbiguousTargetError(ValidationError):
    """Raised when _target_ is required but missing because the type is ambiguous.

    This occurs when a nested config dict lacks _target_ and the parent field's
    type hint is either abstract or has multiple registered implementations.

    :param field: Name of the field with the ambiguous type.
    :param expected_type: The type hint from the parent class.
    :param available_targets: List of registered targets that match this type.
    :param is_abstract: Whether the expected type is abstract.
    :param config_path: Path in config where error occurred.
    """

    def __init__(
        self,
        field: str,
        expected_type: type,
        available_targets: list[str],
        is_abstract: bool,
        config_path: str = "",
    ) -> None:
        self.field = field
        self.expected_type = expected_type
        self.available_targets = available_targets
        self.is_abstract = is_abstract

        location = _format_location(config_path)
        type_name = (
            expected_type.__name__
            if hasattr(expected_type, "__name__")
            else str(expected_type)
        )

        if is_abstract:
            reason = f"'{type_name}' is an abstract class and cannot be instantiated directly"
        else:
            reason = f"'{type_name}' has multiple registered implementations"

        targets_str = (
            ", ".join(f"'{t}'" for t in available_targets)
            if available_targets
            else "(none registered)"
        )

        message = (
            f"Cannot infer type for field '{field}'{location}.\n"
            f"Reason: {reason}.\n"
            f"Expected type: {type_name}\n"
            f"Available targets matching this type: {targets_str}\n"
            f"Hint: Use '_target_' to explicitly specify which implementation to use."
        )

        super().__init__(message, config_path)


class TargetTypeMismatchError(ValidationError):
    """Raised when an explicitly provided _target_ does not match the expected type.

    :param field: Name of the field with the type mismatch.
    :param target: The provided target name.
    :param target_class: The actual class of the target.
    :param expected_type: The expected type from parent's type hint.
    :param config_path: Path in config where error occurred.
    """

    def __init__(
        self,
        field: str,
        target: str,
        target_class: type,
        expected_type: type,
        config_path: str = "",
    ) -> None:
        self.field = field
        self.target = target
        self.target_class = target_class
        self.expected_type = expected_type

        location = _format_location(config_path)
        expected_name = (
            expected_type.__name__
            if hasattr(expected_type, "__name__")
            else str(expected_type)
        )
        actual_name = (
            target_class.__name__
            if hasattr(target_class, "__name__")
            else str(target_class)
        )

        message = (
            f"Target type mismatch for field '{field}'{location}.\n"
            f"Provided target: '{target}' (class: {actual_name})\n"
            f"Expected type: {expected_name}\n"
            f"The target class must be a subclass of the expected type."
        )

        super().__init__(message, config_path)


class TypeInferenceError(ValidationError):
    """Raised when type inference succeeds but validation of the inferred type fails.

    :param field: Name of the field where inference was attempted.
    :param inferred_type: The type that was inferred from the parent's type hint.
    :param validation_errors: List of validation errors from validating with inferred type.
    :param config_path: Path in config where error occurred.
    """

    def __init__(
        self,
        field: str,
        inferred_type: type,
        validation_errors: list["ValidationError"],
        config_path: str = "",
    ) -> None:
        self.field = field
        self.inferred_type = inferred_type
        self.validation_errors = validation_errors

        location = _format_location(config_path)
        type_name = (
            inferred_type.__name__
            if hasattr(inferred_type, "__name__")
            else str(inferred_type)
        )

        errors_str = "\n".join(f"  - {str(e)}" for e in validation_errors)

        message = (
            f"Type inference failed for field '{field}'{location}.\n"
            f"Inferred type: {type_name}\n"
            f"Validation errors:\n{errors_str}\n"
            f"Hint: If this is not the intended type, use '_target_' to specify the correct one."
        )

        super().__init__(message, config_path)


class InstantiationError(ConfigError):
    """Raised when object instantiation fails.

    :param target: Target class name that failed to instantiate.
    :param reason: Description of what went wrong.
    :param config_path: Path in config where error occurred.
    """

    def __init__(self, target: str, reason: str, config_path: str = "") -> None:
        self.target = target
        self.reason = reason
        self.config_path = config_path

        location = _format_location(config_path)
        super().__init__(
            f"Failed to instantiate target '{target}'{location}: {reason}\n"
            f"Hint: Check the constructor arguments and ensure all required "
            f"fields are provided with correct types."
        )


class CompositionError(ConfigError):
    """Base exception for config composition errors."""


class MergeError(CompositionError):
    """Raised when a merge operation fails during config composition.

    :param message: Description of what went wrong.
    :param path: The config path where the error occurred.
    :param hint: Optional hint for how to fix the error.
    """

    def __init__(self, message: str, path: str = "", hint: str = "") -> None:
        self.path = path
        self.hint = hint
        location = _format_location(path)
        msg = f"{message}{location}"
        if hint:
            msg += f"\nHint: {hint}"
        super().__init__(msg)


class CircularRefError(CompositionError):
    """Raised when a circular _ref_ dependency is detected.

    :param chain: List of file paths forming the circular chain.
    """

    def __init__(self, chain: list[str]) -> None:
        self.chain = chain
        chain_str = " → ".join(chain)
        super().__init__(
            f"Circular _ref_ dependency detected: {chain_str}\n"
            f"Hint: Break the cycle by restructuring your config files "
            f"or using _instance_ for shared objects."
        )


class RefResolutionError(CompositionError):
    """Raised when a _ref_ cannot be resolved.

    :param ref_path: The _ref_ path that failed to resolve.
    :param reason: Description of what went wrong.
    :param config_path: Path in config where error occurred.
    :param hint: Optional hint for how to fix the error.
    """

    def __init__(
        self, ref_path: str, reason: str, config_path: str = "", hint: str = ""
    ) -> None:
        self.ref_path = ref_path
        self.reason = reason
        self.config_path = config_path
        self.hint = hint

        location = _format_location(config_path)
        message = f"Failed to resolve _ref_ '{ref_path}'{location}: {reason}"
        if hint:
            message += f"\nHint: {hint}"
        super().__init__(message)


class AmbiguousRefError(CompositionError):
    """Raised when multiple files match an extension-less _ref_ path.

    :param ref_path: The _ref_ path that matched multiple files.
    :param found_files: List of file names that matched.
    :param config_path: Path in config where error occurred.
    """

    def __init__(
        self,
        ref_path: str,
        found_files: list[str],
        config_path: str = "",
    ) -> None:
        self.ref_path = ref_path
        self.found_files = found_files
        self.config_path = config_path

        location = _format_location(config_path)
        files_str = ", ".join(f"'{f}'" for f in found_files)
        super().__init__(
            f"Ambiguous _ref_ '{ref_path}'{location}: multiple files found ({files_str}). "
            f"Specify extension explicitly or remove duplicates."
        )


class RefAtRootError(CompositionError):
    """Raised when _ref_ is used at the root level of a config file.

    :param file_path: The file where _ref_ was used at root.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        super().__init__(
            f"_ref_ is not allowed at root level in '{file_path}'. "
            f"Every config file must define an object, not a reference.\n"
            f"Hint: Move the _ref_ inside a nested object, or inline the referenced content."
        )


class RefInstanceConflictError(CompositionError):
    """Raised when _ref_ and _instance_ are used in the same block.

    :param config_path: Path in config where error occurred.
    """

    def __init__(self, config_path: str = "") -> None:
        self.config_path = config_path
        location = _format_location(config_path)
        super().__init__(
            f"Cannot use both '_ref_' and '_instance_' in the same block{location}\n"
            f"Hint: Use _ref_ for file references or _instance_ for config path references, "
            f"not both."
        )


class InstanceResolutionError(CompositionError):
    """Raised when an _instance_ path cannot be resolved.

    :param instance_path: The _instance_ path that failed to resolve.
    :param reason: Description of what went wrong.
    :param config_path: Path in config where error occurred.
    :param hint: Optional hint for how to fix the error.
    """

    def __init__(
        self, instance_path: str, reason: str, config_path: str = "", hint: str = ""
    ) -> None:
        self.instance_path = instance_path
        self.reason = reason
        self.config_path = config_path
        self.hint = hint

        location = _format_location(config_path)
        message = f"Failed to resolve _instance_ '{instance_path}'{location}: {reason}"
        if hint:
            message += f"\nHint: {hint}"
        super().__init__(message)


class CircularInstanceError(CompositionError):
    """Raised when a circular _instance_ dependency is detected.

    :param chain: List of instance paths forming the circular chain.
    """

    def __init__(self, chain: list[str]) -> None:
        self.chain = chain
        chain_str = " → ".join(chain)
        super().__init__(
            f"Circular _instance_ dependency detected: {chain_str}\n"
            f"Hint: Break the cycle by restructuring your config or "
            f"inlining one of the instances."
        )


class InvalidInnerPathError(CompositionError):
    """Raised when inner_path for partial instantiation is invalid.

    :param inner_path: The path that was invalid.
    :param reason: Description of what went wrong.
    """

    def __init__(self, inner_path: str, reason: str) -> None:
        self.inner_path = inner_path
        self.reason = reason
        super().__init__(
            f"Invalid inner_path '{inner_path}' for partial instantiation: {reason}\n"
            f"Hint: Use dot notation for nested paths (e.g., 'model.encoder')."
        )


class OverrideError(ConfigError):
    """Base exception for override-related errors."""


class InvalidOverridePathError(OverrideError):
    """Raised when an override path doesn't exist in the config structure.

    :param path: The override path that was not found.
    :param reason: Description of what went wrong.
    """

    def __init__(self, path: list[str | int], reason: str) -> None:
        self.path = path
        self.reason = reason
        path_str = _format_override_path(path)
        super().__init__(
            f"Invalid override path '{path_str}': {reason}\n"
            f"Hint: Use dot notation for nested keys (e.g., 'model.lr') "
            f"and [n] for list indices."
        )


class InvalidOverrideSyntaxError(OverrideError):
    """Raised when an override string cannot be parsed.

    :param override_string: The string that could not be parsed.
    :param reason: Description of what went wrong.
    """

    def __init__(self, override_string: str, reason: str) -> None:
        self.override_string = override_string
        self.reason = reason
        super().__init__(
            f"Invalid override syntax '{override_string}': {reason}\n"
            f"Hint: Use format 'key=value', 'key.nested=value', or 'key[0]=value'."
        )


def _format_override_path(path: list[str | int]) -> str:
    """Format an override path list as a string (e.g., ["model", "layers", 0] -> "model.layers[0]")."""
    result = []
    for part in path:
        if isinstance(part, int):
            result.append(f"[{part}]")
        elif result:
            result.append(f".{part}")
        else:
            result.append(part)
    return "".join(result)


# =============================================================================
# Interpolation Errors
# =============================================================================


class InterpolationError(ConfigError):
    """Base exception for interpolation-related errors."""


class InterpolationSyntaxError(InterpolationError):
    """Raised when an interpolation expression cannot be parsed.

    :param expression: The expression that failed to parse.
    :param reason: Description of the parsing error.
    :param config_path: Path in config where the error occurred.
    """

    def __init__(
        self, expression: str, reason: str, config_path: str = ""
    ) -> None:
        self.expression = expression
        self.reason = reason
        self.config_path = config_path

        location = f" at '{config_path}'" if config_path else ""
        super().__init__(
            f"Failed to parse interpolation '${{{expression}}}'{location}: {reason}\n"
            f"Hint: Check syntax: use ${{path.to.value}} for config references, "
            f"${{env:VAR}} for environment variables."
        )


class InterpolationResolutionError(InterpolationError):
    """Raised when an interpolation expression cannot be resolved.

    :param expression: The expression that failed to resolve.
    :param reason: Description of what went wrong.
    :param config_path: Path in config where the error occurred.
    :param hint: Optional hint for how to fix the error.
    """

    def __init__(
        self, expression: str, reason: str, config_path: str = "", hint: str = ""
    ) -> None:
        self.expression = expression
        self.reason = reason
        self.config_path = config_path
        self.hint = hint

        location = f" at '{config_path}'" if config_path else ""
        message = f"Failed to resolve interpolation '${{{expression}}}'{location}: {reason}"
        if hint:
            message += f"\nHint: {hint}"
        super().__init__(message)


class CircularInterpolationError(InterpolationError):
    """Raised when circular interpolation references are detected.

    :param chain: List of config paths forming the circular chain.
    """

    def __init__(self, chain: list[str]) -> None:
        self.chain = chain
        chain_str = " → ".join(chain)
        super().__init__(
            f"Circular interpolation detected: {chain_str}\n"
            f"Hint: Break the cycle by using a literal value or restructuring your config."
        )


class EnvironmentVariableError(InterpolationError):
    """Raised when a required environment variable is not set or is empty.

    :param var_name: Name of the missing environment variable.
    :param config_path: Path in config where the error occurred.
    """

    def __init__(self, var_name: str, config_path: str = "") -> None:
        self.var_name = var_name
        self.config_path = config_path

        location = f" at '{config_path}'" if config_path else ""
        super().__init__(
            f"Environment variable '{var_name}' is not set or is empty{location}\n"
            f"Hint: Set the environment variable or use a coalesce operator for a fallback: "
            f"${{env:{var_name} ?: \"default\"}}"
        )


class ResolverError(InterpolationError):
    """Base exception for custom resolver errors."""


class UnknownResolverError(ResolverError):
    """Raised when a resolver path is not registered.

    :param path: The resolver path that was not found (e.g., "uuid", "db:lookup").
    :param available: List of currently registered resolver paths.
    :param config_path: Path in config where the error occurred.
    """

    def __init__(
        self, path: str, available: list[str], config_path: str = ""
    ) -> None:
        self.path = path
        self.available = available
        self.config_path = config_path

        location = f" at '{config_path}'" if config_path else ""
        available_str = (
            ", ".join(f"'{name}'" for name in available) if available else "(none)"
        )
        super().__init__(
            f"Resolver 'app:{path}' is not registered{location}. "
            f"Available resolvers: {available_str}\n"
            f"Hint: Register the resolver using config.register_resolver('{path}', func)."
        )


class ResolverExecutionError(ResolverError):
    """Raised when a resolver function raises an exception.

    :param path: The resolver path that failed (e.g., "uuid", "db:lookup").
    :param original_error: The exception raised by the resolver function.
    :param config_path: Path in config where the error occurred.
    """

    def __init__(
        self, path: str, original_error: Exception, config_path: str = ""
    ) -> None:
        self.path = path
        self.original_error = original_error
        self.config_path = config_path

        location = f" at '{config_path}'" if config_path else ""
        super().__init__(
            f"Resolver 'app:{path}' raised an exception{location}: "
            f"{type(original_error).__name__}: {original_error}\n"
            f"Hint: Check the resolver function implementation and its inputs."
        )


# =============================================================================
# Required Value Errors
# =============================================================================


class RequiredValueError(ValidationError):
    """Raised when _required_ values were not provided.

    :param missing: List of (path, expected_type) tuples for missing values.
    """

    def __init__(self, missing: list[tuple[str, type | None]]) -> None:
        self.missing = missing

        lines = []
        for path, expected_type in missing:
            type_hint = f" (expected: {expected_type.__name__})" if expected_type else ""
            lines.append(f"  - {path}{type_hint}")

        super().__init__(
            f"The following required values were not provided:\n"
            + "\n".join(lines)
            + "\nHint: Provide these values via overrides or in your config file."
        )


# =============================================================================
# Deprecation Errors
# =============================================================================


class DeprecationError(ConfigError):
    """Base exception for deprecation-related errors."""


# =============================================================================
# Hook Errors
# =============================================================================


class HookError(ConfigError):
    """Base exception for hook-related errors."""


class HookExecutionError(HookError):
    """Raised when a hook function raises an exception.

    :param hook_name: Name of the hook that failed.
    :param phase: The lifecycle phase during which the hook failed.
    :param original_error: The exception raised by the hook function.
    """

    def __init__(
        self,
        hook_name: str,
        phase: "HookPhase",
        original_error: Exception,
    ) -> None:
        self.hook_name = hook_name
        self.phase = phase
        self.original_error = original_error
        super().__init__(
            f"Hook '{hook_name}' failed during {phase.name}: "
            f"{type(original_error).__name__}: {original_error}\n"
            f"Hint: Check the hook implementation for errors."
        )


# Import HookPhase for type annotation (placed at end to avoid circular imports)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rconfig.hooks.models import HookPhase


class DeprecatedKeyError(DeprecationError):
    """Raised when a deprecated key is used and policy is 'error'.

    :param key: The deprecated key path.
    :param pattern: The deprecation pattern that matched.
    :param new_key: The new key to use instead (if provided).
    :param message: Custom deprecation message (if provided).
    :param remove_in: Version when the key will be removed (if provided).
    :param config_path: Path in config where error occurred.
    """

    def __init__(
        self,
        key: str,
        pattern: str,
        new_key: str | None = None,
        message: str | None = None,
        remove_in: str | None = None,
        config_path: str = "",
    ) -> None:
        self.key = key
        self.pattern = pattern
        self.new_key = new_key
        self.message = message
        self.remove_in = remove_in
        self.config_path = config_path

        location = _format_location(config_path)
        parts = [f"Deprecated key '{key}' used{location}"]

        if new_key:
            parts.append(f"Use '{new_key}' instead")
        if message:
            parts.append(message)
        if remove_in:
            parts.append(f"Will be removed in version {remove_in}")

        super().__init__(". ".join(parts))
