"""Type inference for partial instantiation.

This module provides utilities for inferring target types from parent's
type hints when using inner_path for partial instantiation.

Implements a composable unwrapping pipeline:
1. Layer 1 — Strip wrappers: Annotated[X, ...] -> X, Optional[X] -> X
2. Layer 2a — Container matching: list[X], tuple[A,B,C], dict[K,V]
3. Layer 2b — Union matching: Structural match against union members
4. Layer 3 — Verify/register: Ensure concrete and usable
"""

from typing import Any, get_type_hints

from rconfig._internal.path_utils import (
    navigate_path,
    parse_path_segments,
    PathNavigationError,
)
from rconfig._internal.type_utils import (
    TARGET_KEY,
    extract_class_from_hint,
    extracted_container_element_type,
    is_class_type,
    is_concrete_type,
    is_union_hint,
    register_inferred_target,
    resolved_union_candidate,
    unwrapped_hint,
)
from rconfig.target import TargetRegistry


def infer_target_from_parent(
    config: dict[str, Any],
    path: str,
    store: TargetRegistry,
) -> str | None:
    """Infer target name from parent's type hint using the composable pipeline.

    When extracting a nested path like "model.database", this function
    checks if the parent config ("model") has a `_target_` and whether
    that target's class has a concrete type hint for the field ("database").

    Supports: dict[K,V] element, tuple positional, Annotated, Optional[container],
    union structural matching, and plain class fields.

    :param config: Full config dict (before extraction).
    :param path: Dot-notation path to the section being extracted.
    :param store: TargetRegistry with registered targets.
    :return: Inferred target name, or None if cannot infer.
    """
    segments = parse_path_segments(path)

    if len(segments) < 2:
        return None  # No parent to infer from (root level)

    field_segment = segments[-1]

    # Handle index-based access (list/tuple elements)
    if isinstance(field_segment, int):
        return _infer_container_element_type(config, segments, store)

    # Try plain field inference (includes union structural matching)
    result = _infer_plain_field_type(config, segments, store)
    if result is not None:
        return result

    # Try dict element inference (parent field is dict[str, X])
    return _infer_dict_element_from_grandparent(config, segments, store)


def _class_at_path(
    config: dict[str, Any],
    segments: list[str | int],
    store: TargetRegistry,
) -> type | None:
    """Get the target class at a given path in the config.

    Navigates to the config at segments, reads its _target_,
    and returns the registered class.

    :param config: Full config dict.
    :param segments: Path segments to navigate.
    :param store: TargetRegistry with registered targets.
    :return: The target class, or None if cannot resolve.
    """
    try:
        if segments:
            target_config = navigate_path(config, segments)
        else:
            target_config = config
    except PathNavigationError:
        return None

    if not isinstance(target_config, dict):
        return None
    if TARGET_KEY not in target_config:
        return None

    target_name = target_config[TARGET_KEY]
    if target_name not in store.known_targets:
        return None

    return store.known_targets[target_name].target_class


def _infer_plain_field_type(
    config: dict[str, Any],
    segments: list[str | int],
    store: TargetRegistry,
) -> str | None:
    """Infer type for a plain field on a parent class.

    Applies the composable pipeline:
    1. Gets parent class via _target_
    2. Reads type hint for the field
    3. Unwraps Annotated/Optional wrappers
    4. If plain class: verify concrete
    5. If union: attempt structural matching

    :param config: Full config dict.
    :param segments: Full path segments (last is the field name).
    :param store: TargetRegistry with registered targets.
    :return: Inferred target name, or None.
    """
    field_name = segments[-1]
    parent_segments = segments[:-1]

    parent_class = _class_at_path(config, parent_segments, store)
    if parent_class is None:
        return None

    try:
        type_hints = get_type_hints(parent_class)
    except Exception:
        return None

    field_type = type_hints.get(field_name)
    if field_type is None:
        return None

    # Layer 1: unwrap Annotated/Optional
    unwrapped = unwrapped_hint(field_type)

    # Try plain class extraction
    class_type = extract_class_from_hint(unwrapped)
    if class_type is None and is_class_type(unwrapped):
        class_type = unwrapped

    if class_type is not None:
        is_concrete, target_name, _ = is_concrete_type(store, class_type)
        if is_concrete:
            if target_name is None:
                target_name = register_inferred_target(store, class_type)
            return target_name

    # Layer 2b: try union structural matching
    if is_union_hint(unwrapped):
        try:
            field_config = navigate_path(config, segments)
        except PathNavigationError:
            return None
        if isinstance(field_config, dict):
            matched_type = resolved_union_candidate(unwrapped, field_config, store)
            if matched_type is not None:
                is_concrete, target_name, _ = is_concrete_type(store, matched_type)
                if is_concrete:
                    if target_name is None:
                        target_name = register_inferred_target(store, matched_type)
                    return target_name

    return None


def _infer_container_element_type(
    config: dict[str, Any],
    segments: list[str | int],
    store: TargetRegistry,
) -> str | None:
    """Infer element type from a container (list, tuple, dict).

    Applies the composable pipeline to handle:
    list[X][i], tuple[A,B,C][i], Optional[list[X]][i],
    Annotated[list[X], ...][i], etc.

    :param config: Full config dict.
    :param segments: Full path segments (last is an int index).
    :param store: TargetRegistry with registered targets.
    :return: Inferred target name, or None.
    """
    # Need at least 3 segments: grandparent, container_field, index
    if len(segments) < 3:
        return None

    container_field_segment = segments[-2]
    if isinstance(container_field_segment, int):
        # Nested indices not supported (e.g., callbacks[0][1])
        return None

    container_field_name: str = container_field_segment
    grandparent_segments = segments[:-2]

    grandparent_class = _class_at_path(config, grandparent_segments, store)
    if grandparent_class is None:
        return None

    try:
        type_hints = get_type_hints(grandparent_class)
    except Exception:
        return None

    field_type = type_hints.get(container_field_name)
    if field_type is None:
        return None

    # Layer 1: unwrap Annotated/Optional
    unwrapped = unwrapped_hint(field_type)

    # Layer 2a: extract element type from container
    index_segment = segments[-1]
    element_type = extracted_container_element_type(unwrapped, index_segment)
    if element_type is None:
        return None

    # Recursively unwrap the element type
    element_type = unwrapped_hint(element_type)

    # Layer 3: verify/register
    class_type = extract_class_from_hint(element_type)
    if class_type is None and is_class_type(element_type):
        class_type = element_type

    if class_type is None:
        return None

    is_concrete, target_name, _ = is_concrete_type(store, class_type)
    if is_concrete:
        if target_name is None:
            target_name = register_inferred_target(store, class_type)
        return target_name

    return None


def _infer_dict_element_from_grandparent(
    config: dict[str, Any],
    segments: list[str | int],
    store: TargetRegistry,
) -> str | None:
    """Infer type when a string segment accesses a dict[str, X] field.

    For paths like ["parent", "models", "resnet"] where parent.models
    is typed as dict[str, Model], infers Model as the target type.

    :param config: Full config dict.
    :param segments: Full path segments (last is a string key).
    :param store: TargetRegistry with registered targets.
    :return: Inferred target name, or None.
    """
    if len(segments) < 3:
        return None

    dict_field = segments[-2]
    if isinstance(dict_field, int):
        return None

    grandparent_segments = segments[:-2]
    grandparent_class = _class_at_path(config, grandparent_segments, store)
    if grandparent_class is None:
        return None

    try:
        type_hints = get_type_hints(grandparent_class)
    except Exception:
        return None

    field_type = type_hints.get(dict_field)
    if field_type is None:
        return None

    # Layer 1: unwrap
    unwrapped = unwrapped_hint(field_type)

    # Layer 2a: extract value type from dict[K, V]
    dict_key = segments[-1]
    element_type = extracted_container_element_type(unwrapped, dict_key)
    if element_type is None:
        return None

    # Unwrap the element type too
    element_type = unwrapped_hint(element_type)

    # Layer 3: verify/register
    class_type = extract_class_from_hint(element_type)
    if class_type is None and is_class_type(element_type):
        class_type = element_type

    if class_type is None:
        return None

    is_concrete, target_name, _ = is_concrete_type(store, class_type)
    if is_concrete:
        if target_name is None:
            target_name = register_inferred_target(store, class_type)
        return target_name

    return None
