"""Conversion of string config values to their fields' declared types.

Public API:
    coerced_value: Convert one raw string to a type hint.
    ConfigCoercer: Convert every string in a config tree to its field's type hint.
    CoercionResult: Result of a ConfigCoercer pass.
"""

from rconfig.coercion.config_coercer import CoercionResult, ConfigCoercer
from rconfig.coercion.string_coercion import (
    FALSE_TOKENS,
    NONE_TOKENS,
    TRUE_TOKENS,
    coerced_value,
)

__all__ = [
    "CoercionResult",
    "ConfigCoercer",
    "FALSE_TOKENS",
    "NONE_TOKENS",
    "TRUE_TOKENS",
    "coerced_value",
]
