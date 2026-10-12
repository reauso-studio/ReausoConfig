"""Interpolation module for ReausoConfig.

This module provides expression parsing, evaluation, and resolution for
config value interpolation using the ${...} syntax.

Features:
- Config path references: ${/model.lr}, ${./local}, ${model.lr}
- Environment variables: ${env:PATH}, ${env:HOME ?: "/default"}
- Expressions: ${/a * 2 + /b}, ${/epochs > 100 and /lr < 0.01}
- List operations: ${/items[0]}, ${/list + /other}, ${/items | filter(x > 0)}

Example::

    config = {
        "defaults": {"lr": 0.01},
        "model": {
            "learning_rate": "${/defaults.lr}",
            "scaled_lr": "${/defaults.lr * 10}",
        },
    }

    resolved = resolve_interpolations(config)
    # resolved["model"]["learning_rate"] == 0.01
    # resolved["model"]["scaled_lr"] == 0.1
"""

from rconfig.interpolation.evaluator import (
    EvalResult,
    ExpressionEvaluator,
    InterpolationSource,
)
from rconfig.interpolation.parser import (
    InterpolationMatch,
    InterpolationParser,
    find_interpolations,
    has_interpolation,
    is_standalone_interpolation,
)
from rconfig.interpolation.registry import (
    ResolverReference,
    ResolverRegistry,
)
from rconfig.interpolation.resolver import (
    InterpolationResolver,
    resolve_interpolations,
)

__all__ = [
    # Main API
    "resolve_interpolations",
    "InterpolationResolver",
    # Parser
    "InterpolationParser",
    "InterpolationMatch",
    "find_interpolations",
    "has_interpolation",
    "is_standalone_interpolation",
    # Evaluator
    "ExpressionEvaluator",
    "EvalResult",
    "InterpolationSource",
    # Registry
    "ResolverRegistry",
    "ResolverReference",
]
