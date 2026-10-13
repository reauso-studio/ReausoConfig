"""Expression evaluator using Lark Transformer.

This module provides the ExpressionEvaluator class that transforms
a parsed Lark AST into actual Python values, resolving config references,
environment variables, and applying operators.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

from lark import Token, Transformer, v_args

if TYPE_CHECKING:
    from rconfig.provenance import Provenance


@dataclass
class InterpolationSource:
    """Source of data used in an interpolation expression.

    Used for provenance tracking to show where interpolated values came from.

    :param kind: Type of source ("config", "env", "literal", "expression", "resolver").
    :param expression: The expression string that was evaluated.
    :param value: The resolved value.
    :param path: Config path if kind="config".
    :param file: Source file where the referenced value is defined.
    :param line: Line number of the referenced value.
    :param env_var: Environment variable name if kind="env".
    :param env_default: Default value used if env var was not set.
    :param sources: List of child sources for compound expressions.
    :param operator: Operator used for compound expressions (e.g., "*", "+").
    :param resolver_path: Registered resolver path if kind="resolver" (e.g., "uuid", "db:lookup").
    :param resolver_func: Function name of the resolver (e.g., "gen_uuid").
    :param resolver_module: Module where the resolver is defined (e.g., "myapp.resolvers").
    """

    kind: Literal["config", "env", "literal", "expression", "resolver"]
    expression: str
    value: Any
    # For config references
    path: str | None = None
    file: str | None = None
    line: int | None = None
    # For env vars
    env_var: str | None = None
    env_default: Any | None = None
    # For compound expressions
    sources: list[InterpolationSource] = field(default_factory=list)
    operator: str | None = None
    # For resolvers
    resolver_path: str | None = None
    resolver_func: str | None = None
    resolver_module: str | None = None


@dataclass
class EvalResult:
    """Result of evaluating an expression, with provenance info.

    :param value: The evaluated value.
    :param source: Provenance tracking information.
    """

    value: Any
    source: InterpolationSource


class ExpressionEvaluator(Transformer):
    """Lark Transformer that evaluates interpolation expressions.

    Transforms a parsed AST into actual Python values by:
    - Resolving config path references to their values
    - Resolving environment variables
    - Resolving app resolvers
    - Applying arithmetic, comparison, and boolean operators
    - Handling list operations (concat, removal, indexing, slicing, filter)
    - Handling ternary and coalesce operators

    Note: Short-circuit operators (ternary, elvis_coalesce, error_coalesce) are
    handled specially via transform() override to enable lazy child evaluation.

    :param config: The composed config dictionary to resolve paths against.
    :param provenance: Optional Provenance object to look up source locations.
    :param env_getter: Optional function to get env vars (for testing).
    :param resolver: Optional InterpolationResolver for circular detection.
    :param registry: Optional ResolverRegistry for app resolvers.
    """

    # Rules that require lazy evaluation (children should not be auto-transformed)
    _LAZY_RULES = frozenset({"ternary", "elvis_coalesce", "error_coalesce"})

    def __init__(
        self,
        config: dict[str, Any],
        provenance: Provenance | None = None,
        env_getter: Callable[[str], str | None] | None = None,
        resolver: Any | None = None,  # InterpolationResolver, avoid circular import
        registry: Any | None = None,  # ResolverRegistry, avoid circular import
    ) -> None:
        super().__init__()
        self._config = config
        self._provenance = provenance
        self._env_getter = env_getter or os.environ.get
        self._resolver = resolver
        self._registry = registry

    def _transform_tree(self, tree: Any) -> EvalResult:
        """Override _transform_tree to handle lazy-evaluated rules specially.

        For rules in _LAZY_RULES, we call the handler directly without
        transforming children first, enabling short-circuit evaluation.

        This is called for every tree node during transformation, ensuring
        lazy rules are handled correctly at any level of nesting.
        """
        if tree.data in self._LAZY_RULES:
            # Handle lazy rules directly without auto-transforming children
            handler = getattr(self, tree.data)
            return handler(tree)

        # Default transformation for other rules
        return super()._transform_tree(tree)

    def _make_literal(self, value: Any, expr: str) -> EvalResult:
        """Create an EvalResult for a literal value."""
        return EvalResult(
            value=value,
            source=InterpolationSource(
                kind="literal",
                expression=expr,
                value=value,
            ),
        )

    def _make_binary_op(
        self, op: str, left: EvalResult, right: EvalResult, result: Any
    ) -> EvalResult:
        """Create an EvalResult for a binary operation."""
        expr = f"{left.source.expression} {op} {right.source.expression}"
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator=op,
                sources=[left.source, right.source],
            ),
        )

    def _make_unary_op(self, op: str, operand: EvalResult, result: Any) -> EvalResult:
        """Create an EvalResult for a unary operation."""
        expr = f"{op}{operand.source.expression}"
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator=op,
                sources=[operand.source],
            ),
        )

    # === Literals ===

    @v_args(inline=True)
    def number(self, token: Token) -> EvalResult:
        """Parse a number literal."""
        s = str(token)
        value = float(s) if "." in s or "e" in s.lower() else int(s)
        return self._make_literal(value, s)

    @v_args(inline=True)
    def string(self, token: Token) -> EvalResult:
        """Parse a string literal (remove quotes)."""
        s = str(token)
        # Remove surrounding quotes and handle escape sequences
        value = s[1:-1].encode().decode("unicode_escape")
        return self._make_literal(value, s)

    def true(self, _: list) -> EvalResult:
        """Parse 'true' literal."""
        return self._make_literal(True, "true")

    def false(self, _: list) -> EvalResult:
        """Parse 'false' literal."""
        return self._make_literal(False, "false")

    def null(self, _: list) -> EvalResult:
        """Parse 'null' literal."""
        return self._make_literal(None, "null")

    def list(self, items: list[EvalResult]) -> EvalResult:
        """Parse a list literal."""
        values = [item.value for item in items]
        sources = [item.source for item in items]
        expr = "[" + ", ".join(s.expression for s in sources) + "]"
        return EvalResult(
            value=values,
            source=InterpolationSource(
                kind="literal",
                expression=expr,
                value=values,
                sources=sources,
            ),
        )

    # === Arithmetic Operators ===

    @v_args(inline=True)
    def add(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle + operator (addition, list concatenation, or string building).

        A string on either side builds a string, so `"epoch " + 10` is
        `"epoch 10"` -- that is the point of the operator. But only scalars are
        stringified. Mixing a string with a list or a dict used to produce that
        container's repr, so `"a" + ["b"]` silently became the string
        `"a['b']"`, which no config author has ever meant. It raises now.
        """
        from rconfig.errors import InterpolationResolutionError

        lv, rv = left.value, right.value
        if isinstance(lv, list) and isinstance(rv, list):
            result = lv + rv
        elif isinstance(lv, str) or isinstance(rv, str):
            container, other = (
                (lv, rv) if isinstance(lv, (list, dict)) else (rv, lv)
            )
            if isinstance(container, (list, dict)):
                raise InterpolationResolutionError(
                    f"{left.source.expression} + {right.source.expression}",
                    f"cannot add {type(other).__name__} and "
                    f"{type(container).__name__}",
                    hint=(
                        "A string plus a list or dict would stringify the "
                        "container, e.g. 'a' + ['b'] -> \"a['b']\". Concatenate "
                        "two lists, or build the string from scalars."
                    ),
                )
            result = str(lv) + str(rv)
        else:
            result = lv + rv
        return self._make_binary_op("+", left, right, result)

    @v_args(inline=True)
    def sub(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle - operator (subtraction or list removal by value)."""
        lv, rv = left.value, right.value
        if isinstance(lv, list):
            # Remove elements from list by value
            if isinstance(rv, list):
                result = [x for x in lv if x not in rv]
            else:
                result = [x for x in lv if x != rv]
        else:
            result = lv - rv
        return self._make_binary_op("-", left, right, result)

    @v_args(inline=True)
    def mul(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle * operator."""
        result = left.value * right.value
        return self._make_binary_op("*", left, right, result)

    @v_args(inline=True)
    def div(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle / operator (true division)."""
        result = left.value / right.value
        return self._make_binary_op("/", left, right, result)

    @v_args(inline=True)
    def floordiv(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle // operator (floor division)."""
        result = left.value // right.value
        return self._make_binary_op("//", left, right, result)

    @v_args(inline=True)
    def mod(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle % operator (modulo)."""
        result = left.value % right.value
        return self._make_binary_op("%", left, right, result)

    @v_args(inline=True)
    def pow(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle ** operator (power)."""
        result = left.value ** right.value
        return self._make_binary_op("**", left, right, result)

    @v_args(inline=True)
    def neg(self, operand: EvalResult) -> EvalResult:
        """Handle unary - operator."""
        result = -operand.value
        return self._make_unary_op("-", operand, result)

    @v_args(inline=True)
    def pos(self, operand: EvalResult) -> EvalResult:
        """Handle unary + operator."""
        result = +operand.value
        return self._make_unary_op("+", operand, result)

    # === Comparison Operators ===

    @v_args(inline=True)
    def eq(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle == operator."""
        result = left.value == right.value
        return self._make_binary_op("==", left, right, result)

    @v_args(inline=True)
    def ne(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle != operator."""
        result = left.value != right.value
        return self._make_binary_op("!=", left, right, result)

    @v_args(inline=True)
    def lt(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle < operator."""
        result = left.value < right.value
        return self._make_binary_op("<", left, right, result)

    @v_args(inline=True)
    def gt(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle > operator."""
        result = left.value > right.value
        return self._make_binary_op(">", left, right, result)

    @v_args(inline=True)
    def le(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle <= operator."""
        result = left.value <= right.value
        return self._make_binary_op("<=", left, right, result)

    @v_args(inline=True)
    def ge(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle >= operator."""
        result = left.value >= right.value
        return self._make_binary_op(">=", left, right, result)

    @v_args(inline=True)
    def contains(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle 'in' operator."""
        result = left.value in right.value
        return self._make_binary_op("in", left, right, result)

    @v_args(inline=True)
    def not_contains(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle 'not in' operator."""
        result = left.value not in right.value
        return self._make_binary_op("not in", left, right, result)

    # === Boolean Operators ===

    @v_args(inline=True)
    def and_op(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle 'and' operator."""
        result = left.value and right.value
        return self._make_binary_op("and", left, right, result)

    @v_args(inline=True)
    def or_op(self, left: EvalResult, right: EvalResult) -> EvalResult:
        """Handle 'or' operator."""
        result = left.value or right.value
        return self._make_binary_op("or", left, right, result)

    @v_args(inline=True)
    def not_op(self, operand: EvalResult) -> EvalResult:
        """Handle 'not' operator."""
        result = not operand.value
        return self._make_unary_op("not ", operand, result)

    # === Ternary Operator ===

    @v_args(tree=True)
    def ternary(self, tree: Any) -> EvalResult:
        """Handle ternary operator: condition ? if_true : if_false.

        Short-circuits: only evaluates the branch that is taken.

        Uses v_args(tree=True) to receive the raw tree and control child evaluation
        for short-circuit behavior.
        """
        condition_tree, if_true_tree, if_false_tree = tree.children

        # Evaluate condition first
        cond_result = self.transform(condition_tree)

        # Short-circuit: only evaluate the branch we need
        if cond_result.value:
            result = self.transform(if_true_tree)
        else:
            result = self.transform(if_false_tree)

        # Build expression string
        expr = f"{cond_result.source.expression} ? {result.source.expression} : ..."
        return EvalResult(
            value=result.value,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result.value,
                operator="?:",
                sources=[cond_result.source, result.source],
            ),
        )

    # === Coalesce Operators ===

    def _is_soft_error(self, exc: Exception) -> bool:
        """Check if an exception is a soft error for elvis_coalesce.

        Soft errors (caught by ?:): UnknownResolverError, EnvironmentVariableError
        Hard errors (caught by ?? only): ResolverExecutionError, other exceptions

        Lark wraps exceptions in VisitError, so we need to check orig_exc.
        """
        from lark.exceptions import VisitError

        from rconfig.errors import EnvironmentVariableError, UnknownResolverError

        # Check if it's a direct soft error
        if isinstance(exc, (UnknownResolverError, EnvironmentVariableError)):
            return True

        # Check if it's wrapped in a VisitError
        if isinstance(exc, VisitError) and hasattr(exc, "orig_exc"):
            return isinstance(exc.orig_exc, (UnknownResolverError, EnvironmentVariableError))

        return False

    @v_args(tree=True)
    def elvis_coalesce(self, tree: Any) -> EvalResult:
        """Handle ?: operator (Elvis/soft coalesce).

        Catches: None value, UnknownResolverError, EnvironmentVariableError
        Does NOT catch: ResolverExecutionError or other exceptions

        Uses v_args(tree=True) to receive the raw tree and control child evaluation
        for short-circuit behavior.
        """
        left_tree, right_tree = tree.children

        try:
            left_result = self.transform(left_tree)
            if left_result.value is not None:
                return left_result
        except Exception as e:
            if not self._is_soft_error(e):
                raise  # Re-raise hard errors
            # Fall through to right side for soft errors

        # Left was None or raised soft error, evaluate right side
        right_result = self.transform(right_tree)

        expr = f"... ?: {right_result.source.expression}"
        return EvalResult(
            value=right_result.value,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=right_result.value,
                operator="?:",
                sources=[right_result.source],
            ),
        )

    @v_args(tree=True)
    def error_coalesce(self, tree: Any) -> EvalResult:
        """Handle ?? operator (error/hard coalesce).

        Catches: None value, ANY exception (including ResolverExecutionError)

        Uses v_args(tree=True) to receive the raw tree and control child evaluation
        for short-circuit behavior.
        """
        left_tree, right_tree = tree.children

        try:
            left_result = self.transform(left_tree)
            if left_result.value is not None:
                return left_result
        except Exception:
            pass  # Fall through to right side

        # Left was None or raised any error, evaluate right side
        right_result = self.transform(right_tree)

        expr = f"... ?? {right_result.source.expression}"
        return EvalResult(
            value=right_result.value,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=right_result.value,
                operator="??",
                sources=[right_result.source],
            ),
        )

    # === List Operations ===

    @v_args(inline=True)
    def index(self, target: EvalResult, idx: EvalResult) -> EvalResult:
        """Handle indexing: list[0], list[-1]."""
        result = target.value[idx.value]
        expr = f"{target.source.expression}[{idx.source.expression}]"
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator="[]",
                sources=[target.source, idx.source],
            ),
        )

    @v_args(inline=True)
    def slice_both(
        self, start_expr: EvalResult, stop_expr: EvalResult
    ) -> tuple[int | None, int | None]:
        """Parse slice with both start and stop: [1:3]."""
        return (start_expr.value, stop_expr.value)

    @v_args(inline=True)
    def slice_to_end(self, start_expr: EvalResult) -> tuple[int | None, int | None]:
        """Parse slice with start only: [1:]."""
        return (start_expr.value, None)

    @v_args(inline=True)
    def slice_from_start(self, stop_expr: EvalResult) -> tuple[int | None, int | None]:
        """Parse slice with stop only: [:3]."""
        return (None, stop_expr.value)

    @v_args(inline=True)
    def slice_op(
        self, target: EvalResult, slice_args: tuple[int | None, int | None]
    ) -> EvalResult:
        """Handle slicing: list[1:3], list[:3], list[2:]."""
        start, stop = slice_args
        result = target.value[start:stop]
        slice_str = f"{start if start is not None else ''}:{stop if stop is not None else ''}"
        expr = f"{target.source.expression}[{slice_str}]"
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator="[:]",
                sources=[target.source],
            ),
        )

    @v_args(inline=True)
    def remove_method(self, target: EvalResult, idx: EvalResult) -> EvalResult:
        """Handle .remove(index) method."""
        lst = list(target.value)  # Make a copy
        index = idx.value
        del lst[index]  # Raises IndexError if out of bounds
        result = lst
        expr = f"{target.source.expression}.remove({idx.source.expression})"
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator=".remove()",
                sources=[target.source, idx.source],
            ),
        )

    @v_args(inline=True)
    def len_func(self, target: EvalResult) -> EvalResult:
        """Handle len() function."""
        result = len(target.value)
        expr = f"len({target.source.expression})"
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator="len()",
                sources=[target.source],
            ),
        )

    def _cast(self, name: str, cast: Any, target: EvalResult) -> EvalResult:
        """Apply a named cast to a value, reporting a failure in config terms."""
        from rconfig.errors import InterpolationResolutionError

        expr = f"{name}({target.source.expression})"
        try:
            result = cast(target.value)
        except (TypeError, ValueError) as error:
            raise InterpolationResolutionError(
                expr,
                f"cannot convert {target.value!r} to {name}",
                hint=f"{error}",
            ) from error
        return EvalResult(
            value=result,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=result,
                operator=f"{name}()",
                sources=[target.source],
            ),
        )

    @v_args(inline=True)
    def int_func(self, target: EvalResult) -> EvalResult:
        """Handle int(), which is how an env value joins an arithmetic expression.

        An ${env:...} reference is a string wherever it is only part of a larger
        expression -- it is converted to the declared field type only when it is
        the whole value of a key. So `${env:PORT + 1}` builds a string and
        `${int(env:PORT) + 1}` adds.
        """
        return self._cast("int", int, target)

    @v_args(inline=True)
    def float_func(self, target: EvalResult) -> EvalResult:
        """Handle float(). See int_func for why these exist."""
        return self._cast("float", float, target)

    @v_args(inline=True)
    def filter_op(
        self, target: EvalResult, condition: tuple[str, str, EvalResult]
    ) -> EvalResult:
        """Handle filter: list | filter(x > 0).

        The condition is a tuple of (var_name, operator, value).
        """
        var_name, op, compare_value = condition
        target_list = target.value

        if not isinstance(target_list, list):
            from rconfig.errors import InterpolationResolutionError

            raise InterpolationResolutionError(
                f"{target.source.expression} | filter(...)",
                f"filter requires a list, got {type(target_list).__name__}",
                hint="Apply filter to a list value, not a scalar or dict.",
            )

        # Apply the filter directly using the parsed condition
        filtered_values = []
        for item in target_list:
            if self._apply_filter_comparison(op, item, compare_value.value):
                filtered_values.append(item)

        expr = f"{target.source.expression} | filter({var_name} {op} {compare_value.source.expression})"

        return EvalResult(
            value=filtered_values,
            source=InterpolationSource(
                kind="expression",
                expression=expr,
                value=filtered_values,
                operator="filter",
                sources=[target.source, compare_value.source],
            ),
        )

    def _apply_filter_comparison(self, op: str, item: Any, compare_value: Any) -> bool:
        """Apply a filter comparison operator."""
        if op == "==":
            return item == compare_value
        elif op == "!=":
            return item != compare_value
        elif op == "<":
            return item < compare_value
        elif op == ">":
            return item > compare_value
        elif op == "<=":
            return item <= compare_value
        elif op == ">=":
            return item >= compare_value
        return False

    # Filter condition handlers - return (var_name, operator, value)
    @v_args(inline=True)
    def filter_eq(self, var: Token, value: EvalResult) -> tuple[str, str, EvalResult]:
        """Handle filter condition: x == value."""
        return (str(var), "==", value)

    @v_args(inline=True)
    def filter_ne(self, var: Token, value: EvalResult) -> tuple[str, str, EvalResult]:
        """Handle filter condition: x != value."""
        return (str(var), "!=", value)

    @v_args(inline=True)
    def filter_lt(self, var: Token, value: EvalResult) -> tuple[str, str, EvalResult]:
        """Handle filter condition: x < value."""
        return (str(var), "<", value)

    @v_args(inline=True)
    def filter_gt(self, var: Token, value: EvalResult) -> tuple[str, str, EvalResult]:
        """Handle filter condition: x > value."""
        return (str(var), ">", value)

    @v_args(inline=True)
    def filter_le(self, var: Token, value: EvalResult) -> tuple[str, str, EvalResult]:
        """Handle filter condition: x <= value."""
        return (str(var), "<=", value)

    @v_args(inline=True)
    def filter_ge(self, var: Token, value: EvalResult) -> tuple[str, str, EvalResult]:
        """Handle filter condition: x >= value."""
        return (str(var), ">=", value)

    # === Config References ===

    def _resolve_config_path(self, path: str) -> EvalResult:
        """Resolve a config path to its value."""
        from rconfig._internal.path_utils import get_value_at_path
        from rconfig.errors import InterpolationResolutionError

        # If resolver is available, use it for circular detection and resolution
        if self._resolver is not None:
            value, source = self._resolver.get_resolved_value(path)
            if source is not None:
                return EvalResult(value=value, source=source)
            # Fallback to creating source manually if resolver didn't provide one
            return EvalResult(
                value=value,
                source=InterpolationSource(
                    kind="config",
                    expression=path,
                    value=value,
                    path=path,
                ),
            )

        # Direct lookup (no resolver available, used in tests)
        try:
            value = get_value_at_path(self._config, path)
        except (KeyError, IndexError, TypeError) as e:
            raise InterpolationResolutionError(
                path,
                f"path not found in config: {e}",
                hint="Verify the path exists in the config. Use dot notation (e.g., 'model.lr').",
            ) from e

        # Get provenance info if available
        file_path: str | None = None
        line: int | None = None
        if self._provenance:
            entry = self._provenance.get(path)
            if entry:
                file_path = entry.file
                line = entry.line

        return EvalResult(
            value=value,
            source=InterpolationSource(
                kind="config",
                expression=path,
                value=value,
                path=path,
                file=file_path,
                line=line,
            ),
        )

    @v_args(inline=True)
    def abs_config_ref(self, token: Token) -> EvalResult:
        """Handle absolute config reference: /model.lr."""
        path = str(token)[1:]  # Remove leading /
        return self._resolve_config_path(path)

    @v_args(inline=True)
    def parent_config_ref(self, token: Token) -> EvalResult:
        """Handle parent-relative config reference: ../sibling."""
        # For now, treat as simple path - resolver handles actual resolution
        path = str(token)
        return self._resolve_config_path(path)

    @v_args(inline=True)
    def rel_config_ref(self, token: Token) -> EvalResult:
        """Handle explicit relative config reference: ./local."""
        path = str(token)[2:]  # Remove leading ./
        return self._resolve_config_path(path)

    @v_args(inline=True)
    def simple_config_ref(self, token: Token) -> EvalResult:
        """Handle simple config reference: model.lr."""
        path = str(token)
        return self._resolve_config_path(path)

    # === Environment Variables ===

    @v_args(inline=True)
    def env_ref_required(self, name: Token) -> EvalResult:
        """Handle required env var: env:PATH.

        An empty value counts as unset, so ``VAR=`` in a ``.env`` file falls
        back to a coalesce default instead of producing an empty string.
        """
        from rconfig.errors import EnvironmentVariableError

        var_name = str(name)
        value = self._env_getter(var_name)
        if value is None or value == "":
            raise EnvironmentVariableError(var_name)

        return EvalResult(
            value=value,
            source=InterpolationSource(
                kind="env",
                expression=f"env:{var_name}",
                value=value,
                env_var=var_name,
            ),
        )


    # === App Resolvers ===

    def resolver_path(self, items: list[Token]) -> str:
        """Join resolver path components: ["db", "cache", "get"] -> "db:cache:get"."""
        return ":".join(str(item) for item in items)

    @v_args(inline=True)
    def app_resolver_no_args(self, path: str) -> EvalResult:
        """Handle ${app:resolver_path} or ${app:resolver_path()}.

        Resolves an app resolver with no arguments.
        """
        from rconfig.errors import UnknownResolverError

        if self._registry is None:
            raise UnknownResolverError(path, [])

        # Get resolver reference for metadata
        ref = self._registry.known_resolvers.get(path)

        # Resolve the value
        value = self._registry.resolve(path, [], {}, self._config)

        return EvalResult(
            value=value,
            source=InterpolationSource(
                kind="resolver",
                expression=f"app:{path}",
                value=value,
                resolver_path=path,
                resolver_func=ref.func.__name__ if ref else None,
                resolver_module=ref.func.__module__ if ref else None,
            ),
        )

    @v_args(inline=True)
    def app_resolver_with_args(
        self, path: str, args: list[tuple[str | None, EvalResult]]
    ) -> EvalResult:
        """Handle ${app:resolver_path(arg1, arg2, key=val)}.

        Resolves an app resolver with positional and/or keyword arguments.
        """
        from rconfig.errors import UnknownResolverError

        if self._registry is None:
            raise UnknownResolverError(path, [])

        # Get resolver reference for metadata
        ref = self._registry.known_resolvers.get(path)

        # Separate positional and keyword arguments
        positional = [a.value for key, a in args if key is None]
        keyword = {key: a.value for key, a in args if key is not None}

        # Resolve the value
        value = self._registry.resolve(path, positional, keyword, self._config)

        # Build expression string for provenance
        args_str = ", ".join(
            a.source.expression if k is None else f"{k}={a.source.expression}"
            for k, a in args
        )

        return EvalResult(
            value=value,
            source=InterpolationSource(
                kind="resolver",
                expression=f"app:{path}({args_str})",
                value=value,
                resolver_path=path,
                resolver_func=ref.func.__name__ if ref else None,
                resolver_module=ref.func.__module__ if ref else None,
                sources=[a.source for _, a in args],
            ),
        )

    def resolver_args(self, items: list) -> list[tuple[str | None, EvalResult]]:
        """Collect resolver arguments into a list."""
        return list(items)

    @v_args(inline=True)
    def resolver_pos_arg(self, expr: EvalResult) -> tuple[None, EvalResult]:
        """Handle positional resolver argument."""
        return (None, expr)

    @v_args(inline=True)
    def resolver_kw_arg(self, name: Token, expr: EvalResult) -> tuple[str, EvalResult]:
        """Handle keyword resolver argument: key=value."""
        return (str(name), expr)
