"""Shared type utilities for config validation and instantiation.

This module provides utilities for analyzing type hints, extracting class types,
and determining if types can be used as config targets.
"""

import inspect
import types
from collections.abc import (
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set as AbstractSet,
)
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from rconfig.target import TargetRegistry


# Sentinel for _target_ key
TARGET_KEY = "_target_"

# Sentinel for _required_ key
REQUIRED_KEY = "_required_"

# Sentinel for _lazy_ key
LAZY_KEY = "_lazy_"

# Keys used internally by rconfig. These are consumed by the framework during
# composition and instantiation, and cannot be used as config field names.
# They are stripped during structural matching and before constructor calls.
RCONFIG_INTERNAL_KEYS = frozenset({
    "_target_", "_ref_", "_instance_", "_lazy_", "_required_", "_recursive_",
})


def _newtype_supertype(hint: Any) -> type | None:
    """Extract supertype from a NewType, or None if not a NewType.

    NewType creates a callable with a __supertype__ attribute.
    The ``not isinstance(hint, type)`` guard prevents false positives
    on regular classes that happen to define __supertype__.

    :param hint: Potential NewType hint.
    :return: The underlying type, or None if not a NewType.
    """
    supertype = getattr(hint, "__supertype__", None)
    if supertype is not None and not isinstance(hint, type):
        return supertype
    return None


def is_union_hint(hint: Any) -> bool:
    """Check if a type hint is a union, in either spelling.

    Covers ``typing.Union[X, Y]`` / ``Optional[X]`` as well as the PEP 604
    ``X | Y`` syntax, whose origin is ``types.UnionType``.

    :param hint: Type hint to check.
    :return: True if hint is a union type.
    """
    return get_origin(hint) in (Union, types.UnionType)


def is_class_type(hint: type) -> bool:
    """Check if a type hint represents a class that could be a config target.

    Excludes primitive types and built-in collection types that cannot
    be config targets.

    :param hint: Type hint to check.
    :return: True if hint is a class type that could be a config target.
    """
    origin = get_origin(hint)

    # If it has an origin, it's a generic (list[X], dict[K, V], Optional[X], etc.)
    if origin is not None:
        return False

    # Check if it's actually a class
    if not isinstance(hint, type):
        return False

    # Exclude primitive types and built-in collections
    excluded_types = (
        int,
        float,
        str,
        bool,
        bytes,
        type(None),
        list,
        dict,
        set,
        frozenset,
        tuple,
    )
    if hint in excluded_types:
        return False

    return True


def extract_class_from_hint(hint: type) -> type | None:
    """Extract the underlying class type from a type hint.

    Handles NewType, Optional[X], Union[X, None], and plain class types.
    Returns None if the hint doesn't represent a single class type.

    :param hint: Type hint to analyze.
    :return: The underlying class type, or None if not applicable.
    """
    # Handle NewType('Name', X) -> extract from X
    supertype = _newtype_supertype(hint)
    if supertype is not None:
        return extract_class_from_hint(supertype)

    origin = get_origin(hint)
    args = get_args(hint)

    # Handle Optional[X] which is Union[X, None]
    if is_union_hint(hint):
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            # It's Optional[X], check if X is a class
            inner = non_none_args[0]
            if is_class_type(inner):
                return inner
        return None

    # Plain class type
    if is_class_type(hint):
        return hint

    return None


def could_be_implicit_nested(value: Any, expected_type: type | None) -> bool:
    """Check if value could be an implicit nested config (dict without _target_).

    A dict could be an implicit nested config if:
    1. It's a dict without _target_
    2. The expected type is a class type (not list, dict, etc.) or a union type

    :param value: The value to check.
    :param expected_type: Expected type from parent's type hint.
    :return: True if value could be an implicit nested config.
    """
    if not isinstance(value, dict):
        return False
    if TARGET_KEY in value:
        return False  # Already has _target_, not implicit
    if expected_type is None:
        return False

    # Extract the actual class type from the hint (handle Optional, etc.)
    class_type = extract_class_from_hint(expected_type)
    if class_type is not None:
        return True

    # Also allow union types through for structural matching
    unwrapped = unwrapped_hint(expected_type)
    return is_union_hint(unwrapped)


def find_registered_subclasses(store: TargetRegistry, base_class: type) -> list[str]:
    """Find all registered targets that are subclasses of the given base class.

    :param store: TargetRegistry containing registered target classes.
    :param base_class: Base class to find subclasses of.
    :return: List of target names whose classes are subclasses of base_class.
    """
    subclasses: list[str] = []

    for name, reference in store.known_targets.items():
        target_class = reference.target_class
        # Check if target_class is a subclass of base_class (including exact match)
        try:
            if issubclass(target_class, base_class):
                subclasses.append(name)
        except TypeError:
            # issubclass can raise TypeError for some types
            continue

    return subclasses


def find_exact_match(store: TargetRegistry, cls: type) -> str | None:
    """Find a registered target that exactly matches the given class.

    :param store: TargetRegistry containing registered target classes.
    :param cls: Class to find exact match for.
    :return: Target name if exact match found, None otherwise.
    """
    for name, reference in store.known_targets.items():
        if reference.target_class is cls:
            return name
    return None


def is_concrete_type(
    store: TargetRegistry, cls: type
) -> tuple[bool, str | None, list[str]]:
    """Determine if a type is concrete (unambiguously instantiable).

    Pure query — does NOT mutate the registry. If the class is concrete
    but not registered, returns (True, None, []).  The caller should use
    register_inferred_target() to register it explicitly.

    A type is concrete if:
    1. It is not abstract (no @abstractmethod decorators)
    2. It has exactly one registered target matching it, OR
    3. No targets are registered for this type

    :param store: TargetRegistry containing registered target classes.
    :param cls: Class to check.
    :return: Tuple of (is_concrete, exact_target_name, all_matching_targets)
    """
    # Check if abstract
    if inspect.isabstract(cls):
        matching = find_registered_subclasses(store, cls)
        return (False, None, matching)

    # Find all registered subclasses (including exact matches)
    matching_targets = find_registered_subclasses(store, cls)

    # Check for exact match
    exact_match = find_exact_match(store, cls)

    if exact_match is not None:
        # We have an exact match. Is it the ONLY match?
        if len(matching_targets) == 1 and matching_targets[0] == exact_match:
            # Concrete: exactly one target, it's the exact match
            return (True, exact_match, matching_targets)
        else:
            # Ambiguous: there are subclasses registered too
            return (False, None, matching_targets)
    else:
        # No exact match registered
        if len(matching_targets) == 0:
            # Concrete but not registered — caller must use register_inferred_target()
            return (True, None, [])
        else:
            # Subclasses registered but not the class itself - ambiguous
            return (False, None, matching_targets)


def register_inferred_target(store: TargetRegistry, cls: type) -> str:
    """Register a concrete class as a target, inferring a suitable name.

    Uses the lowercase class name, falling back to the fully-qualified
    module path when a name collision exists.

    :param store: TargetRegistry to register in.
    :param cls: Concrete class to register.
    :return: The target name that was registered.
    :raises ValueError: If the class is abstract.
    """
    if inspect.isabstract(cls):
        raise ValueError(f"Cannot register abstract class: {cls.__name__}")

    target_name = cls.__name__.lower()
    if target_name in store:
        target_name = f"{cls.__module__}.{cls.__name__}"
    store.register(target_name, cls)
    return target_name


def unwrapped_hint(hint: type) -> type:
    """Strip Annotated, Optional, and NewType wrappers from a type hint.

    Recursively unwraps:
    - NewType('Name', X) -> X
    - Annotated[X, ...] -> X
    - Optional[X] (Union[X, None]) -> X
    - Composes: Annotated[Optional[X], ...] -> X

    Multi-option unions (Union[A, B]) pass through unchanged.

    :param hint: Type hint to unwrap.
    :return: The inner type after stripping wrappers.
    """
    # Handle NewType('Name', X)
    supertype = _newtype_supertype(hint)
    if supertype is not None:
        return unwrapped_hint(supertype)

    # Handle Annotated[X, ...]
    if get_origin(hint) is Annotated:
        return unwrapped_hint(get_args(hint)[0])

    # Handle Optional[X] (Union[X, None])
    if is_union_hint(hint):
        args = get_args(hint)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return unwrapped_hint(non_none[0])

    return hint


def extracted_container_element_type(hint: type, segment: str | int) -> type | None:
    """Extract element type from a container given an access segment.

    Matches access pattern to container type:
    - list[X] / set[X] / frozenset[X] / Sequence[X] / Set[X] + int -> X
    - tuple[A, B, C] + int(i) -> type at position i
    - tuple[X, ...] + int -> X (variadic tuple)
    - dict[K, V] / Mapping[K, V] + str -> V

    :param hint: The (unwrapped) container type hint.
    :param segment: The access segment (int for index, str for key).
    :return: The element type, or None if not a matching container.
    """
    origin = get_origin(hint)
    args = get_args(hint)

    if isinstance(segment, int):
        # Integer index: list-like or tuple
        if origin in (
            list, set, frozenset,
            Sequence, MutableSequence, AbstractSet, MutableSet,
        ):
            return args[0] if args else None
        if origin is tuple:
            if not args:
                return None
            # Variadic tuple: tuple[X, ...]
            if len(args) == 2 and args[1] is Ellipsis:
                return args[0]
            # Positional tuple: tuple[A, B, C]
            if 0 <= segment < len(args):
                return args[segment]
            return None
    else:
        # String key: dict[K, V] or Mapping[K, V]
        if origin in (dict, Mapping, MutableMapping):
            return args[1] if len(args) >= 2 else None

    return None


def resolved_union_candidate(
    hint: type,
    config_dict: dict[str, Any],
    store: TargetRegistry,
) -> type | None:
    """Structural matching for union types.

    Given a Union type and a config dict, find the single matching
    concrete class by comparing config keys against each candidate's fields.

    :param hint: A Union type hint (e.g., Encoder | Decoder).
    :param config_dict: The config dict for the field.
    :param store: TargetRegistry.
    :return: The matched type, or None if no unique match.
    """
    if not is_union_hint(hint):
        return None

    args = get_args(hint)
    candidate_types = [a for a in args if a is not type(None)]
    if len(candidate_types) < 2:
        return None  # Not a real union, just Optional

    # Strip rconfig internal keys
    user_keys = {k for k in config_dict if k not in RCONFIG_INTERNAL_KEYS}

    # Expand to concrete candidates
    concrete_candidates = _expanded_concrete_candidates(candidate_types)
    if not concrete_candidates:
        return None

    # Match each candidate
    matching = []
    for candidate in concrete_candidates:
        if _candidate_matches_config(candidate, user_keys, config_dict):
            matching.append(candidate)

    if len(matching) == 1:
        return matching[0]
    return None


def _expanded_concrete_candidates(types: list[type]) -> list[type]:
    """Expand abstract types to their concrete subclasses recursively.

    Abstract classes are never candidates themselves (they cannot be
    registered or instantiated per the registry's concrete-only constraint).
    Only already-imported subclasses are visible.

    :param types: List of types from a Union's args.
    :return: List of concrete candidate types.
    """
    concrete: list[type] = []
    for t in types:
        if not isinstance(t, type):
            continue
        if inspect.isabstract(t):
            concrete.extend(_concrete_subclasses(t))
        else:
            concrete.append(t)
    return concrete


def _concrete_subclasses(cls: type) -> list[type]:
    """Recursively find all concrete subclasses of an abstract class.

    :param cls: Abstract base class.
    :return: List of concrete subclasses (imported at call time).
    """
    result: list[type] = []
    for sub in cls.__subclasses__():
        if inspect.isabstract(sub):
            result.extend(_concrete_subclasses(sub))
        else:
            result.append(sub)
    return result


def _candidate_matches_config(
    candidate: type,
    user_keys: set[str],
    config_dict: dict[str, Any],
) -> bool:
    """Check if a candidate class structurally matches the config dict.

    Disqualifies if:
    - Config has keys not in candidate's fields (unless **kwargs)
    - Candidate has required fields missing from config
    - Config values are type-incompatible with annotations

    :param candidate: A concrete class to check.
    :param user_keys: Config keys with rconfig internals stripped.
    :param config_dict: The full config dict (for value type checking).
    :return: True if candidate matches the config structure.
    """
    try:
        type_hints = get_type_hints(candidate)
    except Exception:
        return False

    try:
        sig = inspect.signature(candidate.__init__, follow_wrapped=True)
        params = {k: v for k, v in sig.parameters.items() if k != "self"}
    except (ValueError, TypeError):
        return False

    # Check for **kwargs (VAR_KEYWORD) — accepts any keys
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )

    candidate_fields = set(type_hints.keys()) | set(params.keys())

    # Disqualify: config has keys not in candidate fields (unless **kwargs)
    if not has_var_keyword:
        unknown_keys = user_keys - candidate_fields
        if unknown_keys:
            return False

    # Disqualify: candidate has required fields missing from config
    for param_name, param in params.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is inspect.Parameter.empty:
            if param_name not in user_keys:
                return False

    # Disqualify: type-incompatible values
    for key in user_keys:
        if key not in type_hints:
            continue
        value = config_dict[key]
        expected = type_hints[key]
        if not _value_is_type_compatible(value, expected):
            return False

    return True


def _value_is_type_compatible(value: Any, expected_type: type) -> bool:
    """Check if a config value is type-compatible with the expected type.

    Best-effort check for primitive types. Dict values (potential nested
    configs) and None are always considered compatible.

    :param value: The config value to check.
    :param expected_type: The expected type from annotation.
    :return: True if compatible (or cannot determine).
    """
    if value is None:
        return True

    if isinstance(value, dict):
        return True  # Dicts could be nested configs

    if isinstance(value, list):
        origin = get_origin(expected_type)
        return origin in (
            list, tuple, set, frozenset,
            Sequence, MutableSequence, AbstractSet, MutableSet,
        ) or expected_type in (list, tuple)

    # Check union compatibility
    if is_union_hint(expected_type):
        args = get_args(expected_type)
        return any(_value_is_type_compatible(value, a) for a in args)

    if isinstance(expected_type, type):
        return isinstance(value, expected_type)

    return True  # Unknown types — don't disqualify
