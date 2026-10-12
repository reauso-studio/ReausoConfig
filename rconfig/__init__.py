"""ReausoConfig - A lightweight configuration library.

This module provides a simple, pandas-like API for loading YAML config files
and instantiating Python objects from them.

Example::

    import rconfig as rc
    from dataclasses import dataclass

    @dataclass
    class ModelConfig:
        hidden_size: int
        dropout: float = 0.1

    # Register target class
    rc.register("model", ModelConfig)

    # Instantiate from config file
    model = rc.instantiate(Path("config.yaml"))

    # Type-safe version
    model = rc.instantiate(Path("config.yaml"), ModelConfig)

    # With CLI overrides (opt-in, e.g. for a training script)
    # python main.py hidden_size=512
    rc.set_cli_overrides(True)
    model = rc.instantiate(Path("config.yaml"))

    # With programmatic overrides
    model = rc.instantiate(Path("config.yaml"), overrides={"hidden_size": 512})
"""

import sys
import threading
from functools import singledispatch
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, TypeVar, overload

from ._internal.path_utils import StrOrPath, ensure_path
from .target import TargetRegistry, TargetEntry
from .help import (
    HelpIntegration,
    FunctionHelpIntegration,
    FlatHelpIntegration,
    GroupedHelpIntegration,
    ArgparseHelpIntegration,
    MULTIRUN_HELP,
)
from .multirun import (
    MultirunResult,
    MultirunIterator,
    MultirunError,
    InvalidSweepValueError,
    NoRunConfigurationError,
    generate_run_configs,
    validate_sweep_values,
    apply_ref_shorthand_to_sweep,
    extract_cli_multirun_overrides,
)

if TYPE_CHECKING:
    from .provenance import Provenance, ProvenanceBuilder
from .diff import (
    ConfigDiff,
    DiffEntry,
    DiffEntryType,
    DiffBuilder,
    DiffFormat,
    DiffFormatContext,
    DiffLayout,
    DiffFlatLayout,
    DiffTreeLayout,
    DiffMarkdownLayout,
    # Registry
    DiffLayoutEntry,
    DiffPresetEntry,
    DiffRegistry,
    get_diff_registry,
)
from .validation import ConfigValidator, ValidationResult
from .coercion import ConfigCoercer
from .instantiation import ConfigInstantiator, is_lazy_proxy, force_initialize
from .composition import (
    ConfigComposer,
    set_cache_size,
    clear_cache,
)
from .provenance import (
    Provenance,
    ProvenanceEntry,
    ProvenanceBuilder,
    InstanceRef,
    EntrySourceType,
    NodeSourceType,
    ProvenanceFormat,
    ProvenanceFormatContext,
    ProvenanceLayout,
    ProvenanceTreeLayout,
    TreeLayout,  # Backwards compatibility alias
    # Registry
    ProvenanceLayoutEntry,
    ProvenancePresetEntry,
    ProvenanceRegistry,
    get_provenance_registry,
)
from .override import (
    Override,
    apply_overrides,
    extract_cli_overrides,
    parse_dict_overrides,
    parse_override_value,
)
from .export import (
    Exporter,
    DictExporter,
    YamlExporter,
    JsonExporter,
    TomlExporter,
    FileExporter,
    SingleFileExporter,
    MultiFileExporter,
    register_exporter,
    unregister_exporter,
    get_exporter,
    supported_exporter_extensions,
)
from .loaders import (
    ConfigFileLoader,
    YamlConfigLoader,
    JsonConfigLoader,
    TomlConfigLoader,
    register_loader,
    unregister_loader,
    get_loader,
    supported_loader_extensions,
)
from .errors import (
    AmbiguousRefError,
    AmbiguousTargetError,
    CircularInstanceError,
    CircularInterpolationError,
    CircularRefError,
    CompositionError,
    ConfigError,
    ConfigFileError,
    EnvironmentVariableError,
    InstanceResolutionError,
    InstantiationError,
    InterpolationError,
    InterpolationResolutionError,
    InterpolationSyntaxError,
    InvalidInnerPathError,
    InvalidOverridePathError,
    InvalidOverrideSyntaxError,
    MergeError,
    MissingFieldError,
    OverrideError,
    RefAtRootError,
    RefInstanceConflictError,
    RefResolutionError,
    ResolverError,
    ResolverExecutionError,
    RequiredValueError,
    TargetNotFoundError,
    TargetTypeMismatchError,
    TypeInferenceError,
    TypeMismatchError,
    UnknownResolverError,
    ValidationError,
    ValueCoercionError,
)
from .interpolation.registry import ResolverRegistry
from .deprecation import (
    DeprecationInfo,
    DeprecationHandler,
    RconfigDeprecationWarning,
    get_deprecation_registry,
)
from .errors import DeprecatedKeyError, HookError, HookExecutionError
from .hooks import (
    Callback,
    HookContext,
    HookEntry,
    HookPhase,
    HookRegistry,
)

T = TypeVar("T")


# Internal singleton instances
_store = TargetRegistry()
_resolver_registry = ResolverRegistry()
_hook_registry = HookRegistry()
_validator = ConfigValidator(_store)
_instantiator = ConfigInstantiator(_store, _validator)
_coercer = ConfigCoercer(_store)

# Help integration storage (thread-safe)
_help_integration: HelpIntegration = FlatHelpIntegration()
_help_integration_lock = threading.RLock()

# CLI override policy (thread-safe). Off by default: a library embedded in another
# program must not read that program's command line unless asked to.
_cli_overrides_default = False
_cli_overrides_lock = threading.RLock()


# =============================================================================
# Hooks API
# =============================================================================


def _invoke_hooks(phase: HookPhase, context: HookContext) -> None:
    """Invoke all hooks registered for a phase.

    Internal function used by instantiate() and ConfigInstantiator.

    :param phase: The lifecycle phase.
    :param context: The context to pass to hooks.
    """
    _hook_registry.invoke(phase, context)


def register_hook(
    phase: HookPhase,
    func: Callable[[HookContext], None],
    *,
    name: str | None = None,
    pattern: str | None = None,
    priority: int = 50,
) -> None:
    """Register a hook for a configuration lifecycle phase.

    :param phase: The lifecycle phase when this hook should be invoked.
    :param func: The hook function. Must accept a HookContext parameter.
    :param name: Unique identifier for the hook. Defaults to function name.
    :param pattern: Optional glob pattern for conditional execution.
                   Hook only runs when config_path matches the pattern.
    :param priority: Execution order (lower values run first, default 50).

    Example::

        def validate_paths(ctx: HookContext) -> None:
            if ctx.config and "data" in ctx.config:
                path = Path(ctx.config["data"]["path"])
                if not path.exists():
                    raise ValueError(f"Data path not found: {path}")

        rc.register_hook(HookPhase.CONFIG_LOADED, validate_paths)
    """
    _hook_registry.register(phase, func, name=name, pattern=pattern, priority=priority)


def unregister_hook(name: str, phase: HookPhase | None = None) -> None:
    """Unregister a hook by name.

    :param name: The name of the hook to unregister.
    :param phase: If specified, only unregister from this phase.
                 If None, unregister from all phases.
    :raises KeyError: If no hook with that name exists.

    Example::

        rc.unregister_hook("validate_paths")
        rc.unregister_hook("my_hook", phase=HookPhase.CONFIG_LOADED)
    """
    _hook_registry.unregister(name, phase)


def register_callback(callback: Callback) -> None:
    """Register a class-based callback for all lifecycle phases.

    The callback's methods (on_config_loaded, on_before_instantiate, etc.)
    are registered as individual hooks.

    :param callback: A Callback subclass instance.

    Example::

        class ExperimentTracker(rc.Callback):
            def on_config_loaded(self, ctx: HookContext) -> None:
                start_tracking(ctx.config)

            def on_error(self, ctx: HookContext) -> None:
                log_failure(ctx.error)

        tracker = ExperimentTracker()
        rc.register_callback(tracker)
    """
    callback_id = id(callback)
    callback_name = callback.__class__.__name__

    # Register each overridden method as a hook
    _hook_registry.register(
        HookPhase.CONFIG_LOADED,
        callback.on_config_loaded,
        name=f"{callback_name}_{callback_id}_config_loaded",
    )
    _hook_registry.register(
        HookPhase.BEFORE_INSTANTIATE,
        callback.on_before_instantiate,
        name=f"{callback_name}_{callback_id}_before_instantiate",
    )
    _hook_registry.register(
        HookPhase.AFTER_INSTANTIATE,
        callback.on_after_instantiate,
        name=f"{callback_name}_{callback_id}_after_instantiate",
    )
    _hook_registry.register(
        HookPhase.ON_ERROR,
        callback.on_error,
        name=f"{callback_name}_{callback_id}_on_error",
    )


def unregister_callback(callback: Callback) -> None:
    """Unregister a class-based callback from all lifecycle phases.

    :param callback: The Callback instance to unregister.

    Example::

        rc.unregister_callback(tracker)
    """
    callback_id = id(callback)
    callback_name = callback.__class__.__name__

    for phase in HookPhase:
        suffix = phase.name.lower()
        hook_name = f"{callback_name}_{callback_id}_{suffix}"
        try:
            _hook_registry.unregister(hook_name, phase)
        except KeyError:
            pass  # Hook may not be registered for this phase


def known_hooks() -> MappingProxyType[HookPhase, tuple[HookEntry, ...]]:
    """Return a read-only view of all registered hooks.

    :return: Mapping from HookPhase to tuple of HookEntry objects.

    Example::

        for phase, hooks in rc.known_hooks().items():
            for hook in hooks:
                print(f"{phase.name}: {hook.name}")
    """
    return _hook_registry.known_hooks


def on_config_loaded(
    func: Callable[[HookContext], None] | None = None,
    *,
    pattern: str | None = None,
    priority: int = 50,
) -> Callable[[HookContext], None] | Callable[[Callable[[HookContext], None]], Callable[[HookContext], None]]:
    """Decorator to register a CONFIG_LOADED hook.

    Called after config file is loaded and composed (refs resolved),
    before interpolation resolution.

    :param func: The hook function (when used without parentheses).
    :param pattern: Optional glob pattern for conditional execution.
    :param priority: Execution order (lower values run first, default 50).
    :return: The decorated function.

    Example::

        @rc.on_config_loaded
        def validate_paths(ctx: HookContext) -> None:
            '''Validate data paths exist.'''
            ...

        @rc.on_config_loaded(pattern="**/model/*.yaml", priority=10)
        def validate_model(ctx: HookContext) -> None:
            '''Validate model configs only, run early.'''
            ...
    """
    def decorator(f: Callable[[HookContext], None]) -> Callable[[HookContext], None]:
        _hook_registry.register(
            HookPhase.CONFIG_LOADED, f, name=f.__name__, pattern=pattern, priority=priority
        )
        return f

    if func is not None:
        return decorator(func)
    return decorator


def on_before_instantiate(
    func: Callable[[HookContext], None] | None = None,
    *,
    pattern: str | None = None,
    priority: int = 50,
) -> Callable[[HookContext], None] | Callable[[Callable[[HookContext], None]], Callable[[HookContext], None]]:
    """Decorator to register a BEFORE_INSTANTIATE hook.

    Called before each object's constructor is called (per nested config
    with _target_).

    :param func: The hook function (when used without parentheses).
    :param pattern: Optional glob pattern for conditional execution.
    :param priority: Execution order (lower values run first, default 50).
    :return: The decorated function.

    Example::

        @rc.on_before_instantiate
        def inject_secrets(ctx: HookContext) -> None:
            '''Log before each instantiation.'''
            print(f"Creating {ctx.target_name} at {ctx.inner_path}")
    """
    def decorator(f: Callable[[HookContext], None]) -> Callable[[HookContext], None]:
        _hook_registry.register(
            HookPhase.BEFORE_INSTANTIATE, f, name=f.__name__, pattern=pattern, priority=priority
        )
        return f

    if func is not None:
        return decorator(func)
    return decorator


def on_after_instantiate(
    func: Callable[[HookContext], None] | None = None,
    *,
    pattern: str | None = None,
    priority: int = 50,
) -> Callable[[HookContext], None] | Callable[[Callable[[HookContext], None]], Callable[[HookContext], None]]:
    """Decorator to register an AFTER_INSTANTIATE hook.

    Called after each object's constructor returns (per nested config
    with _target_).

    :param func: The hook function (when used without parentheses).
    :param pattern: Optional glob pattern for conditional execution.
    :param priority: Execution order (lower values run first, default 50).
    :return: The decorated function.

    Example::

        @rc.on_after_instantiate
        def register_metrics(ctx: HookContext) -> None:
            '''Register each instantiated object with metrics system.'''
            metrics.register(ctx.target_name, ctx.instance)
    """
    def decorator(f: Callable[[HookContext], None]) -> Callable[[HookContext], None]:
        _hook_registry.register(
            HookPhase.AFTER_INSTANTIATE, f, name=f.__name__, pattern=pattern, priority=priority
        )
        return f

    if func is not None:
        return decorator(func)
    return decorator


def on_error(
    func: Callable[[HookContext], None] | None = None,
    *,
    pattern: str | None = None,
    priority: int = 50,
) -> Callable[[HookContext], None] | Callable[[Callable[[HookContext], None]], Callable[[HookContext], None]]:
    """Decorator to register an ON_ERROR hook.

    Called when an error occurs during instantiation.

    :param func: The hook function (when used without parentheses).
    :param pattern: Optional glob pattern for conditional execution.
    :param priority: Execution order (lower values run first, default 50).
    :return: The decorated function.

    Example::

        @rc.on_error
        def log_failures(ctx: HookContext) -> None:
            '''Log instantiation failures.'''
            logger.error(f"Failed: {ctx.error}")
    """
    def decorator(f: Callable[[HookContext], None]) -> Callable[[HookContext], None]:
        _hook_registry.register(
            HookPhase.ON_ERROR, f, name=f.__name__, pattern=pattern, priority=priority
        )
        return f

    if func is not None:
        return decorator(func)
    return decorator


def set_help_integration(integration: HelpIntegration) -> None:
    """Set a custom help integration.

    Thread-safe: protected by internal lock.

    :param integration: A HelpIntegration instance. Cannot be None.
    :raises ValueError: If integration is None.

    Example::

        from rconfig.help import GroupedHelpIntegration

        rc.set_help_integration(GroupedHelpIntegration())

        # Or a custom integration
        class CustomIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                # Custom integration logic
                ...

        rc.set_help_integration(CustomIntegration())
    """
    if integration is None:
        raise ValueError("integration cannot be None")

    global _help_integration
    with _help_integration_lock:
        _help_integration = integration


def current_help_integration() -> HelpIntegration:
    """Return the current help integration.

    Thread-safe: protected by internal lock.
    Returns the default FlatHelpIntegration if none was explicitly set.

    :return: The current HelpIntegration (never None).

    Example::

        integration = rc.current_help_integration()
        print(f"Using: {integration.__class__.__name__}")
    """
    with _help_integration_lock:
        return _help_integration


def help_integration(func: Callable[["Provenance", str], None]) -> Callable[["Provenance", str], None]:
    """Decorator to register a function as the help integration.

    The decorated function is responsible for all behavior including
    calling sys.exit() if needed. The framework only calls the function
    when --help/-h is detected.

    :param func: Integration function with signature (provenance, config_path) -> None.
    :return: The same function (for use as decorator).

    Example::

        @rc.help_integration
        def my_integration(provenance, config_path):
            for path, entry in provenance.items():
                print(f"{path}: {entry.type_hint}")
            sys.exit(0)
    """
    set_help_integration(FunctionHelpIntegration(func))
    return func


def set_cli_overrides(enabled: bool) -> None:
    """Set whether config loading reads ``sys.argv`` by default.

    When enabled, ``key=value`` arguments are applied as overrides and
    ``--help``/``-h`` shows config help. It is disabled by default, so loading
    config inside a web app, worker or test run never touches the host
    program's command line. A per-call ``cli_overrides`` argument takes
    precedence over this setting.

    Thread-safe: protected by internal lock.

    :param enabled: True to read CLI overrides by default, False to ignore sys.argv.

    Example::

        # At the start of a training script
        rc.set_cli_overrides(True)
        model = rc.instantiate(Path("config.yaml"))  # python train.py lr=0.01
    """
    global _cli_overrides_default
    with _cli_overrides_lock:
        _cli_overrides_default = enabled


def cli_overrides_enabled() -> bool:
    """Return whether config loading reads ``sys.argv`` by default.

    Thread-safe: protected by internal lock.

    :return: The process-wide default set by set_cli_overrides() (False initially).
    """
    with _cli_overrides_lock:
        return _cli_overrides_default


def register(name: str, target: type) -> None:
    """Register a target class under a unique name.

    :param name: Unique identifier for the target class.
    :param target: Class to register.

    Example::

        @dataclass
        class ModelConfig:
            hidden_size: int

        rc.register("model", ModelConfig)
    """
    _store.register(name, target)


def unregister(name: str) -> None:
    """Unregister a previously registered configuration reference.

    :param name: Identifier of the reference to unregister.
    :raises KeyError: If no reference with that name exists.
    """
    _store.unregister(name)


# =============================================================================
# Internal Pipeline Helpers
# =============================================================================


def _effective_cli_overrides(cli_overrides: bool | None) -> bool:
    """Resolve a per-call cli_overrides argument against the process-wide default."""
    if cli_overrides is None:
        return cli_overrides_enabled()
    return cli_overrides


def _handle_help_request(
    path: Path,
    *,
    inner_path: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> None:
    """Hand config help to the help integration when --help/-h is in sys.argv.

    Only called when CLI overrides are enabled. The provenance passed to the
    integration never applies CLI overrides, so other command-line arguments
    cannot break the help output.
    """
    if "--help" not in sys.argv and "-h" not in sys.argv:
        return

    integration = current_help_integration()

    # Consume --help/-h from sys.argv if integration requests it
    if integration.consume_help_flag:
        sys.argv = [arg for arg in sys.argv if arg not in ("--help", "-h")]

    # Get provenance with type hints and descriptions
    provenance = get_provenance(
        path, inner_path=inner_path, overrides=overrides, cli_overrides=False
    )

    # Call the integration (it's responsible for sys.exit() if needed)
    integration.integrate(provenance, str(path))


def _collected_overrides(overrides: dict[str, Any] | None, cli_enabled: bool) -> list[Override]:
    """Return programmatic overrides followed by CLI overrides (CLI wins on conflict)."""
    collected: list[Override] = []
    if overrides:
        collected.extend(parse_dict_overrides(overrides))
    if cli_enabled:
        collected.extend(extract_cli_overrides(sys.argv[1:]))
    return collected


def _coerce_override_values(overrides: list[Override], config: dict[str, Any]) -> None:
    """Validate override paths and coerce string values to the target field types."""
    for override in overrides:
        expected_type_hint = _validator.validate_override_path(override.path, config)
        if override.operation == "set" and isinstance(override.value, str):
            override.value = parse_override_value(override.value, expected_type_hint)


def _typed_config(
    config: dict[str, Any],
    unresolved: dict[str, Any],
    *,
    inner_path: str | None = None,
) -> dict[str, Any]:
    """Return the resolved config with strings converted to declared field types.

    :param config: The config after interpolation.
    :param unresolved: The same config before interpolation (for error messages).
    :param inner_path: If given, only values inside this section can fail.
    :return: The config with converted values.
    :raises ValueCoercionError: For the first value that cannot be converted.
    """
    coercion = _coercer.coerced(config, unresolved)
    errors = [
        error for error in coercion.errors
        if inner_path is None or _is_within_path(error.config_path, inner_path)
    ]
    if errors:
        raise errors[0]
    return coercion.config


def _is_within_path(path: str, parent: str) -> bool:
    """Check if a config path is the parent path or lies inside it."""
    return path == parent or path.startswith(f"{parent}.") or path.startswith(f"{parent}[")


def validate(
    path: StrOrPath,
    *,
    inner_path: str | None = None,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
) -> ValidationResult:
    """Validate a config file without instantiating (dry-run).

    Composes the config (resolving _ref_ and _instance_ references), applies
    any overrides, and validates against registered targets. Also checks that
    all _required_ values have been satisfied.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param inner_path: Optional path to validate only a section of the config.
                       When specified, only the sub-config at this path is validated
                       and _required_ markers outside this section are ignored.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :return: ValidationResult with any errors found.
    :raises InvalidInnerPathError: If inner_path doesn't exist or is invalid.

    Example::

        result = rc.validate(Path("config.yaml"))
        if not result.valid:
            for error in result.errors:
                print(error)

        # With overrides to satisfy _required_ values
        result = rc.validate(
            Path("config.yaml"),
            overrides={"api_key": "secret123"},
        )

        # Validate only a section
        result = rc.validate(Path("trainer.yaml"), inner_path="model")
    """
    from rconfig.interpolation import resolve_interpolations
    from rconfig.validation.required import find_required_markers
    from rconfig.errors import RequiredValueError

    path = ensure_path(path)

    # Handle --help/-h when CLI overrides are enabled
    cli_enabled = _effective_cli_overrides(cli_overrides)
    if cli_enabled:
        _handle_help_request(path)

    composer = ConfigComposer()
    config = composer.compose(path)

    # Collect overrides (CLI wins on conflict), validate paths and coerce values
    all_overrides = _collected_overrides(overrides, cli_enabled)
    _coerce_override_values(all_overrides, config)

    # Apply overrides
    if all_overrides:
        config = apply_overrides(config, all_overrides)

    # Resolve interpolations on the full config, as instantiate() does
    unresolved = config
    try:
        config = resolve_interpolations(config)
    except InterpolationError:
        # An interpolation may depend on an unsatisfied _required_ value,
        # which is reported as a RequiredValueError below instead
        if not find_required_markers(config):
            raise

    # Handle partial validation with inner_path
    if inner_path is not None:
        from rconfig._internal.path_utils import get_value_at_path
        from rconfig._internal.type_inference import infer_target_from_parent

        try:
            sub_config = get_value_at_path(config, inner_path)
            unresolved = get_value_at_path(unresolved, inner_path)
        except (KeyError, IndexError, TypeError) as e:
            raise InvalidInnerPathError(inner_path, str(e))

        if not isinstance(sub_config, dict):
            raise InvalidInnerPathError(
                inner_path,
                f"Expected dict at path, got {type(sub_config).__name__}",
            )

        # If sub-config has no _target_, try to infer from parent's type hint
        if "_target_" not in sub_config:
            inferred_target = infer_target_from_parent(config, inner_path, _store)
            if inferred_target:
                sub_config = {"_target_": inferred_target, **sub_config}

        config = sub_config

    # Convert strings to declared field types; unconvertible values are reported
    coercion = _coercer.coerced(config, unresolved if isinstance(unresolved, dict) else None)
    config = coercion.config

    # Check for unsatisfied _required_ values
    required_markers = find_required_markers(config)
    required_errors: list[ValidationError] = []
    if required_markers:
        missing = [(m.path, m.expected_type) for m in required_markers]
        required_errors.append(RequiredValueError(missing))

    # Run regular validation
    result = _validator.validate(config)

    # A value that could not be converted is reported once, by its coercion error
    coercion_error_paths = {error.config_path for error in coercion.errors}
    validation_errors = [
        error for error in result.errors
        if not (isinstance(error, TypeMismatchError) and error.config_path in coercion_error_paths)
    ]

    # Combine required value, coercion and validation errors
    all_errors = required_errors + list(coercion.errors) + validation_errors
    return ValidationResult(valid=len(all_errors) == 0, errors=all_errors)


@overload
def instantiate(path: StrOrPath, *, cli_overrides: bool | None = ..., lazy: bool = ...) -> Any: ...
@overload
def instantiate(path: StrOrPath, expected_type: type[T], *, cli_overrides: bool | None = ..., lazy: bool = ...) -> T: ...
@overload
def instantiate(
    path: StrOrPath, *, overrides: dict[str, Any], cli_overrides: bool | None = ..., lazy: bool = ...
) -> Any: ...
@overload
def instantiate(
    path: StrOrPath,
    expected_type: type[T],
    *,
    overrides: dict[str, Any],
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> T: ...
@overload
def instantiate(
    path: StrOrPath, *, inner_path: str, cli_overrides: bool | None = ..., lazy: bool = ...
) -> Any: ...
@overload
def instantiate(
    path: StrOrPath,
    expected_type: type[T],
    *,
    inner_path: str,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> T: ...
@overload
def instantiate(
    path: StrOrPath,
    *,
    inner_path: str,
    overrides: dict[str, Any],
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> Any: ...
@overload
def instantiate(
    path: StrOrPath,
    expected_type: type[T],
    *,
    inner_path: str,
    overrides: dict[str, Any],
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> T: ...


def instantiate(
    path: StrOrPath,
    expected_type: type[T] | None = None,
    *,
    inner_path: str | None = None,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    lazy: bool = False,
) -> T | Any:
    """Load, compose, validate, and instantiate a config file.

    Composes the config (resolving _ref_ and _instance_ references), applies
    any overrides, validates against registered targets, and instantiates
    the final object tree.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param expected_type: Optional type for type-safe returns.
    :param inner_path: Optional path to instantiate only a section of the config.
                       Interpolations are resolved from the full config before
                       extraction. External _instance_ refs are auto-instantiated.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :param lazy: If True, all nested configs are lazily instantiated.
                 Lazy objects delay __init__ until first attribute access.
    :return: Instantiated object (typed if expected_type provided).
    :raises ConfigFileError: If file cannot be loaded.
    :raises CircularRefError: If circular _ref_ references are detected.
    :raises CircularInstanceError: If circular _instance_ references are detected.
    :raises RefResolutionError: If a _ref_ cannot be resolved.
    :raises InstanceResolutionError: If an _instance_ path cannot be resolved.
    :raises InvalidInnerPathError: If inner_path doesn't exist or is invalid.
    :raises ValidationError: If config is invalid.
    :raises InvalidOverridePathError: If an override path doesn't exist.
    :raises InvalidOverrideSyntaxError: If an override string is malformed.
    :raises InstantiationError: If instantiation fails.

    Example::

        # From file
        model = rc.instantiate(Path("config.yaml"))

        # Type-safe version
        model = rc.instantiate(Path("config.yaml"), ModelConfig)

        # Partial instantiation - only instantiate a section
        model = rc.instantiate(Path("trainer.yaml"), inner_path="model")
        encoder = rc.instantiate(Path("trainer.yaml"), inner_path="model.encoder")

        # With programmatic overrides
        model = rc.instantiate(Path("config.yaml"), overrides={"model.lr": 0.01})

        # Read CLI overrides for this call only (or use rc.set_cli_overrides(True))
        model = rc.instantiate(Path("config.yaml"), cli_overrides=True)

        # With lazy instantiation (all nested configs are lazy)
        model = rc.instantiate(Path("config.yaml"), lazy=True)

        # CLI help (--help or -h) shows config entries and exits
        # python main.py --help
    """
    path = ensure_path(path)

    # Handle --help/-h when CLI overrides are enabled
    cli_enabled = _effective_cli_overrides(cli_overrides)
    if cli_enabled:
        _handle_help_request(path)

    # Compose config (resolve _ref_ and _instance_)
    composer = ConfigComposer()
    config = composer.compose(path)
    instance_targets = composer.instance_targets

    # Invoke CONFIG_LOADED hooks (may modify config via return value)
    config = _hook_registry.invoke(
        HookPhase.CONFIG_LOADED,
        HookContext(
            phase=HookPhase.CONFIG_LOADED,
            config_path=str(path),
            config=MappingProxyType(config),
        ),
        config,
    )

    # Collect overrides (CLI wins on conflict), validate paths and coerce values
    all_overrides = _collected_overrides(overrides, cli_enabled)
    _coerce_override_values(all_overrides, config)

    # Apply overrides
    if all_overrides:
        config = apply_overrides(config, all_overrides)

    # Resolve interpolations (${...} expressions) - always on full config
    from rconfig.interpolation import resolve_interpolations

    unresolved = config
    config = resolve_interpolations(config)

    # Convert strings (env values, interpolation results) to declared field types
    config = _typed_config(config, unresolved, inner_path=inner_path)

    # Handle partial instantiation
    if inner_path is not None:
        from rconfig._internal.partial import extract_partial_config
        from rconfig._internal.path_utils import get_value_at_path
        from rconfig._internal.type_inference import infer_target_from_parent

        # Extract sub-config (interpolations already resolved from full config)
        sub_config, processed_targets, external_targets = extract_partial_config(
            config=config,
            inner_path=inner_path,
            instance_targets=instance_targets,
        )

        # If sub-config has no _target_, try to infer from parent's type hint
        if "_target_" not in sub_config:
            inferred_target = infer_target_from_parent(config, inner_path, _store)
            if inferred_target:
                sub_config = {"_target_": inferred_target, **sub_config}

        # Check for unsatisfied _required_ values in extracted sub-config only
        from rconfig.validation.required import find_required_markers
        from rconfig.errors import RequiredValueError

        required_markers = find_required_markers(sub_config)
        if required_markers:
            missing = [(m.path, m.expected_type) for m in required_markers]
            raise RequiredValueError(missing)

        # Pre-instantiate external targets
        external_instances: dict[str, Any] = {}
        for ext_path in external_targets:
            ext_config = get_value_at_path(config, ext_path)
            if isinstance(ext_config, dict) and "_target_" in ext_config:
                external_instances[f"__external__:{ext_path}"] = (
                    _instantiator.instantiate(
                        ext_config,
                        instance_targets={},
                        config_path=ext_path,
                        config_path_for_hooks=str(path),
                    )
                )

        try:
            return _instantiator.instantiate(
                sub_config,
                instance_targets=processed_targets,
                external_instances=external_instances,
                lazy=lazy,
                config_path_for_hooks=str(path),
            )
        except Exception as e:
            # Invoke ON_ERROR hooks
            _invoke_hooks(
                HookPhase.ON_ERROR,
                HookContext(
                    phase=HookPhase.ON_ERROR,
                    config_path=str(path),
                    config=MappingProxyType(sub_config),
                    inner_path=inner_path,
                    error=e,
                ),
            )
            raise

    # Check for unsatisfied _required_ values on full config
    from rconfig.validation.required import find_required_markers
    from rconfig.errors import RequiredValueError

    required_markers = find_required_markers(config)
    if required_markers:
        missing = [(m.path, m.expected_type) for m in required_markers]
        raise RequiredValueError(missing)

    try:
        return _instantiator.instantiate(
            config,
            instance_targets=instance_targets,
            lazy=lazy,
            config_path_for_hooks=str(path),
        )
    except Exception as e:
        # Invoke ON_ERROR hooks
        _invoke_hooks(
            HookPhase.ON_ERROR,
            HookContext(
                phase=HookPhase.ON_ERROR,
                config_path=str(path),
                config=MappingProxyType(config),
                error=e,
            ),
        )
        raise


# === Multirun API ===


@overload
def instantiate_multirun(
    path: StrOrPath,
    *,
    sweep: dict[str, list[Any]],
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[Any]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    expected_type: type[T],
    *,
    sweep: dict[str, list[Any]],
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[T]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    *,
    experiments: list[dict[str, Any]],
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[Any]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    expected_type: type[T],
    *,
    experiments: list[dict[str, Any]],
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[T]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    *,
    sweep: dict[str, list[Any]],
    experiments: list[dict[str, Any]],
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[Any]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    expected_type: type[T],
    *,
    sweep: dict[str, list[Any]],
    experiments: list[dict[str, Any]],
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[T]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    *,
    sweep: dict[str, list[Any]] | None = ...,
    experiments: list[dict[str, Any]] | None = ...,
    overrides: dict[str, Any] | None = ...,
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[Any]: ...
@overload
def instantiate_multirun(
    path: StrOrPath,
    expected_type: type[T],
    *,
    sweep: dict[str, list[Any]] | None = ...,
    experiments: list[dict[str, Any]] | None = ...,
    overrides: dict[str, Any] | None = ...,
    inner_path: str | None = ...,
    cli_overrides: bool | None = ...,
    lazy: bool = ...,
) -> MultirunIterator[T]: ...


def instantiate_multirun(
    path: StrOrPath,
    expected_type: type[T] | None = None,
    *,
    sweep: dict[str, list[Any]] | None = None,
    experiments: list[dict[str, Any]] | None = None,
    overrides: dict[str, Any] | None = None,
    inner_path: str | None = None,
    cli_overrides: bool | None = None,
    lazy: bool = False,
) -> MultirunIterator[T] | MultirunIterator[Any]:
    """Generate and instantiate multiple config combinations from sweeps and experiments.

    Creates a lazy iterator that generates configs from sweep parameters (cartesian
    product) and/or explicit experiments. Each iteration yields a MultirunResult
    containing the resolved config, applied overrides, and instantiated object.

    :param path: Path to the base config file. Accepts str, Path, or any os.PathLike.
    :param expected_type: Optional type for type-safe returns.
    :param sweep: Dict of parameter paths to lists of values (cartesian product).
    :param experiments: List of explicit experiment override dicts.
    :param overrides: Constant overrides applied to all runs (lowest priority).
    :param inner_path: Optional path to instantiate only a section of the config.
                       Interpolations are resolved from the full config before
                       extraction. External _instance_ refs are auto-instantiated.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :param lazy: If True, nested configs delay __init__ until first access.
    :return: MultirunIterator with length, slicing, and reversal support.
    :raises NoRunConfigurationError: If neither sweep nor experiments provided.
    :raises InvalidInnerPathError: If inner_path doesn't exist or is invalid.
    :raises ValueError: If sweep values are not lists.

    **Override Priority:** CLI > experiment/sweep > constant overrides

    Example::

        import rconfig as rc
        from pathlib import Path

        # Sweep only (cartesian product)
        for result in rc.instantiate_multirun(
            path=Path("config.yaml"),
            sweep={"model.lr": [0.01, 0.001], "model.layers": [4, 8]},
        ):
            train(result.instance)  # 4 runs total

        # Experiments only
        for result in rc.instantiate_multirun(
            path=Path("config.yaml"),
            experiments=[
                {"model": "models/resnet"},
                {"model": "models/vit"},
            ],
        ):
            train(result.instance)  # 2 runs total

        # Both sweep and experiments (cartesian product)
        for result in rc.instantiate_multirun(
            path=Path("config.yaml"),
            experiments=[{"model": "models/resnet"}, {"model": "models/vit"}],
            sweep={"optimizer.lr": [0.01, 0.001]},
        ):
            train(result.instance)  # 4 runs total

        # Iterator features
        results = rc.instantiate_multirun(...)
        len(results)           # Total run count
        results[50:]           # Resume from index 50
        reversed(results)      # Reverse order
        results[3]             # Single run at index 3

        # Partial instantiation with inner_path
        for result in rc.instantiate_multirun(
            path=Path("trainer.yaml"),
            inner_path="model",  # Only instantiate the model section
            sweep={"lr": [0.01, 0.001]},
        ):
            model = result.instance  # Only the model section

        # Error handling
        for result in rc.instantiate_multirun(...):
            try:
                train(result.instance)
            except Exception as e:
                log_failure(result.overrides, e)
                continue
    """
    import copy

    from rconfig.interpolation import resolve_interpolations
    from rconfig.validation.required import find_required_markers
    from rconfig.override import apply_cli_overrides_with_ref_shorthand

    path = ensure_path(path)

    # Validate inputs
    sweep = sweep or {}
    experiments = experiments or []
    overrides = overrides or {}

    # Validate sweep values are lists
    if sweep:
        validate_sweep_values(sweep)

    # Handle --help/-h when CLI overrides are enabled
    cli_enabled = _effective_cli_overrides(cli_overrides)
    if cli_enabled:
        _handle_help_request(path)

    # Parse CLI multirun arguments
    cli_regular_overrides: list[Override] = []
    cli_sweep: dict[str, list[Any]] = {}
    cli_experiments: list[dict[str, Any]] = []

    if cli_enabled:
        cli_regular_overrides, cli_sweep, cli_experiments = extract_cli_multirun_overrides(
            sys.argv[1:]
        )

    # Merge CLI sweep into programmatic sweep (CLI wins on conflict)
    merged_sweep = {**sweep, **cli_sweep}

    # Merge CLI experiments into programmatic experiments
    merged_experiments = experiments + cli_experiments

    # Check that at least one of sweep or experiments is provided
    has_sweep = bool(merged_sweep)
    has_experiments = bool(merged_experiments)

    if not has_sweep and not has_experiments:
        raise NoRunConfigurationError(has_overrides=bool(overrides))

    # Generate run configurations (just override dicts, fast)
    run_configs = generate_run_configs(
        sweep=merged_sweep,
        experiments=merged_experiments,
        overrides=overrides,
    )

    # Compose base config once (will be deep-copied for each run)
    composer = ConfigComposer()
    base_config = composer.compose(path)
    instance_targets = composer.instance_targets

    def instantiate_single_run(run_overrides: dict[str, Any]) -> MultirunResult[T]:
        """Instantiate a single run configuration.

        This function is called lazily during iteration.
        """
        try:
            # Deep copy the base config
            config = copy.deepcopy(base_config)

            # Apply _ref_ shorthand to sweep values targeting dict fields
            transformed_overrides = apply_ref_shorthand_to_sweep(run_overrides, config)

            # Convert to Override objects
            run_override_list = parse_dict_overrides(transformed_overrides)

            # Collect all overrides in priority order
            all_overrides: list[Override] = []

            # Run-specific overrides (from sweep/experiments)
            all_overrides.extend(run_override_list)

            # CLI regular overrides (highest priority)
            all_overrides.extend(cli_regular_overrides)

            # Validate paths and coerce values
            _coerce_override_values(all_overrides, config)

            # Apply overrides with _ref_ shorthand for CLI overrides
            if cli_regular_overrides:
                config = apply_cli_overrides_with_ref_shorthand(
                    config, cli_regular_overrides
                )
            if run_override_list:
                config = apply_overrides(config, run_override_list)

            # Check for unsatisfied _required_ values
            required_markers = find_required_markers(config)
            if required_markers:
                missing = [(m.path, m.expected_type) for m in required_markers]
                raise RequiredValueError(missing)

            # Resolve interpolations, then convert strings to declared field types
            unresolved = config
            config = resolve_interpolations(config)
            config = _typed_config(config, unresolved, inner_path=inner_path)

            # Handle partial instantiation
            if inner_path is not None:
                from rconfig._internal.partial import extract_partial_config
                from rconfig._internal.path_utils import get_value_at_path
                from rconfig._internal.type_inference import infer_target_from_parent

                # Extract sub-config (interpolations already resolved from full config)
                sub_config, processed_targets, external_targets = extract_partial_config(
                    config=config,
                    inner_path=inner_path,
                    instance_targets=instance_targets,
                )

                # If sub-config has no _target_, try to infer from parent's type hint
                if "_target_" not in sub_config:
                    inferred_target = infer_target_from_parent(config, inner_path, _store)
                    if inferred_target:
                        sub_config = {"_target_": inferred_target, **sub_config}

                # Pre-instantiate external targets
                external_instances: dict[str, Any] = {}
                for ext_path in external_targets:
                    ext_config = get_value_at_path(config, ext_path)
                    if isinstance(ext_config, dict) and "_target_" in ext_config:
                        external_instances[f"__external__:{ext_path}"] = (
                            _instantiator.instantiate(
                                ext_config, instance_targets={}, config_path=ext_path
                            )
                        )

                instance = _instantiator.instantiate(
                    sub_config,
                    instance_targets=processed_targets,
                    external_instances=external_instances,
                    lazy=lazy,
                )
            else:
                # Instantiate full config
                instance = _instantiator.instantiate(
                    config, instance_targets=instance_targets, lazy=lazy
                )

            # Wrap config in MappingProxyType for immutability
            immutable_config = MappingProxyType(config)
            immutable_overrides = MappingProxyType(run_overrides)

            return MultirunResult(
                config=immutable_config,
                overrides=immutable_overrides,
                _instance=instance,
                _error=None,
            )

        except Exception as e:
            # Store the error in the result
            immutable_config = MappingProxyType({})
            immutable_overrides = MappingProxyType(run_overrides)

            return MultirunResult(
                config=immutable_config,
                overrides=immutable_overrides,
                _instance=None,
                _error=e,
            )

    return MultirunIterator(run_configs, instantiate_single_run)


def known_targets() -> MappingProxyType[str, TargetEntry]:
    """Get a read-only view of all registered target entries.

    :return: Immutable mapping of name to TargetEntry.
    """
    return _store.known_targets


# Type variable for the resolver decorator
F = TypeVar("F", bound=Callable[..., Any])


def register_resolver(*path: str, func: Callable[..., Any]) -> None:
    """Register a custom resolver function.

    Resolvers can be invoked in interpolation expressions using the syntax:
    ``${app:resolver_name}`` or ``${app:namespace:resolver_name(args)}``.

    :param path: One or more path components (e.g., "uuid" or "db", "lookup").
    :param func: The resolver function to register.
    :raises ValueError: If path is empty or func is not callable.

    Example::

        def gen_uuid() -> str:
            import uuid
            return str(uuid.uuid4())

        rc.register_resolver("uuid", func=gen_uuid)

        # Namespaced resolver
        def db_lookup(table: str, id: int) -> dict:
            return database.get(table, id)

        rc.register_resolver("db", "lookup", func=db_lookup)
    """
    _resolver_registry.register(*path, func=func)


def unregister_resolver(*path: str) -> None:
    """Unregister a previously registered resolver.

    :param path: One or more path components (e.g., "uuid" or "db", "lookup").
    :raises KeyError: If no resolver with that path exists.

    Example::

        rc.unregister_resolver("uuid")
        rc.unregister_resolver("db", "lookup")
    """
    _resolver_registry.unregister(*path)


def resolver(*path: str) -> Callable[[F], F]:
    """Decorator to register a resolver function.

    Resolvers can be invoked in interpolation expressions using the syntax:
    ``${app:resolver_name}`` or ``${app:namespace:resolver_name(args)}``.

    If the resolver function has a parameter named ``_config_``, it will receive
    the current config dictionary (read-only) when invoked.

    :param path: One or more path components (e.g., "uuid" or "db", "lookup").
    :return: Decorator function.

    Example::

        @rc.resolver("uuid")
        def gen_uuid() -> str:
            import uuid
            return str(uuid.uuid4())

        @rc.resolver("db", "lookup")
        def db_lookup(table: str, id: int) -> dict:
            return database.get(table, id)

        @rc.resolver("derive")
        def derive(path: str, *, _config_: dict) -> Any:
            # Access config values
            return get_nested_value(_config_, path)
    """

    def decorator(func: F) -> F:
        register_resolver(*path, func=func)
        return func

    return decorator


def get_provenance(
    path: StrOrPath,
    *,
    inner_path: str | None = None,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
) -> "Provenance":
    """Compose a config file and track the origin of each value.

    :param path: Path to the entry-point config file. Accepts str, Path, or any os.PathLike.
    :param inner_path: If specified, returns provenance only for this section.
                      Also uses lazy loading to only load needed files.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :return: Provenance object with origin information for each config value.

    Example::

        prov = rc.get_provenance(Path("trainer.yaml"))
        print(prov)  # Shows config with file:line annotations
        entry = prov.get("model.layers")  # Get specific origin info
        for path, entry in prov.items():
            print(f"{path}: {entry.file}:{entry.line}")

        # Partial provenance (lazy loading)
        prov = rc.get_provenance(Path("trainer.yaml"), inner_path="model")
        # Returns provenance only for model section and its dependencies

        # With overrides
        prov = rc.get_provenance(
            Path("config.yaml"),
            overrides={"model.lr": 0.01}
        )

        # Include CLI overrides for this call
        prov = rc.get_provenance(Path("config.yaml"), cli_overrides=True)
    """
    from rconfig.interpolation import resolve_interpolations
    from rconfig.provenance import ProvenanceBuilder
    from rconfig.composition.IncrementalComposer import IncrementalComposer
    from rconfig.composition.InstanceResolver import InstanceResolver

    path = ensure_path(path)

    # Handle --help/-h when CLI overrides are enabled
    cli_enabled = _effective_cli_overrides(cli_overrides)
    if cli_enabled:
        _handle_help_request(path, inner_path=inner_path, overrides=overrides)

    # Create builder for accumulating provenance during composition
    builder = ProvenanceBuilder()

    # Compose the config tree using incremental algorithm
    composer = IncrementalComposer(None, builder)
    result = composer.compose(path, inner_path=inner_path)

    # Resolve all _instance_ references
    instance_resolver = InstanceResolver(builder)
    config = instance_resolver.resolve(result.instances, result.config)

    # Collect overrides (CLI wins on conflict), validate paths and coerce values
    all_overrides = _collected_overrides(overrides, cli_enabled)
    _coerce_override_values(all_overrides, config)

    # Apply overrides
    if all_overrides:
        config = apply_overrides(config, all_overrides)

    # Set initial config
    builder.set_config(config)

    # Resolve interpolations and update builder with interpolation sources
    resolved = resolve_interpolations(config, builder)

    # Convert strings to declared field types and record the converted values.
    # Provenance does not validate, so a value that cannot be converted is kept as-is.
    coercion = _coercer.coerced(resolved, config)
    for coerced_path, value in coercion.coerced_paths.items():
        entry = builder.get_entry(coerced_path)
        if entry is not None:
            entry.value = value
    builder.set_config(coercion.config)

    # Resolve target class information from registered targets
    builder.resolve_targets(_store.known_targets)

    # Build the final immutable provenance
    return builder.build()


# === Config Diffing API ===


def diff(
    left: "StrOrPath | Provenance",
    right: "StrOrPath | Provenance",
    *,
    left_inner_path: str | None = None,
    right_inner_path: str | None = None,
    left_overrides: dict[str, Any] | None = None,
    right_overrides: dict[str, Any] | None = None,
    cli_overrides: bool = False,
) -> ConfigDiff:
    """Compare two configurations and report differences.

    Accepts either path objects (which are resolved to Provenance internally)
    or Provenance objects directly. Returns a ConfigDiff with added, removed,
    changed, and unchanged entries.

    :param left: Left (original/base) config - str, Path, os.PathLike, or Provenance.
    :param right: Right (new/updated) config - str, Path, os.PathLike, or Provenance.
    :param left_inner_path: Optional path to compare only a section of left config.
    :param right_inner_path: Optional path to compare only a section of right config.
    :param left_overrides: Overrides to apply to left config (Path only).
    :param right_overrides: Overrides to apply to right config (Path only).
    :param cli_overrides: Whether to parse CLI overrides (default False for diff).
    :return: ConfigDiff object with all differences.

    Example::

        import rconfig as rc
        from pathlib import Path

        # Compare two config files
        diff = rc.diff(Path("config_v1.yaml"), Path("config_v2.yaml"))

        # Check if configs are identical
        if diff.is_empty():
            print("Configs are identical")

        # Access differences by type
        for path, entry in diff.added.items():
            print(f"Added: {path} = {entry.right_value}")

        for path, entry in diff.changed.items():
            print(f"Changed: {path}: {entry.left_value} -> {entry.right_value}")

        # Format output
        print(diff.format().terminal())
        print(diff.format().markdown())
        print(diff.format().show_provenance().tree())

        # Compare specific sections
        diff = rc.diff(
            Path("trainer.yaml"), Path("trainer_new.yaml"),
            left_inner_path="model",
            right_inner_path="model",
        )

        # Compare with overrides
        diff = rc.diff(
            Path("config.yaml"), Path("config.yaml"),
            left_overrides={"model.lr": 0.001},
            right_overrides={"model.lr": 0.01},
        )

        # Reuse existing provenance
        prov1 = rc.get_provenance(Path("config_v1.yaml"))
        prov2 = rc.get_provenance(Path("config_v2.yaml"))
        diff = rc.diff(prov1, prov2)
    """
    # Resolve left to Provenance if needed
    if not isinstance(left, Provenance):
        left_prov = get_provenance(
            ensure_path(left),
            inner_path=left_inner_path,
            overrides=left_overrides,
            cli_overrides=cli_overrides,
        )
    else:
        left_prov = left

    # Resolve right to Provenance if needed
    if not isinstance(right, Provenance):
        right_prov = get_provenance(
            ensure_path(right),
            inner_path=right_inner_path,
            overrides=right_overrides,
            cli_overrides=cli_overrides,
        )
    else:
        right_prov = right

    # Use DiffBuilder to compute the diff
    builder = DiffBuilder()
    return builder.compute_diff(left_prov, right_prov)


# === Formatting API ===


@overload
def format(obj: "Provenance", layout: "ProvenanceLayout | None" = None) -> ProvenanceFormat: ...
@overload
def format(obj: ConfigDiff) -> DiffFormat: ...


@singledispatch
def format(obj: Any, layout: Any = None) -> Any:
    """Format provenance or diff objects for display.

    Returns a fluent builder for configuring output format. Use method
    chaining to customize what information is shown and how it's formatted.

    :param obj: A Provenance or ConfigDiff object to format.
    :param layout: Optional custom layout (Provenance only).
    :return: ProvenanceFormat or DiffFormat builder for method chaining.
    :raises TypeError: If obj is not a supported type.

    Example::

        import rconfig as rc
        from pathlib import Path

        # Format provenance
        prov = rc.get_provenance(Path("config.yaml"))
        print(rc.format(prov))                    # Default tree format
        print(rc.format(prov).minimal())          # Minimal preset
        print(rc.format(prov).hide_chain())       # Hide interpolation chain

        # Format diff
        diff = rc.diff(Path("v1.yaml"), Path("v2.yaml"))
        print(rc.format(diff).terminal())         # Terminal output
        print(rc.format(diff).markdown())         # Markdown table
        print(rc.format(diff).show_provenance())  # Include file:line info
    """
    raise TypeError(f"Cannot format object of type {type(obj).__name__}")


@format.register(Provenance)
def _format_provenance(
    obj: "Provenance", layout: "ProvenanceLayout | None" = None
) -> ProvenanceFormat:
    return ProvenanceFormat(obj, layout)


@format.register(ConfigDiff)
def _format_diff(obj: ConfigDiff) -> DiffFormat:
    return DiffFormat(obj)


# === Deprecation API ===


def deprecate(
    old_key: str,
    *,
    new_key: str | None = None,
    message: str | None = None,
    remove_in: str | None = None,
    policy: str | None = None,
) -> None:
    """Register a deprecated configuration key.

    Supports exact paths and glob-style patterns:
    - Exact: "model.lr" matches only "model.lr"
    - Single wildcard (*): "*.lr" matches "model.lr", "encoder.lr" (one level)
    - Double wildcard (**): "**.lr" matches "a.b.c.lr" (any depth)

    :param old_key: The deprecated key pattern (exact path or glob).
    :param new_key: Optional new key location for auto-mapping.
    :param message: Optional custom deprecation message.
    :param remove_in: Optional version when the key will be removed.
    :param policy: Per-deprecation policy override ("warn", "error", "ignore").

    Example::

        # Register a simple deprecation
        rc.deprecate("learning_rate", new_key="model.optimizer.lr")

        # With version and message
        rc.deprecate(
            "n_epochs",
            new_key="training.epochs",
            message="Use 'training.epochs' instead",
            remove_in="2.0.0",
        )

        # Glob patterns
        rc.deprecate("**.dropout", message="Dropout configured elsewhere")
        rc.deprecate("*.lr", message="Use full path 'optimizer.learning_rate'")

        # Per-deprecation policy (always error for this key)
        rc.deprecate("critical_key", policy="error")
    """
    registry = get_deprecation_registry()
    registry.register(
        old_key,
        new_key=new_key,
        message=message,
        remove_in=remove_in,
        policy=policy,
    )


def undeprecate(old_key: str) -> None:
    """Remove a deprecation registration.

    :param old_key: The deprecated key pattern to remove.
    :raises KeyError: If no deprecation with that pattern exists.

    Example::

        rc.undeprecate("learning_rate")
    """
    registry = get_deprecation_registry()
    registry.unregister(old_key)


def set_deprecation_policy(policy: str) -> None:
    """Set the global deprecation policy.

    Controls how deprecated keys are handled by default:
    - "warn": Emit a warning (default)
    - "error": Raise DeprecatedKeyError
    - "ignore": Silently ignore

    Per-deprecation policies override this global setting.

    :param policy: One of "warn", "error", "ignore".

    Example::

        rc.set_deprecation_policy("warn")   # Emit warnings (default)
        rc.set_deprecation_policy("error")  # Raise errors
        rc.set_deprecation_policy("ignore") # Silent
    """
    registry = get_deprecation_registry()
    registry.set_policy(policy)  # type: ignore


def set_deprecation_handler(handler: DeprecationHandler) -> None:
    """Set a custom deprecation warning handler.

    The handler is called when a deprecated key is accessed and policy is "warn".

    :param handler: A DeprecationHandler instance.

    Example::

        from rconfig.deprecation import DeprecationHandler, DeprecationInfo

        class LoggingHandler(DeprecationHandler):
            def handle(self, info: DeprecationInfo, path: str, file: str, line: int) -> None:
                import logging
                logging.warning(f"Deprecated key '{path}' at {file}:{line}")

        rc.set_deprecation_handler(LoggingHandler())
    """
    registry = get_deprecation_registry()
    registry.set_handler(handler)


# Type for deprecation handler decorator
H = TypeVar("H", bound=Callable[..., Any])


def deprecation_handler(func: H) -> H:
    """Decorator to register a function as the deprecation handler.

    The function should accept: (info: DeprecationInfo, path: str, file: str, line: int)

    :param func: Handler function.
    :return: The same function (for use as decorator).

    Example::

        @rc.deprecation_handler
        def my_handler(info, path, file, line):
            print(f"DEPRECATED: {path} -> {info.new_key}")
    """
    registry = get_deprecation_registry()
    registry.set_handler_func(func)
    return func


# === Config Export / Serialization API ===


def _resolved_config(
    path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
) -> tuple[dict[str, Any], ConfigComposer]:
    """Internal helper: run resolution pipeline without instantiation.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :return: Tuple of (resolved config dict, composer instance).
    """
    from rconfig.interpolation import resolve_interpolations
    from rconfig.validation.required import find_required_markers

    path = ensure_path(path)

    # Handle --help/-h when CLI overrides are enabled
    cli_enabled = _effective_cli_overrides(cli_overrides)
    if cli_enabled:
        _handle_help_request(path)

    composer = ConfigComposer()
    config = composer.compose(path)

    # Collect overrides (CLI wins on conflict), validate paths and coerce values
    all_overrides = _collected_overrides(overrides, cli_enabled)
    _coerce_override_values(all_overrides, config)

    # Apply overrides
    if all_overrides:
        config = apply_overrides(config, all_overrides)

    # Check for unsatisfied _required_ values
    required_markers = find_required_markers(config)
    if required_markers:
        missing = [(m.path, m.expected_type) for m in required_markers]
        raise RequiredValueError(missing)

    # Resolve interpolations, then convert strings to declared field types.
    # Exports do not validate, so a value that cannot be converted is kept as-is.
    unresolved = config
    config = resolve_interpolations(config)
    config = _coercer.coerced(config, unresolved).config

    return config, composer


def export(
    path: StrOrPath,
    exporter: Exporter,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
) -> Any:
    """Export resolved config using a custom exporter.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param exporter: Exporter instance to use.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :return: The exported data in the exporter's target format.

    Example::

        class TomlExporter(rc.Exporter):
            def export(self, config: dict) -> str:
                import tomli_w
                return tomli_w.dumps(config)

        toml_str = rc.export(Path("config.yaml"), exporter=TomlExporter())
    """
    config, _ = _resolved_config(path, overrides=overrides, cli_overrides=cli_overrides)
    return exporter.export(config)


def to_dict(
    path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> dict[str, Any]:
    """Export resolved config as a Python dictionary.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    :return: Resolved config as a dictionary.

    Example::

        config = rc.to_dict(Path("config.yaml"))
        print(config["model"]["hidden_size"])

        # With overrides
        config = rc.to_dict(
            Path("config.yaml"),
            overrides={"model.lr": 0.01},
        )

        # Without internal markers
        clean = rc.to_dict(Path("config.yaml"), exclude_markers=True)
    """
    exporter = DictExporter(exclude_markers=exclude_markers)
    return export(path, exporter, overrides=overrides, cli_overrides=cli_overrides)


def to_yaml(
    path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> str:
    """Export resolved config as a YAML string.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    :return: Resolved config as a YAML string.

    Example::

        yaml_str = rc.to_yaml(Path("config.yaml"))
        print(yaml_str)

        # With overrides
        yaml_str = rc.to_yaml(
            Path("config.yaml"),
            overrides={"model.lr": 0.01},
        )
    """
    exporter = YamlExporter(exclude_markers=exclude_markers)
    return export(path, exporter, overrides=overrides, cli_overrides=cli_overrides)


def to_json(
    path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
    indent: int | None = 2,
) -> str:
    """Export resolved config as a JSON string.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    :param indent: Number of spaces for indentation, None for compact output.
    :return: Resolved config as a JSON string.

    Example::

        json_str = rc.to_json(Path("config.yaml"))
        print(json_str)

        # Compact output
        json_str = rc.to_json(Path("config.yaml"), indent=None)

        # With overrides
        json_str = rc.to_json(
            Path("config.yaml"),
            overrides={"model.lr": 0.01},
        )
    """
    exporter = JsonExporter(exclude_markers=exclude_markers, indent=indent)
    return export(path, exporter, overrides=overrides, cli_overrides=cli_overrides)


def to_toml(
    path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> str:
    """Export resolved config as a TOML string.

    :param path: Path to config file. Accepts str, Path, or any os.PathLike.
    :param overrides: Dictionary of config overrides using dot notation keys.
    :param cli_overrides: Whether to parse CLI overrides and --help from sys.argv.
                          None (default) uses set_cli_overrides(), which is off unless enabled.
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    :return: Resolved config as a TOML string.

    Example::

        toml_str = rc.to_toml(Path("config.yaml"))
        print(toml_str)

        # With overrides
        toml_str = rc.to_toml(
            Path("config.yaml"),
            overrides={"model.lr": 0.01},
        )
    """
    exporter = TomlExporter(exclude_markers=exclude_markers)
    return export(path, exporter, overrides=overrides, cli_overrides=cli_overrides)


@singledispatch
def to_file(
    source: StrOrPath | dict[str, Any],
    output_path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> None:
    """Export config to a single file with format auto-detection.

    All references are flattened into a single standalone file.
    Format is determined by the output file extension.

    :param source: Source config (str, Path, os.PathLike to file, or dict).
    :param output_path: Output file path (extension determines format). Accepts str, Path, or any os.PathLike.
    :param overrides: Config overrides (only used with Path input).
    :param cli_overrides: Parse CLI overrides (only used with Path input; None uses set_cli_overrides()).
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    :raises ConfigFileError: If the output file extension is not supported.

    Example::

        # Export from file to different formats
        rc.to_file(Path("config.yaml"), Path("output.json"))   # YAML -> JSON
        rc.to_file(Path("config.yaml"), Path("output.toml"))   # YAML -> TOML

        # Export from dict
        config = {"model": {"lr": 0.01}, "epochs": 10}
        rc.to_file(config, Path("output.yaml"))

        # Post-processing workflow
        config = rc.to_dict(Path("config.yaml"))
        config["extra"] = "value"
        rc.to_file(config, Path("output.json"))
    """
    raise TypeError(f"Unsupported source type: {type(source)}")


@to_file.register(Path)
def _to_file_from_path(
    source: Path,
    output_path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> None:
    config, _ = _resolved_config(
        source, overrides=overrides, cli_overrides=cli_overrides
    )
    file_exporter = SingleFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(config, ensure_path(output_path))


@to_file.register(str)
def _to_file_from_str(
    source: str,
    output_path: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> None:
    config, _ = _resolved_config(
        ensure_path(source), overrides=overrides, cli_overrides=cli_overrides
    )
    file_exporter = SingleFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(config, ensure_path(output_path))


@to_file.register(dict)
def _to_file_from_dict(
    source: dict,
    output_path: StrOrPath,
    *,
    exclude_markers: bool = False,
) -> None:
    file_exporter = SingleFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(source, ensure_path(output_path))


@singledispatch
def to_files(
    source: StrOrPath | dict[str, Any],
    config_root_file: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> None:
    """Export config preserving file structure with format auto-detection.

    When source is a path, each referenced file is exported separately with
    interpolations resolved. The _ref_ paths are preserved.

    When source is a dict, only the root file is written (no ref_graph available).

    Format is determined by file extensions:
    - Root file: format from config_root_file extension
    - Referenced files: preserve original extension from source files

    :param source: Source config (str, Path, os.PathLike to file, or dict).
    :param config_root_file: Output root file path (extension determines root format). Accepts str, Path, or any os.PathLike.
    :param overrides: Config overrides (only used with Path input).
    :param cli_overrides: Parse CLI overrides (only used with Path input; None uses set_cli_overrides()).
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    :raises ConfigFileError: If an output file extension is not supported.

    Example::

        # Export from file with preserved structure
        rc.to_files(Path("trainer.yaml"), Path("output/trainer.json"))
        # Creates:
        #   output/trainer.json (root file in JSON)
        #   output/models/resnet.yaml (preserves original YAML format)

        # Export from dict (root file only)
        config = {"model": {"lr": 0.01}, "epochs": 10}
        rc.to_files(config, Path("output/config.yaml"))
    """
    raise TypeError(f"Unsupported source type: {type(source)}")


@to_files.register(Path)
def _to_files_from_path(
    source: Path,
    config_root_file: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> None:
    config, composer = _resolved_config(
        source, overrides=overrides, cli_overrides=cli_overrides
    )
    ref_graph = composer.ref_graph()
    file_exporter = MultiFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(
        config,
        ensure_path(config_root_file),
        source_path=source,
        ref_graph=ref_graph,
    )


@to_files.register(str)
def _to_files_from_str(
    source: str,
    config_root_file: StrOrPath,
    *,
    overrides: dict[str, Any] | None = None,
    cli_overrides: bool | None = None,
    exclude_markers: bool = False,
) -> None:
    source_path = ensure_path(source)
    config, composer = _resolved_config(
        source_path, overrides=overrides, cli_overrides=cli_overrides
    )
    ref_graph = composer.ref_graph()
    file_exporter = MultiFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(
        config,
        ensure_path(config_root_file),
        source_path=source_path,
        ref_graph=ref_graph,
    )


@to_files.register(dict)
def _to_files_from_dict(
    source: dict,
    config_root_file: StrOrPath,
    *,
    exclude_markers: bool = False,
) -> None:
    file_exporter = MultiFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(
        source,
        ensure_path(config_root_file),
        source_path=None,
        ref_graph=None,
    )


@to_file.register(MultirunResult)
def _to_file_from_multirun_result(
    source: MultirunResult[Any],
    output_path: StrOrPath,
    *,
    exclude_markers: bool = False,
) -> None:
    """Export a MultirunResult config to a single file.

    :param source: MultirunResult from instantiate_multirun iteration.
    :param output_path: Output file path (extension determines format). Accepts str, Path, or any os.PathLike.
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    """
    config = dict(source.config)  # Convert from MappingProxyType
    file_exporter = SingleFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(config, ensure_path(output_path))


@to_files.register(MultirunResult)
def _to_files_from_multirun_result(
    source: MultirunResult[Any],
    config_root_file: StrOrPath,
    *,
    exclude_markers: bool = False,
) -> None:
    """Export a MultirunResult config preserving structure.

    Note: Since MultirunResult doesn't have ref_graph, this exports as single file.

    :param source: MultirunResult from instantiate_multirun iteration.
    :param config_root_file: Output root file path. Accepts str, Path, or any os.PathLike.
    :param exclude_markers: If True, remove internal markers (_target_, etc.).
    """
    config = dict(source.config)  # Convert from MappingProxyType
    file_exporter = MultiFileExporter(exclude_markers=exclude_markers)
    file_exporter.export_to_file(
        config,
        ensure_path(config_root_file),
        source_path=None,
        ref_graph=None,
    )


# === Format Preset API ===


def register_provenance_preset(
    name: str,
    factory: Callable[[], ProvenanceFormatContext],
    description: str = "",
) -> None:
    """Register a custom provenance format preset.

    :param name: Unique name for the preset.
    :param factory: Callable that returns a ProvenanceFormatContext.
    :param description: Human-readable description.
    :raises ValueError: If name conflicts with a built-in preset.

    Example::

        import rconfig as rc

        rc.register_provenance_preset(
            "my_preset",
            lambda: rc.ProvenanceFormatContext(show_paths=True, show_values=True),
            "My custom preset",
        )
    """
    get_provenance_registry().register_preset(name, factory, description)


def unregister_provenance_preset(name: str) -> None:
    """Unregister a custom provenance format preset.

    :param name: Name of the preset to unregister.
    :raises KeyError: If preset is not registered.
    :raises ValueError: If trying to unregister a built-in preset.
    """
    get_provenance_registry().unregister_preset(name)


def known_provenance_presets() -> MappingProxyType[str, ProvenancePresetEntry]:
    """Get all registered provenance presets.

    :return: Read-only mapping of preset names to entries.

    Example::

        for name, entry in rc.known_provenance_presets().items():
            print(f"{name}: {entry.description}")
    """
    return get_provenance_registry().known_presets


def provenance_preset(
    name: str,
    description: str = "",
) -> Callable[[Callable[[], ProvenanceFormatContext]], Callable[[], ProvenanceFormatContext]]:
    """Decorator to register a function as a provenance preset.

    :param name: Unique name for the preset.
    :param description: Human-readable description.
    :return: Decorator function.

    Example::

        import rconfig as rc

        @rc.provenance_preset("debug", "Full debug output")
        def debug_preset() -> rc.ProvenanceFormatContext:
            return rc.ProvenanceFormatContext(
                show_paths=True,
                show_values=True,
                show_chain=True,
                show_types=True,
            )

        # Use it
        print(rc.format(prov).preset("debug"))
    """
    def decorator(
        factory: Callable[[], ProvenanceFormatContext],
    ) -> Callable[[], ProvenanceFormatContext]:
        get_provenance_registry().register_preset(name, factory, description)
        return factory
    return decorator


def register_diff_preset(
    name: str,
    factory: Callable[[], DiffFormatContext],
    description: str = "",
) -> None:
    """Register a custom diff format preset.

    :param name: Unique name for the preset.
    :param factory: Callable that returns a DiffFormatContext.
    :param description: Human-readable description.
    :raises ValueError: If name conflicts with a built-in preset.
    """
    get_diff_registry().register_preset(name, factory, description)


def unregister_diff_preset(name: str) -> None:
    """Unregister a custom diff format preset.

    :param name: Name of the preset to unregister.
    :raises KeyError: If preset is not registered.
    :raises ValueError: If trying to unregister a built-in preset.
    """
    get_diff_registry().unregister_preset(name)


def known_diff_presets() -> MappingProxyType[str, DiffPresetEntry]:
    """Get all registered diff presets.

    :return: Read-only mapping of preset names to entries.
    """
    return get_diff_registry().known_presets


def diff_preset(
    name: str,
    description: str = "",
) -> Callable[[Callable[[], DiffFormatContext]], Callable[[], DiffFormatContext]]:
    """Decorator to register a function as a diff preset.

    :param name: Unique name for the preset.
    :param description: Human-readable description.
    :return: Decorator function.

    Example::

        import rconfig as rc

        @rc.diff_preset("added_only", "Show only added entries")
        def added_only_preset() -> rc.DiffFormatContext:
            return rc.DiffFormatContext(
                show_added=True,
                show_removed=False,
                show_changed=False,
            )
    """
    def decorator(
        factory: Callable[[], DiffFormatContext],
    ) -> Callable[[], DiffFormatContext]:
        get_diff_registry().register_preset(name, factory, description)
        return factory
    return decorator


# === Format Layout API ===


def register_provenance_layout(
    name: str,
    factory: Callable[[], ProvenanceLayout],
    description: str = "",
) -> None:
    """Register a custom provenance format layout.

    :param name: Unique name for the layout.
    :param factory: Callable that returns a ProvenanceLayout instance.
    :param description: Human-readable description.
    :raises ValueError: If name conflicts with a built-in layout.

    Example::

        import rconfig as rc
        from rconfig.provenance.formatting import ProvenanceLayout, ProvenanceDisplayModel

        class TableLayout(ProvenanceLayout):
            def render(self, model: ProvenanceDisplayModel) -> str:
                # Custom rendering logic
                ...

        rc.register_provenance_layout(
            "table",
            lambda: TableLayout(),
            "Custom table format",
        )
    """
    get_provenance_registry().register_layout(name, factory, description)


def unregister_provenance_layout(name: str) -> None:
    """Unregister a custom provenance format layout.

    :param name: Name of the layout to unregister.
    :raises KeyError: If layout is not registered.
    :raises ValueError: If trying to unregister a built-in layout.
    """
    get_provenance_registry().unregister_layout(name)


def known_provenance_layouts() -> MappingProxyType[str, ProvenanceLayoutEntry]:
    """Get all registered provenance layouts.

    :return: Read-only mapping of layout names to entries.

    Example::

        for name, entry in rc.known_provenance_layouts().items():
            builtin = "[builtin]" if entry.builtin else "[custom]"
            print(f"{name} {builtin}: {entry.description}")
    """
    return get_provenance_registry().known_layouts


def provenance_layout(
    name: str,
    description: str = "",
) -> Callable[[Callable[[], ProvenanceLayout]], Callable[[], ProvenanceLayout]]:
    """Decorator to register a function as a provenance layout.

    :param name: Unique name for the layout.
    :param description: Human-readable description.
    :return: Decorator function.

    Example::

        import rconfig as rc
        from rconfig.provenance.formatting import ProvenanceLayout, ProvenanceDisplayModel

        @rc.provenance_layout("custom", "Custom output format")
        def custom_layout() -> ProvenanceLayout:
            class CustomLayout(ProvenanceLayout):
                def render(self, model: ProvenanceDisplayModel) -> str:
                    ...
            return CustomLayout()

        # Use it
        print(prov.format().layout("custom"))
    """
    def decorator(
        factory: Callable[[], ProvenanceLayout],
    ) -> Callable[[], ProvenanceLayout]:
        get_provenance_registry().register_layout(name, factory, description)
        return factory
    return decorator


def register_diff_layout(
    name: str,
    factory: Callable[[], DiffLayout],
    description: str = "",
) -> None:
    """Register a custom diff format layout.

    :param name: Unique name for the layout.
    :param factory: Callable that returns a DiffLayout instance.
    :param description: Human-readable description.
    :raises ValueError: If name conflicts with a built-in layout.
    """
    get_diff_registry().register_layout(name, factory, description)


def unregister_diff_layout(name: str) -> None:
    """Unregister a custom diff format layout.

    :param name: Name of the layout to unregister.
    :raises KeyError: If layout is not registered.
    :raises ValueError: If trying to unregister a built-in layout.
    """
    get_diff_registry().unregister_layout(name)


def known_diff_layouts() -> MappingProxyType[str, DiffLayoutEntry]:
    """Get all registered diff layouts.

    :return: Read-only mapping of layout names to entries.
    """
    return get_diff_registry().known_layouts


def diff_layout(
    name: str,
    description: str = "",
) -> Callable[[Callable[[], DiffLayout]], Callable[[], DiffLayout]]:
    """Decorator to register a function as a diff layout.

    :param name: Unique name for the layout.
    :param description: Human-readable description.
    :return: Decorator function.

    Example::

        import rconfig as rc
        from rconfig.diff.formatting import DiffLayout, DiffDisplayModel

        @rc.diff_layout("jsonlines", "JSON Lines format")
        def jsonlines_layout() -> DiffLayout:
            class JsonLinesLayout(DiffLayout):
                def render(self, model: DiffDisplayModel) -> str:
                    ...
            return JsonLinesLayout()
    """
    def decorator(
        factory: Callable[[], DiffLayout],
    ) -> Callable[[], DiffLayout]:
        get_diff_registry().register_layout(name, factory, description)
        return factory
    return decorator


# Public API - Minimal root exports
# For classes like TargetRegistry, ConfigValidator, etc., import from submodules:
#   from rconfig.target import TargetRegistry
#   from rconfig.validation import ConfigValidator
#   from rconfig.composition import ConfigComposer, Provenance
#   from rconfig.override import Override
__all__ = [
    # Type aliases
    "StrOrPath",
    # Module-level API functions (primary interface)
    "register",
    "unregister",
    "validate",
    "instantiate",
    "known_targets",
    "get_provenance",
    "set_cache_size",
    "clear_cache",
    # Multirun API
    "instantiate_multirun",
    "MultirunResult",
    "MultirunIterator",
    "MultirunError",
    "InvalidSweepValueError",
    "NoRunConfigurationError",
    "MULTIRUN_HELP",
    # Resolver API
    "register_resolver",
    "unregister_resolver",
    "resolver",
    # Diff API
    "diff",
    "format",
    "ConfigDiff",
    "DiffEntry",
    "DiffEntryType",
    "DiffBuilder",
    "DiffFormat",
    "DiffFormatContext",
    "DiffLayout",
    "DiffFlatLayout",
    "DiffTreeLayout",
    "DiffMarkdownLayout",
    # Provenance Format Context
    "ProvenanceFormatContext",
    # Format Preset API (provenance)
    "register_provenance_preset",
    "unregister_provenance_preset",
    "known_provenance_presets",
    "provenance_preset",
    "ProvenancePresetEntry",
    "ProvenanceRegistry",
    "get_provenance_registry",
    # Format Preset API (diff)
    "register_diff_preset",
    "unregister_diff_preset",
    "known_diff_presets",
    "diff_preset",
    "DiffPresetEntry",
    "DiffRegistry",
    "get_diff_registry",
    # Format Layout API (provenance)
    "register_provenance_layout",
    "unregister_provenance_layout",
    "known_provenance_layouts",
    "provenance_layout",
    "ProvenanceLayoutEntry",
    # Format Layout API (diff)
    "register_diff_layout",
    "unregister_diff_layout",
    "known_diff_layouts",
    "diff_layout",
    "DiffLayoutEntry",
    # Lazy instantiation utilities
    "is_lazy_proxy",
    "force_initialize",
    # CLI override policy API
    "set_cli_overrides",
    "cli_overrides_enabled",
    # Help integration API
    "set_help_integration",
    "current_help_integration",
    "help_integration",
    "HelpIntegration",
    "FlatHelpIntegration",
    "GroupedHelpIntegration",
    "ArgparseHelpIntegration",
    # Deprecation API
    "deprecate",
    "undeprecate",
    "set_deprecation_policy",
    "set_deprecation_handler",
    "deprecation_handler",
    "DeprecationInfo",
    "DeprecationHandler",
    "DeprecatedKeyError",
    "RconfigDeprecationWarning",
    # Export API (string output)
    "export",
    "to_dict",
    "to_yaml",
    "to_json",
    "to_toml",
    # Export API (file output with format auto-detection)
    "to_file",
    "to_files",
    # Export classes (for custom exporters)
    "Exporter",
    "DictExporter",
    "YamlExporter",
    "JsonExporter",
    "TomlExporter",
    "FileExporter",
    "SingleFileExporter",
    "MultiFileExporter",
    # Exporter registry
    "register_exporter",
    "unregister_exporter",
    "get_exporter",
    "supported_exporter_extensions",
    # Loader classes (for custom loaders)
    "ConfigFileLoader",
    "YamlConfigLoader",
    "JsonConfigLoader",
    "TomlConfigLoader",
    # Loader registry
    "register_loader",
    "unregister_loader",
    "get_loader",
    "supported_loader_extensions",
    # Exceptions (available at root for convenience)
    "AmbiguousRefError",
    "AmbiguousTargetError",
    "CircularInstanceError",
    "CircularRefError",
    "CompositionError",
    "ConfigError",
    "ConfigFileError",
    "InstanceResolutionError",
    "InstantiationError",
    "InvalidInnerPathError",
    "InvalidOverridePathError",
    "InvalidOverrideSyntaxError",
    "MergeError",
    "MissingFieldError",
    "OverrideError",
    "RefAtRootError",
    "RefInstanceConflictError",
    "RefResolutionError",
    "ResolverError",
    "ResolverExecutionError",
    "RequiredValueError",
    "TargetNotFoundError",
    "TargetTypeMismatchError",
    "TypeInferenceError",
    "TypeMismatchError",
    "ValueCoercionError",
    "UnknownResolverError",
    "ValidationError",
]
