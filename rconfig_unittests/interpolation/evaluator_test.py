"""Unit tests for ExpressionEvaluator.

These tests verify the evaluator in isolation with mocked dependencies,
focusing on app resolvers, ternary operator, and coalesce operators.
"""

import unittest
from unittest.mock import MagicMock, patch

from lark.exceptions import VisitError

from rconfig.interpolation.evaluator import ExpressionEvaluator, EvalResult, InterpolationSource
from rconfig.interpolation.parser import InterpolationParser
from rconfig.interpolation.registry import ResolverRegistry, ResolverReference
from rconfig.errors import (
    UnknownResolverError,
    ResolverExecutionError,
    EnvironmentVariableError,
    InterpolationResolutionError,
)


class AppResolverEvaluatorTests(unittest.TestCase):
    """Tests for app resolver evaluation in ExpressionEvaluator."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        # Use wrapped_class since ResolverRegistry is a @Singleton decorator
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)
        self.config = {"key": "value"}

    def _evaluate(self, expression: str) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config=self.config,
            registry=self.registry,
        )
        return evaluator.transform(tree)

    def test_app_resolver__NoArgs__CallsRegistryResolve(self):
        # Arrange
        self.registry.resolve.return_value = "uuid-123"
        mock_func = MagicMock()
        mock_func.__name__ = "gen_uuid"
        mock_func.__module__ = "myapp.resolvers"
        mock_ref = MagicMock()
        mock_ref.func = mock_func
        self.registry.known_resolvers = {"uuid": mock_ref}

        # Act
        result = self._evaluate("app:uuid")

        # Assert
        self.registry.resolve.assert_called_once_with("uuid", [], {}, self.config)
        self.assertEqual(result.value, "uuid-123")

    def test_app_resolver__EmptyParens__CallsRegistryResolve(self):
        # Arrange
        self.registry.resolve.return_value = "result"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate("app:uuid()")

        # Assert
        self.registry.resolve.assert_called_once_with("uuid", [], {}, self.config)
        self.assertEqual(result.value, "result")

    def test_app_resolver__PositionalArgs__PassesArgsToRegistry(self):
        # Arrange
        self.registry.resolve.return_value = "computed"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:add(1, 2)')

        # Assert
        self.registry.resolve.assert_called_once_with("add", [1, 2], {}, self.config)
        self.assertEqual(result.value, "computed")

    def test_app_resolver__KeywordArgs__PassesKwargsToRegistry(self):
        # Arrange
        self.registry.resolve.return_value = "2025-01-02"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:now(fmt="%Y-%m-%d")')

        # Assert
        self.registry.resolve.assert_called_once_with(
            "now", [], {"fmt": "%Y-%m-%d"}, self.config
        )

    def test_app_resolver__MixedArgs__PassesBothToRegistry(self):
        # Arrange
        self.registry.resolve.return_value = {"id": 42}
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:db:lookup("users", id=42)')

        # Assert
        self.registry.resolve.assert_called_once_with(
            "db:lookup", ["users"], {"id": 42}, self.config
        )

    def test_app_resolver__NestedNamespace__JoinsPathCorrectly(self):
        # Arrange
        self.registry.resolve.return_value = "cached"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:db:cache:get("key")')

        # Assert
        self.registry.resolve.assert_called_once_with(
            "db:cache:get", ["key"], {}, self.config
        )

    def test_app_resolver__ConfigRefAsArg__ResolvesConfigFirst(self):
        # Arrange
        self.config = {"base": 10}
        self.registry.resolve.return_value = 20
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate("app:scale(/base, 2)")

        # Assert
        self.registry.resolve.assert_called_once_with(
            "scale", [10, 2], {}, self.config
        )

    def test_app_resolver__ProvenanceTracking__SetsResolverKind(self):
        # Arrange
        mock_func = MagicMock()
        mock_func.__name__ = "gen_uuid"
        mock_func.__module__ = "myapp.resolvers"
        mock_ref = MagicMock()
        mock_ref.func = mock_func
        self.registry.known_resolvers = {"uuid": mock_ref}
        self.registry.resolve.return_value = "uuid-123"

        # Act
        result = self._evaluate("app:uuid")

        # Assert
        self.assertEqual(result.source.kind, "resolver")
        self.assertEqual(result.source.resolver_path, "uuid")
        self.assertEqual(result.source.resolver_func, "gen_uuid")
        self.assertEqual(result.source.resolver_module, "myapp.resolvers")

    def test_app_resolver__InExpression__CombinesWithArithmetic(self):
        # Arrange
        self.registry.resolve.return_value = 10
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate("app:get_value() + 5")

        # Assert
        self.assertEqual(result.value, 15)


class TernaryOperatorEvaluatorTests(unittest.TestCase):
    """Tests for ternary operator evaluation in ExpressionEvaluator."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()

    def _evaluate(self, expression: str, config: dict | None = None) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(config=config or {})
        return evaluator.transform(tree)

    def test_ternary__TruthyCondition__ReturnsTrueBranch(self):
        # Act
        result = self._evaluate('true ? "yes" : "no"')

        # Assert
        self.assertEqual(result.value, "yes")

    def test_ternary__FalsyCondition__ReturnsFalseBranch(self):
        # Act
        result = self._evaluate('false ? "yes" : "no"')

        # Assert
        self.assertEqual(result.value, "no")

    def test_ternary__NullCondition__ReturnsFalseBranch(self):
        # Act
        result = self._evaluate('null ? "yes" : "no"')

        # Assert
        self.assertEqual(result.value, "no")

    def test_ternary__ZeroCondition__ReturnsFalseBranch(self):
        # Act
        result = self._evaluate('0 ? "yes" : "no"')

        # Assert
        self.assertEqual(result.value, "no")

    def test_ternary__NonZeroCondition__ReturnsTrueBranch(self):
        # Act
        result = self._evaluate('42 ? "yes" : "no"')

        # Assert
        self.assertEqual(result.value, "yes")

    def test_ternary__ComparisonCondition__EvaluatesComparison(self):
        # Arrange
        config = {"count": 15}

        # Act
        result = self._evaluate('/count > 10 ? "high" : "low"', config)

        # Assert
        self.assertEqual(result.value, "high")

    def test_ternary__ConfigRefCondition__EvaluatesConfigValue(self):
        # Arrange
        config = {"debug": True}

        # Act
        result = self._evaluate('/debug ? "verbose" : "quiet"', config)

        # Assert
        self.assertEqual(result.value, "verbose")

    def test_ternary__ShortCircuit__DoesNotEvaluateFalseBranchWhenTrue(self):
        # This test verifies short-circuit behavior by using a division by zero
        # in the branch that shouldn't be evaluated
        config = {"flag": True}

        # Act - if false branch were evaluated, division by zero would occur
        result = self._evaluate('/flag ? 1 : 1/0', config)

        # Assert
        self.assertEqual(result.value, 1)

    def test_ternary__ShortCircuit__DoesNotEvaluateTrueBranchWhenFalse(self):
        # This test verifies short-circuit behavior
        config = {"flag": False}

        # Act - if true branch were evaluated, division by zero would occur
        result = self._evaluate('/flag ? 1/0 : 2', config)

        # Assert
        self.assertEqual(result.value, 2)

    def test_ternary__Nested__RightAssociative(self):
        # a ? b : c ? d : e should be a ? b : (c ? d : e)
        config = {"a": False, "c": True}

        # Act
        result = self._evaluate('/a ? 1 : /c ? 2 : 3', config)

        # Assert - since a is false, we evaluate c ? 2 : 3, and c is true, so result is 2
        self.assertEqual(result.value, 2)

    def test_ternary__WithBooleanOperators__EvaluatesConditionCorrectly(self):
        # Arrange
        config = {"x": True, "y": True}

        # Act
        result = self._evaluate('/x and /y ? "both" : "not both"', config)

        # Assert
        self.assertEqual(result.value, "both")


class ElvisCoalesceEvaluatorTests(unittest.TestCase):
    """Tests for elvis coalesce (?:) operator evaluation."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)

    def _evaluate(
        self,
        expression: str,
        config: dict | None = None,
        env_getter=None,
    ) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config=config or {},
            registry=self.registry,
            env_getter=env_getter,
        )
        return evaluator.transform(tree)

    def test_elvis__NonNullValue__ReturnsLeftValue(self):
        # Act
        result = self._evaluate('42 ?: "fallback"')

        # Assert
        self.assertEqual(result.value, 42)

    def test_elvis__NullValue__ReturnsFallback(self):
        # Act
        result = self._evaluate('null ?: "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_elvis__ResolverReturnsValue__ReturnsResolverValue(self):
        # Arrange
        self.registry.resolve.return_value = "resolved"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:get_value ?: "fallback"')

        # Assert
        self.assertEqual(result.value, "resolved")

    def test_elvis__ResolverReturnsNull__ReturnsFallback(self):
        # Arrange
        self.registry.resolve.return_value = None
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:get_value ?: "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_elvis__UnknownResolver__ReturnsFallback(self):
        # Arrange
        self.registry.resolve.side_effect = UnknownResolverError("unknown", [])

        # Act
        result = self._evaluate('app:unknown ?: "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_elvis__MissingEnvVar__ReturnsFallback(self):
        # Arrange
        def env_getter(name: str) -> str | None:
            return None

        # Act
        result = self._evaluate('env:NONEXISTENT ?: "fallback"', env_getter=env_getter)

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_elvis__ResolverExecutionError__PropagatesException(self):
        # Arrange - elvis should NOT catch execution errors, only missing errors
        self.registry.resolve.side_effect = ResolverExecutionError(
            "failing", RuntimeError("boom")
        )

        # Act & Assert
        # Lark wraps the exception in VisitError, which contains the original
        with self.assertRaises(VisitError) as ctx:
            self._evaluate('app:failing ?: "fallback"')

        # Verify the original exception is the ResolverExecutionError
        self.assertIsInstance(ctx.exception.orig_exc, ResolverExecutionError)

    def test_elvis__Chained__EvaluatesRightToLeft(self):
        # Arrange - a ?: b ?: c should be a ?: (b ?: c)
        # If both a and b fail/null, should return c

        # First call for "a" returns null
        # Second call for "b" returns null
        self.registry.resolve.side_effect = [None, None]
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:a ?: app:b ?: "c"')

        # Assert
        self.assertEqual(result.value, "c")

    def test_elvis__ShortCircuit__DoesNotEvaluateFallbackWhenLeftSucceeds(self):
        # Arrange
        self.registry.resolve.return_value = "success"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:primary ?: 1/0')  # Would error if evaluated

        # Assert
        self.assertEqual(result.value, "success")
        # Should only be called once for primary, not for fallback
        self.registry.resolve.assert_called_once()


class ErrorCoalesceEvaluatorTests(unittest.TestCase):
    """Tests for error coalesce (??) operator evaluation."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)

    def _evaluate(
        self,
        expression: str,
        config: dict | None = None,
        env_getter=None,
    ) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config=config or {},
            registry=self.registry,
            env_getter=env_getter,
        )
        return evaluator.transform(tree)

    def test_error_coalesce__NonNullValue__ReturnsLeftValue(self):
        # Act
        result = self._evaluate('42 ?? "fallback"')

        # Assert
        self.assertEqual(result.value, 42)

    def test_error_coalesce__NullValue__ReturnsFallback(self):
        # Act
        result = self._evaluate('null ?? "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_error_coalesce__ResolverReturnsValue__ReturnsResolverValue(self):
        # Arrange
        self.registry.resolve.return_value = "resolved"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:get_value ?? "fallback"')

        # Assert
        self.assertEqual(result.value, "resolved")

    def test_error_coalesce__ResolverReturnsNull__ReturnsFallback(self):
        # Arrange
        self.registry.resolve.return_value = None
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:get_value ?? "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_error_coalesce__UnknownResolver__ReturnsFallback(self):
        # Arrange
        self.registry.resolve.side_effect = UnknownResolverError("unknown", [])

        # Act
        result = self._evaluate('app:unknown ?? "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_error_coalesce__MissingEnvVar__ReturnsFallback(self):
        # Arrange
        def env_getter(name: str) -> str | None:
            return None

        # Act
        result = self._evaluate('env:NONEXISTENT ?? "fallback"', env_getter=env_getter)

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_error_coalesce__ResolverExecutionError__CatchesAndReturnsFallback(self):
        # Arrange - error coalesce SHOULD catch execution errors
        self.registry.resolve.side_effect = ResolverExecutionError(
            "failing", RuntimeError("boom")
        )

        # Act
        result = self._evaluate('app:failing ?? "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_error_coalesce__AnyException__CatchesAndReturnsFallback(self):
        # Arrange
        self.registry.resolve.side_effect = ValueError("unexpected error")

        # Act
        result = self._evaluate('app:failing ?? "fallback"')

        # Assert
        self.assertEqual(result.value, "fallback")

    def test_error_coalesce__Chained__EvaluatesRightToLeft(self):
        # Arrange - a ?? b ?? c should be a ?? (b ?? c)
        # If both a and b fail, should return c
        self.registry.resolve.side_effect = [
            ResolverExecutionError("a", RuntimeError("boom")),
            ResolverExecutionError("b", RuntimeError("boom")),
        ]

        # Act
        result = self._evaluate('app:a ?? app:b ?? "c"')

        # Assert
        self.assertEqual(result.value, "c")

    def test_error_coalesce__ShortCircuit__DoesNotEvaluateFallbackWhenLeftSucceeds(self):
        # Arrange
        self.registry.resolve.return_value = "success"
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('app:primary ?? 1/0')  # Would error if evaluated

        # Assert
        self.assertEqual(result.value, "success")
        self.registry.resolve.assert_called_once()


class CombinedOperatorsEvaluatorTests(unittest.TestCase):
    """Tests for combinations of ternary and coalesce operators."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)

    def _evaluate(self, expression: str, config: dict | None = None) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config=config or {},
            registry=self.registry,
        )
        return evaluator.transform(tree)

    def test_combined__CoalesceInTernaryCondition__EvaluatesCorrectly(self):
        # Arrange
        self.registry.resolve.return_value = 10
        self.registry.known_resolvers = {}

        # Act
        result = self._evaluate('(app:get_value ?? 0) > 5 ? "high" : "low"')

        # Assert
        self.assertEqual(result.value, "high")

    def test_combined__CoalesceInTernaryConditionWithFallback__UsesFallback(self):
        # Arrange
        self.registry.resolve.side_effect = UnknownResolverError("unknown", [])

        # Act
        result = self._evaluate('(app:unknown ?? 10) > 5 ? "high" : "low"')

        # Assert
        self.assertEqual(result.value, "high")

    def test_combined__TernaryBranchesWithCoalesce__EvaluatesCorrectly(self):
        # Arrange
        self.registry.resolve.side_effect = [None]  # First resolver returns null
        self.registry.known_resolvers = {}
        config = {"flag": True}

        # Act
        result = self._evaluate('/flag ? app:a ?? "x" : "y"', config)

        # Assert
        self.assertEqual(result.value, "x")

    def test_combined__MixedCoalesceTypes__BehavesCorrectly(self):
        # Arrange - first resolver raises error
        self.registry.resolve.side_effect = [
            ResolverExecutionError("a", RuntimeError("boom")),
        ]

        # Act - app:a ?: ... should propagate error since ?: doesn't catch execution errors
        # Lark wraps the exception in VisitError
        with self.assertRaises(VisitError) as ctx:
            self._evaluate('app:a ?: "fallback"')

        # Verify the original exception is the ResolverExecutionError
        self.assertIsInstance(ctx.exception.orig_exc, ResolverExecutionError)


class EnvRefEvaluatorTests(unittest.TestCase):
    """Tests for environment variable reference evaluation."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)

    def _evaluate(self, expression: str, env: dict[str, str]) -> EvalResult:
        """Helper to parse and evaluate an expression against a fake environment."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config={},
            registry=self.registry,
            env_getter=env.get,
        )
        return evaluator.transform(tree)

    def test_env_ref__SetValue__ReturnsRawStringWithEnvSource(self):
        """Test that env values are returned as raw strings, uncoerced."""
        # Act
        result = self._evaluate("env:DEBUG", {"DEBUG": "false"})

        # Assert
        self.assertEqual(result.value, "false")
        self.assertEqual(result.source.kind, "env")
        self.assertEqual(result.source.env_var, "DEBUG")

    def test_env_ref__SetValueWithElvis__ReturnsEnvSource(self):
        """Test that a set env var short-circuits ?: and keeps the env source."""
        # Act
        result = self._evaluate("env:PORT ?: 8080", {"PORT": "9000"})

        # Assert
        self.assertEqual(result.value, "9000")
        self.assertEqual(result.source.kind, "env")

    def test_env_ref__UnsetValueWithElvis__ReturnsTypedLiteral(self):
        """Test that an unset env var falls back to the literal with its type."""
        # Act
        result = self._evaluate("env:PORT ?: 8080", {})

        # Assert
        self.assertEqual(result.value, 8080)
        self.assertIsInstance(result.value, int)

    def test_env_ref__EmptyValueWithElvis__UsesDefault(self):
        """Test that an empty env var falls back to the ?: default."""
        # Act
        result = self._evaluate("env:PORT ?: 8080", {"PORT": ""})

        # Assert
        self.assertEqual(result.value, 8080)


if __name__ == "__main__":
    unittest.main()


class AddOperatorEvaluatorTests(unittest.TestCase):
    """Tests for + : addition, list concatenation and string building."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)

    def _evaluate(self, expression: str, env: dict[str, str] | None = None) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config={},
            registry=self.registry,
            env_getter=(env or {}).get,
        )
        return evaluator.transform(tree)

    def _assert_raises_resolution_error(self, expression: str, env=None) -> str:
        """Evaluate and return the message of the resolution error it raises.

        lark wraps a transformer exception in VisitError, so the cause is what
        carries the library's own error.
        """
        with self.assertRaises((VisitError, InterpolationResolutionError)) as caught:
            self._evaluate(expression, env)
        error = caught.exception
        original = getattr(error, "orig_exc", error)
        self.assertIsInstance(original, InterpolationResolutionError)
        return str(original)

    def test_add__StringAndList__Raises(self):
        """A string plus a list used to stringify the list's repr.

        `"a" + ["b"]` produced the string "a['b']", which is not something a
        config author asks for, and it happened silently.
        """
        # Act
        message = self._assert_raises_resolution_error('"a" + ["b"]')

        # Assert
        self.assertIn("cannot add str and list", message)

    def test_add__ListAndString__Raises(self):
        """The same mistake with the operands the other way round."""
        # Act
        message = self._assert_raises_resolution_error('["b"] + "a"')

        # Assert
        self.assertIn("cannot add str and list", message)

    def test_add__EnvStringAndList__Raises(self):
        """The shape that motivated the fix.

        An env value is a string inside an expression, so appending defaults to
        a list read from the environment silently produced mangled strings -
        and only once the variable was set, so it passed in development.
        """
        # Act
        message = self._assert_raises_resolution_error(
            '(env:HOSTS ?: []) + ["localhost"]', {"HOSTS": "example.com"}
        )

        # Assert
        self.assertIn("cannot add str and list", message)

    def test_add__StringAndNumber__BuildsString(self):
        """Stringifying a scalar is the operator's job, and stays.

        rconfig_integrationtests/config_files/interpolation/complex/
        all_operations.yaml relies on it.
        """
        # Act
        result = self._evaluate('"epoch " + 100')

        # Assert
        self.assertEqual(result.value, "epoch 100")

    def test_add__TwoLists__Concatenates(self):
        # Act
        result = self._evaluate("[1, 2] + [3]")

        # Assert
        self.assertEqual(result.value, [1, 2, 3])

    def test_add__TwoNumbers__Adds(self):
        # Act
        result = self._evaluate("1 + 2")

        # Assert
        self.assertEqual(result.value, 3)


class CastFunctionEvaluatorTests(unittest.TestCase):
    """Tests for int() and float(), which give env values a numeric type."""

    def setUp(self) -> None:
        self.parser = InterpolationParser()
        self.registry = MagicMock(spec=ResolverRegistry.wrapped_class)

    def _evaluate(self, expression: str, env: dict[str, str] | None = None) -> EvalResult:
        """Helper to parse and evaluate an expression."""
        tree = self.parser.parse(expression)
        evaluator = ExpressionEvaluator(
            config={},
            registry=self.registry,
            env_getter=(env or {}).get,
        )
        return evaluator.transform(tree)

    def test_int__EnvValueInArithmetic__Adds(self):
        """Without the cast this concatenates, because env values are strings.

        An ${env:...} reference is converted to the declared field type only
        when it is the whole value of a key; inside an expression it is a
        string, so `env:PORT + 1` builds "90001" rather than adding.
        """
        # Act
        result = self._evaluate("int(env:PORT) + 1", {"PORT": "9000"})

        # Assert
        self.assertEqual(result.value, 9001)
        self.assertIsInstance(result.value, int)

    def test_float__EnvValueInArithmetic__Multiplies(self):
        # Act
        result = self._evaluate("float(env:RATIO) * 2", {"RATIO": "0.5"})

        # Assert
        self.assertEqual(result.value, 1.0)
        self.assertIsInstance(result.value, float)

    def test_int__NonNumericValue__RaisesNamingTheValue(self):
        """The error has to quote what it could not convert."""
        # Act
        with self.assertRaises((VisitError, InterpolationResolutionError)) as caught:
            self._evaluate("int(env:PORT)", {"PORT": "abc"})

        # Assert
        error = caught.exception
        original = getattr(error, "orig_exc", error)
        self.assertIsInstance(original, InterpolationResolutionError)
        self.assertIn("'abc'", str(original))

    def test_int__AlreadyANumber__IsUnchanged(self):
        # Act
        result = self._evaluate("int(42)")

        # Assert
        self.assertEqual(result.value, 42)
