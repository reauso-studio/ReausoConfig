"""Configuration instantiation logic.

This module provides instantiation of config dictionaries into actual
Python objects using registered target classes.
"""

import inspect
from collections.abc import Mapping, MutableMapping
from types import MappingProxyType
from typing import Any, get_args, get_origin, get_type_hints

from rconfig.target import TargetRegistry
from rconfig.validation import ConfigValidator
from rconfig.errors import InstantiationError
from rconfig._internal.path_utils import build_child_path

from rconfig._internal.type_utils import (
    TARGET_KEY,
    LAZY_KEY,
    could_be_implicit_nested,
    extract_class_from_hint,
    extracted_container_element_type,
    is_concrete_type,
    is_union_hint,
    register_inferred_target,
    resolved_union_candidate,
    unwrapped_hint,
)
from rconfig.instantiation.LazyProxy import get_lazy_proxy_class


class ConfigInstantiator:
    """Instantiates Python objects from validated config dictionaries.

    Handles recursive instantiation of nested configs and validates
    configs before instantiation. Supports shared instances when
    instance_targets mapping is provided from ConfigComposer.
    """

    def __init__(self, store: TargetRegistry, validator: ConfigValidator) -> None:
        """Initialize the instantiator.

        :param store: TargetRegistry containing registered target classes.
        :param validator: ConfigValidator for validating configs before instantiation.
        """
        self._store = store
        self._validator = validator
        # Instance sharing: maps instance config paths to their target paths
        self._instance_targets: dict[str, str | None] = {}
        # Cache of instantiated objects by their config path
        self._instantiated_cache: dict[str, Any] = {}
        # Global lazy mode flag
        self._global_lazy: bool = False
        # Root config path for hooks (file path)
        self._config_path_for_hooks: str | None = None

    def instantiate(
        self,
        config: dict[str, Any],
        validate: bool = True,
        config_path: str = "",
        instance_targets: dict[str, str | None] | None = None,
        external_instances: dict[str, Any] | None = None,
        lazy: bool = False,
        config_path_for_hooks: str | None = None,
    ) -> Any:
        """Create an object from a config dictionary.

        :param config: Config dict with _target_ key.
        :param validate: Whether to validate before instantiation.
        :param config_path: Current path for error messages.
        :param instance_targets: Optional mapping from config paths to their
                                 target paths for instance sharing. When two
                                 paths share the same target, they get the
                                 same Python object instance.
        :param external_instances: Pre-instantiated objects for external refs.
                                   Used by partial instantiation to provide
                                   objects from outside the partial scope.
        :param lazy: If True, all nested configs are lazily instantiated.
                     Lazy objects delay __init__ until first attribute access.
        :param config_path_for_hooks: File path for hooks (passed to HookContext).
        :return: Instantiated object.
        :raises ValidationError: If config is invalid (when validate=True).
        :raises InstantiationError: If instantiation fails.
        """
        # Set up instance sharing for this instantiation
        if instance_targets is not None:
            self._instance_targets = instance_targets
        else:
            self._instance_targets = {}
        self._instantiated_cache = {}

        # Set up lazy mode for this instantiation
        self._global_lazy = lazy

        # Store config path for hooks
        self._config_path_for_hooks = config_path_for_hooks

        # Pre-populate cache with external instances
        if external_instances:
            self._instantiated_cache.update(external_instances)

        if validate:
            result = self._validator.validate(config, config_path)
            if not result.valid:
                # Raise the first error
                raise result.errors[0]

        target_name = config[TARGET_KEY]
        reference = self._store.known_targets[target_name]

        # Check for per-field _lazy_ marker on the root config
        should_be_lazy = self._global_lazy or config.get(LAZY_KEY, False)

        # Process arguments, instantiating nested configs
        # Filter out _lazy_ key so it's not passed to constructor
        filtered_config = {k: v for k, v in config.items() if k != LAZY_KEY}
        kwargs = self._processed_arguments(filtered_config, config_path)

        # Invoke BEFORE_INSTANTIATE hooks
        self._invoke_before_instantiate(filtered_config, config_path, target_name)

        try:
            if should_be_lazy:
                proxy_class = get_lazy_proxy_class(reference.target_class)
                instance = proxy_class(**kwargs)
            else:
                instance = reference.target_class(**kwargs)

            # Invoke AFTER_INSTANTIATE hooks
            self._invoke_after_instantiate(filtered_config, config_path, target_name, instance)

            # Cache this instance for potential sharing
            if config_path:
                self._instantiated_cache[config_path] = instance
            return instance
        except Exception as e:
            raise InstantiationError(target_name, str(e), config_path)

    def _processed_arguments(
        self,
        config: dict[str, Any],
        config_path: str,
    ) -> dict[str, Any]:
        """Return processed config arguments with nested configs instantiated.

        :param config: Config dict to process.
        :param config_path: Current path for error messages.
        :return: Dictionary of processed arguments.
        """
        kwargs: dict[str, Any] = {}

        # Get type hints for inferring nested config types
        target_name = config[TARGET_KEY]
        reference = self._store.known_targets[target_name]

        try:
            type_hints = get_type_hints(reference.target_class)
        except Exception:
            type_hints = {}

        for key, value in config.items():
            if key == TARGET_KEY:
                continue

            field_path = build_child_path(config_path, key)
            expected_type = type_hints.get(key)
            kwargs[key] = self._instantiated_value(value, field_path, expected_type)

        return kwargs

    def _instantiated_value(
        self,
        value: Any,
        config_path: str,
        expected_type: type | None = None,
    ) -> Any:
        """Return value with nested configs instantiated.

        :param value: Value to process.
        :param config_path: Current path for error messages.
        :param expected_type: Expected type from parent's type hint.
        :return: Value with nested configs instantiated.
        """
        # Check if this path is an instance reference
        if config_path in self._instance_targets:
            target_path = self._instance_targets[config_path]
            if target_path is None:
                # _instance_: null
                return None

            # Handle external instance reference (from partial instantiation)
            if target_path.startswith("__external__:"):
                # External instances should have been pre-populated in cache
                if target_path in self._instantiated_cache:
                    return self._instantiated_cache[target_path]
                # If not found, the external target couldn't be instantiated
                external_path = target_path[13:]  # Strip "__external__:" prefix
                raise InstantiationError(
                    "external",
                    f"External instance target '{external_path}' was not pre-instantiated",
                    config_path,
                )

            # Check if the target has already been instantiated
            if target_path in self._instantiated_cache:
                return self._instantiated_cache[target_path]
            # If not instantiated yet, we'll instantiate it now and it will be cached

        # Explicit nested config with _target_
        if self._is_nested_config(value):
            # Auto-register target if not registered but we have expected type
            # Only auto-register if target name matches expected class name
            target_name = value[TARGET_KEY]
            if target_name not in self._store.known_targets:
                class_type = extract_class_from_hint(expected_type)
                if (
                    class_type is not None
                    and not inspect.isabstract(class_type)
                    and target_name.lower() == class_type.__name__.lower()
                ):
                    self._store.register(target_name, class_type)
            return self._instantiate_nested(value, config_path)

        # Implicit nested config - dict without _target_ where type can be inferred
        if could_be_implicit_nested(value, expected_type):
            augmented = self._augment_with_inferred_target(value, expected_type)
            if augmented is not None:
                return self._instantiate_nested(augmented, config_path)

        if isinstance(value, list):
            list_element_type = _extracted_list_element_type(expected_type)
            return [
                self._instantiated_value(
                    item,
                    build_child_path(config_path, i),
                    _extracted_tuple_positional_type(expected_type, i) or list_element_type,
                )
                for i, item in enumerate(value)
            ]

        if isinstance(value, dict):
            dict_value_type = _extracted_dict_value_type(expected_type)
            return {
                k: self._instantiated_value(
                    v, build_child_path(config_path, k), dict_value_type
                )
                for k, v in value.items()
            }

        return value

    def _instantiate_nested(
        self,
        config: dict[str, Any],
        config_path: str,
    ) -> Any:
        """Instantiate a nested config, with caching for instance sharing.

        :param config: Config dict with _target_ key.
        :param config_path: Current path for error messages and caching.
        :return: Instantiated object.
        """
        # Determine the canonical path for caching
        # If this is an instance reference, use the target path for caching
        cache_path = config_path
        if config_path in self._instance_targets:
            target_path = self._instance_targets[config_path]
            if target_path is not None:
                cache_path = target_path

        # Check cache first
        if cache_path in self._instantiated_cache:
            return self._instantiated_cache[cache_path]

        # Check for per-field _lazy_ marker or global lazy mode
        should_be_lazy = self._global_lazy or config.get(LAZY_KEY, False)

        # Filter out _lazy_ key from config before validation and instantiation
        filtered_config = {k: v for k, v in config.items() if k != LAZY_KEY}

        # Validate before instantiation
        result = self._validator.validate(filtered_config, config_path)
        if not result.valid:
            raise result.errors[0]

        target_name = filtered_config[TARGET_KEY]
        reference = self._store.known_targets[target_name]

        # Process arguments, instantiating nested configs
        kwargs = self._processed_arguments(filtered_config, config_path)

        # Invoke BEFORE_INSTANTIATE hooks
        self._invoke_before_instantiate(filtered_config, config_path, target_name)

        try:
            if should_be_lazy:
                proxy_class = get_lazy_proxy_class(reference.target_class)
                instance = proxy_class(**kwargs)
            else:
                instance = reference.target_class(**kwargs)

            # Invoke AFTER_INSTANTIATE hooks
            self._invoke_after_instantiate(filtered_config, config_path, target_name, instance)

            # Cache this instance for potential sharing
            self._instantiated_cache[cache_path] = instance
            return instance
        except Exception as e:
            raise InstantiationError(target_name, str(e), config_path)

    def _is_nested_config(self, value: Any) -> bool:
        """Check if a value is a nested config (dict with _target_)."""
        return isinstance(value, dict) and TARGET_KEY in value

    def _augment_with_inferred_target(
        self,
        value: dict[str, Any],
        expected_type: type,
    ) -> dict[str, Any] | None:
        """Add inferred _target_ to a dict if the type is concrete.

        Handles plain class types and union types via structural matching.

        :return: Augmented config if inference succeeds, None otherwise.
        """
        class_type = extract_class_from_hint(expected_type)

        if class_type is None:
            # Try union structural matching
            unwrapped = unwrapped_hint(expected_type)
            if is_union_hint(unwrapped):
                matched = resolved_union_candidate(unwrapped, value, self._store)
                if matched is not None:
                    class_type = matched

        if class_type is None:
            return None

        is_concrete_result, inferred_target, _ = is_concrete_type(
            self._store, class_type
        )

        if is_concrete_result:
            if inferred_target is None:
                inferred_target = register_inferred_target(self._store, class_type)
            return {TARGET_KEY: inferred_target, **value}

        return None

    def _invoke_before_instantiate(
        self,
        config: dict[str, Any],
        inner_path: str,
        target_name: str,
    ) -> None:
        """Invoke BEFORE_INSTANTIATE hooks if hooks are enabled.

        :param config: The config being instantiated.
        :param inner_path: Path within config to current object.
        :param target_name: The _target_ name being instantiated.
        """
        if self._config_path_for_hooks is None:
            return

        from rconfig.hooks import HookContext, HookPhase, HookRegistry

        registry = HookRegistry()
        if not registry.known_hooks[HookPhase.BEFORE_INSTANTIATE]:
            return

        context = HookContext(
            phase=HookPhase.BEFORE_INSTANTIATE,
            config_path=self._config_path_for_hooks,
            config=MappingProxyType(config),
            inner_path=inner_path or None,
            target_name=target_name,
        )
        registry.invoke(HookPhase.BEFORE_INSTANTIATE, context)

    def _invoke_after_instantiate(
        self,
        config: dict[str, Any],
        inner_path: str,
        target_name: str,
        instance: Any,
    ) -> None:
        """Invoke AFTER_INSTANTIATE hooks if hooks are enabled.

        :param config: The config that was instantiated.
        :param inner_path: Path within config to current object.
        :param target_name: The _target_ name that was instantiated.
        :param instance: The instantiated object.
        """
        if self._config_path_for_hooks is None:
            return

        from rconfig.hooks import HookContext, HookPhase, HookRegistry

        registry = HookRegistry()
        if not registry.known_hooks[HookPhase.AFTER_INSTANTIATE]:
            return

        context = HookContext(
            phase=HookPhase.AFTER_INSTANTIATE,
            config_path=self._config_path_for_hooks,
            config=MappingProxyType(config),
            inner_path=inner_path or None,
            target_name=target_name,
            instance=instance,
        )
        registry.invoke(HookPhase.AFTER_INSTANTIATE, context)


def _extracted_list_element_type(hint: type | None) -> type | None:
    """Extract element type from list[X] or Optional[list[X]].

    :param hint: Type hint for the list field.
    :return: The element type, or None.
    """
    if hint is None:
        return None
    unwrapped = unwrapped_hint(hint)
    return extracted_container_element_type(unwrapped, 0)


def _extracted_tuple_positional_type(hint: type | None, index: int) -> type | None:
    """Extract positional type from tuple[A, B, C].

    Returns the type at position `index`, or None if not a positional tuple.

    :param hint: Type hint for the tuple field.
    :param index: The position index.
    :return: The type at position, or None.
    """
    if hint is None:
        return None
    unwrapped = unwrapped_hint(hint)
    origin = get_origin(unwrapped)
    if origin is not tuple:
        return None
    args = get_args(unwrapped)
    if not args:
        return None
    # Skip variadic tuples — they use the list element path
    if len(args) == 2 and args[1] is Ellipsis:
        return None
    if 0 <= index < len(args):
        return args[index]
    return None


def _extracted_dict_value_type(hint: type | None) -> type | None:
    """Extract value type from dict[K, V], Mapping[K, V], or Optional variants.

    :param hint: Type hint for the dict/mapping field.
    :return: The value type V, or None.
    """
    if hint is None:
        return None
    unwrapped = unwrapped_hint(hint)
    origin = get_origin(unwrapped)
    if origin not in (dict, Mapping, MutableMapping):
        return None
    args = get_args(unwrapped)
    return args[1] if len(args) >= 2 else None
