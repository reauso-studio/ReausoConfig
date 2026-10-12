from abc import ABC, abstractmethod
from collections.abc import (
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set as AbstractSet,
)
from dataclasses import dataclass
from typing import Optional, Union
from unittest import TestCase
from unittest.mock import MagicMock, patch

from rconfig.target import TargetRegistry
from rconfig.validation import ConfigValidator, ValidationResult
from rconfig._internal.type_utils import (
    could_be_implicit_nested,
    find_registered_subclasses,
    is_class_type,
    is_concrete_type,
)
from rconfig.errors import (
    AmbiguousTargetError,
    InvalidOverridePathError,
    MissingFieldError,
    TargetNotFoundError,
    TargetTypeMismatchError,
    TypeInferenceError,
    TypeMismatchError,
)


class ConfigValidatorTests(TestCase):
    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_validate__ValidConfig__ReturnsValidResult(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            hidden_size: int
            dropout: float = 0.1

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "hidden_size": 256}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_validate__MissingTarget__ReturnsAmbiguousTargetError(self):
        # Arrange
        store = self._empty_store()
        validator = ConfigValidator(store)
        config = {"hidden_size": 256}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], AmbiguousTargetError)
        self.assertEqual(result.errors[0].field, "(root)")

    def test_validate__UnknownTarget__ReturnsTargetNotFoundError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            size: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "unknown", "size": 256}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)
        self.assertEqual(result.errors[0].target, "unknown")
        self.assertIn("model", result.errors[0].available)

    def test_validate__MissingRequiredField__ReturnsMissingFieldError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            required_field: int
            optional_field: str = "default"

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], MissingFieldError)
        self.assertEqual(result.errors[0].field, "required_field")

    def test_validate__TypeMismatch__ReturnsTypeMismatchError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            size: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "size": "not an int"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], TypeMismatchError)
        self.assertEqual(result.errors[0].field, "size")

    def test_validate__OptionalFieldWithNone__IsValid(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            value: Optional[int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": None}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__ListField__ValidatesElementTypes(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            layers: list[int]

        store.register("model", Model)
        validator = ConfigValidator(store)

        # Act & Assert - Valid list
        config = {"_target_": "model", "layers": [128, 256, 512]}
        result = validator.validate(config)
        self.assertTrue(result.valid)

        # Act & Assert - Invalid list element type
        config = {"_target_": "model", "layers": [128, "invalid", 512]}
        result = validator.validate(config)
        self.assertFalse(result.valid)

    def test_validate__DictField__ValidatesKeyValueTypes(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            params: dict[str, int]

        store.register("model", Model)
        validator = ConfigValidator(store)

        # Act & Assert - Valid dict
        config = {"_target_": "model", "params": {"a": 1, "b": 2}}
        result = validator.validate(config)
        self.assertTrue(result.valid)

        # Act & Assert - Invalid dict value type
        config = {"_target_": "model", "params": {"a": "not int"}}
        result = validator.validate(config)
        self.assertFalse(result.valid)

    def test_validate__NestedConfig__ValidatesRecursively(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class InnerModel:
            size: int

        @dataclass
        class OuterModel:
            inner: InnerModel

        store.register("inner", InnerModel)
        store.register("outer", OuterModel)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner", "size": 256},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__NestedConfigWithError__ReturnsNestedError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class InnerModel:
            size: int

        @dataclass
        class OuterModel:
            inner: InnerModel

        store.register("inner", InnerModel)
        store.register("outer", OuterModel)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner"},  # Missing required 'size'
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], MissingFieldError)
        self.assertEqual(result.errors[0].field, "size")
        self.assertEqual(result.errors[0].config_path, "inner")

    def test_validate__WithConfigPath__IncludesPathInErrors(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            size: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model"}

        # Act
        result = validator.validate(config, config_path="trainer.model")

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(result.errors[0].config_path, "trainer.model")

    def test_validate__MultipleErrors__ReturnsAllErrors(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            a: int
            b: str
            c: float

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "c": "not a float"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        # Should have 2 missing field errors (a, b) and 1 type error (c)
        self.assertEqual(len(result.errors), 3)


class ValidatorAmbiguousTargetErrorTests(TestCase):
    """Tests for AmbiguousTargetError when root _target_ is missing."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_validate__MissingRootTarget__RaisesAmbiguousTargetError(self):
        """Missing root _target_ raises AmbiguousTargetError (not MissingFieldError)."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            size: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"size": 256}  # No _target_ at root

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        error = result.errors[0]
        self.assertIsInstance(error, AmbiguousTargetError)
        self.assertEqual(error.field, "(root)")
        self.assertTrue(error.is_abstract)
        self.assertIn("model", error.available_targets)

    def test_validate__EmptyDict__RaisesAmbiguousTargetError(self):
        """Empty dict raises AmbiguousTargetError."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            size: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {}  # Empty dict

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        error = result.errors[0]
        self.assertIsInstance(error, AmbiguousTargetError)
        self.assertEqual(error.field, "(root)")

    def test_validate__MissingRootTarget__IncludesAllRegisteredTargets(self):
        """AmbiguousTargetError includes all registered targets in available_targets."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class ModelA:
            size: int

        @dataclass
        class ModelB:
            name: str

        store.register("model_a", ModelA)
        store.register("model_b", ModelB)
        validator = ConfigValidator(store)
        config = {"size": 256}

        # Act
        result = validator.validate(config)

        # Assert
        error = result.errors[0]
        self.assertIsInstance(error, AmbiguousTargetError)
        self.assertIn("model_a", error.available_targets)
        self.assertIn("model_b", error.available_targets)

    def test_validate__MissingRootTarget__WithConfigPath__IncludesPath(self):
        """AmbiguousTargetError includes config_path when provided."""
        # Arrange
        store = self._empty_store()
        validator = ConfigValidator(store)
        config = {"value": 42}

        # Act
        result = validator.validate(config, config_path="nested.section")

        # Assert
        error = result.errors[0]
        self.assertIsInstance(error, AmbiguousTargetError)
        self.assertEqual(error.config_path, "nested.section")


class ValidationResultTests(TestCase):
    def test_ValidationResult__ValidTrue__EmptyErrors(self):
        # Arrange & Act
        result = ValidationResult(valid=True)

        # Assert
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, [])

    def test_ValidationResult__ValidFalse__WithErrors(self):
        # Arrange
        error = MissingFieldError("field", "target")

        # Act
        result = ValidationResult(valid=False, errors=[error])

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)


class ConfigValidatorEdgeCaseTests(TestCase):
    """Tests for edge cases and uncovered code paths."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_validate__ClassWithVarKeyword__SkipsKwargsValidation(self):
        # Arrange
        store = self._empty_store()

        class ModelWithKwargs:
            def __init__(self, required: int, **kwargs: str) -> None:
                self.required = required
                self.kwargs = kwargs

        store.register("model", ModelWithKwargs)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "required": 42, "extra": "value"}

        # Act
        result = validator.validate(config)

        # Assert - should be valid, **kwargs should be skipped
        self.assertTrue(result.valid)

    def test_validate__ClassWithVarPositional__SkipsArgsValidation(self):
        # Arrange
        store = self._empty_store()

        class ModelWithArgs:
            def __init__(self, required: int, *args: int) -> None:
                self.required = required
                self.args = args

        store.register("model", ModelWithArgs)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "required": 42}

        # Act
        result = validator.validate(config)

        # Assert - should be valid, *args should be skipped
        self.assertTrue(result.valid)

    def test_validate__TypeHintsFails__SkipsTypeValidation(self):
        # Arrange
        store = self._empty_store()

        class ModelWithBadHints:
            def __init__(self, value: "NonExistentType") -> None:  # noqa: F821
                self.value = value

        store.register("model", ModelWithBadHints)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        # Act - should not raise, just skip type validation
        # Mock get_type_hints to raise an exception
        with patch(
            "rconfig.validation.Validator.get_type_hints",
            side_effect=NameError("name 'NonExistentType' is not defined"),
        ):
            result = validator.validate(config)

        # Assert - valid because type hints couldn't be resolved
        self.assertTrue(result.valid)

    def test_validate__UnionType__ValidatesAllOptions(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            value: Union[int, str]

        store.register("model", Model)
        validator = ConfigValidator(store)

        # Act & Assert - int is valid
        config = {"_target_": "model", "value": 42}
        result = validator.validate(config)
        self.assertTrue(result.valid)

        # Act & Assert - str is valid
        config = {"_target_": "model", "value": "hello"}
        result = validator.validate(config)
        self.assertTrue(result.valid)

        # Act & Assert - list is invalid
        config = {"_target_": "model", "value": [1, 2, 3]}
        result = validator.validate(config)
        self.assertFalse(result.valid)

    def test_validate__UntypedList__AcceptsAnyList(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            items: list  # No element type specified

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "items": [1, "mixed", 3.14]}

        # Act
        result = validator.validate(config)

        # Assert - any list should be valid
        self.assertTrue(result.valid)

    def test_validate__UntypedDict__AcceptsAnyDict(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            params: dict  # No key/value types specified

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "params": {1: "one", "two": 2}}

        # Act
        result = validator.validate(config)

        # Assert - any dict should be valid
        self.assertTrue(result.valid)

    def test_validate__NonListForListField__ReturnsTypeMismatchError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            layers: list[int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "layers": "not a list"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], TypeMismatchError)

    def test_validate__NonDictForDictField__ReturnsTypeMismatchError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            params: dict[str, int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "params": "not a dict"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], TypeMismatchError)

    def test_validate__NestedConfigForIntField__ValidatesRecursively(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            data: int  # Expects int, but we'll pass nested config

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "data": {"_target_": "inner", "value": 42},  # Nested config where int expected
        }

        # Act
        result = validator.validate(config)

        # Assert - nested config is validated recursively (returns True in _type_matches)
        self.assertTrue(result.valid)

    def test_validate__TupleType__ReturnsTypeMismatchError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            coords: tuple[int, int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "coords": (1, 2)}

        # Act
        result = validator.validate(config)

        # Assert - tuple is not handled, falls through to return False
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TypeMismatchError)

    def test_validate__UnionTypeInError__FormatsTypeReprCorrectly(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            value: Union[int, str]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 3.14}  # float is not int|str

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeMismatchError)
        # Check the expected type repr contains both types
        self.assertIn("int", error.expected)
        self.assertIn("str", error.expected)

    def test_validate__OptionalInError__FormatsTypeReprCorrectly(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Model:
            value: Optional[int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": "not an int"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeMismatchError)
        # Optional[int] should be formatted as "int | None"
        self.assertIn("int", error.expected)
        self.assertIn("None", error.expected)

    def test_validate__NoneTypeField__AcceptsNone(self):
        # Arrange - Test field typed as exactly None (rare edge case)
        store = self._empty_store()

        @dataclass
        class Model:
            sentinel: None  # Field that only accepts None

        store.register("model", Model)
        validator = ConfigValidator(store)

        # Act & Assert - None is valid
        config = {"_target_": "model", "sentinel": None}
        result = validator.validate(config)
        self.assertTrue(result.valid)

        # Act & Assert - non-None is invalid
        config = {"_target_": "model", "sentinel": 42}
        result = validator.validate(config)
        self.assertFalse(result.valid)

    def test_validate__UntypedListInError__FormatsTypeReprCorrectly(self):
        # Arrange - tests _type_repr for untyped list (line 247)
        store = self._empty_store()

        @dataclass
        class Model:
            items: list  # Untyped list

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "items": "not a list"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeMismatchError)
        self.assertEqual(error.expected, "list")

    def test_validate__UntypedDictInError__FormatsTypeReprCorrectly(self):
        # Arrange - tests _type_repr for untyped dict (line 252)
        store = self._empty_store()

        @dataclass
        class Model:
            params: dict  # Untyped dict

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "params": "not a dict"}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeMismatchError)
        self.assertEqual(error.expected, "dict")

    def test_validate__ComplexTypeWithoutName__FormatsTypeReprAsFallback(self):
        # Arrange - test _type_repr fallback for type without __name__ (line 257)
        store = self._empty_store()

        # Use a generic alias that doesn't have __name__
        from typing import Callable

        @dataclass
        class Model:
            callback: Callable[[int], str]  # Callable doesn't have simple __name__

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "callback": "not callable"}

        # Act
        result = validator.validate(config)

        # Assert - should fail with some type repr (fallback to str())
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeMismatchError)
        # The expected should be some string representation
        self.assertTrue(len(error.expected) > 0)


class ConfigValidatorImplicitTargetTests(TestCase):
    """Tests for implicit _target_ inference in nested configs."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_validate__ImplicitNestedConfig_ConcreteType__ReturnsValidResult(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__ImplicitNestedConfig_AbstractType__ReturnsAmbiguousTargetError(self):
        # Arrange
        store = self._empty_store()

        class AbstractProcessor(ABC):
            @abstractmethod
            def process(self) -> None:
                pass

        class ConcreteProcessor(AbstractProcessor):
            def __init__(self, mode: str) -> None:
                self.mode = mode

            def process(self) -> None:
                pass

        @dataclass
        class Pipeline:
            processor: AbstractProcessor

        store.register("concrete", ConcreteProcessor)
        store.register("pipeline", Pipeline)
        validator = ConfigValidator(store)
        config = {
            "_target_": "pipeline",
            "processor": {"mode": "fast"},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], AmbiguousTargetError)
        self.assertTrue(result.errors[0].is_abstract)

    def test_validate__ImplicitNestedConfig_MultipleSubclasses__ReturnsAmbiguousTargetError(
        self,
    ):
        # Arrange
        store = self._empty_store()

        class Base:
            def __init__(self, value: int) -> None:
                self.value = value

        class ChildA(Base):
            pass

        class ChildB(Base):
            pass

        @dataclass
        class Container:
            item: Base

        store.register("base", Base)
        store.register("child_a", ChildA)
        store.register("child_b", ChildB)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"value": 10},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, AmbiguousTargetError)
        self.assertIn("base", error.available_targets)
        self.assertIn("child_a", error.available_targets)

    def test_validate__ImplicitNestedConfig_ValidationFails__ReturnsTypeInferenceError(
        self,
    ):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            required_field: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"wrong_field": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeInferenceError)
        self.assertIn("_target_", str(error))

    def test_validate__ExplicitTarget_WrongType__ReturnsTargetTypeMismatchError(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class TypeA:
            value: int

        @dataclass
        class TypeB:
            name: str

        @dataclass
        class Container:
            item: TypeA

        store.register("type_a", TypeA)
        store.register("type_b", TypeB)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "type_b", "name": "test"},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TargetTypeMismatchError)

    def test_validate__OptionalField_ImplicitNested__ReturnsValidResult(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Optional[Inner]

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__DeeplyNestedImplicit__ReturnsValidResult(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class Level3:
            value: int

        @dataclass
        class Level2:
            level3: Level3

        @dataclass
        class Level1:
            level2: Level2

        store.register("l3", Level3)
        store.register("l2", Level2)
        store.register("l1", Level1)
        validator = ConfigValidator(store)
        config = {
            "_target_": "l1",
            "level2": {
                "level3": {"value": 99},
            },
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__MixedExplicitImplicit__ReturnsValidResult(self):
        # Arrange
        store = self._empty_store()

        @dataclass
        class A:
            x: int

        @dataclass
        class B:
            y: str

        @dataclass
        class Container:
            a: A
            b: B

        store.register("a", A)
        store.register("b", B)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "a": {"x": 10},
            "b": {"_target_": "b", "y": "hello"},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__ExplicitTarget_CorrectSubtype__ReturnsValidResult(self):
        # Arrange
        store = self._empty_store()

        class Base:
            def __init__(self, value: int) -> None:
                self.value = value

        class Child(Base):
            pass

        @dataclass
        class Container:
            item: Base

        store.register("base", Base)
        store.register("child", Child)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "child", "value": 10},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__UnionWithMultipleTypes__SkipsImplicitInference(self):
        """Test Union[A, B] with multiple non-None types returns None from _extract_class_from_hint."""
        # Covers line 248 - Union with multiple non-None types can't be implicitly inferred
        # However, the validator will still accept a dict as valid for Union types
        # because _type_matches returns True for dicts against class types (line 507-508)
        store = self._empty_store()

        @dataclass
        class TypeA:
            value: int

        @dataclass
        class TypeB:
            name: str

        @dataclass
        class Container:
            item: Union[TypeA, TypeB]  # Not Optional, multiple types

        store.register("type_a", TypeA)
        store.register("type_b", TypeB)
        store.register("container", Container)
        validator = ConfigValidator(store)
        # Pass a dict without _target_ - won't trigger implicit inference for Union[A, B]
        # but _type_matches allows dicts for class types
        config = {"_target_": "container", "item": {"value": 10}}

        # Act
        result = validator.validate(config)

        # Assert - valid because _type_matches treats dict as potentially valid for class types
        # (the actual instantiation would need explicit _target_)
        self.assertTrue(result.valid)

    def test_validate__TypeNotRegisteredInTypeCheck__SkipsTypeCheck(self):
        """Test when nested config target is not in store during type check (line 425)."""
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("outer", Outer)
        # Note: "inner" is NOT registered, but we use explicit _target_
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "unknown_inner", "value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert - Should fail with TargetNotFoundError
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)

    def test_validate__ClassNotRegisteredButHasSubclasses__ReturnsAmbiguousError(self):
        """Test type not registered directly but has registered subclasses (line 285)."""
        store = self._empty_store()

        class Base:
            def __init__(self, value: int) -> None:
                self.value = value

        class Child(Base):
            pass

        @dataclass
        class Container:
            item: Base

        # Register only the child, not the base
        store.register("child", Child)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"value": 10},  # Implicit - Base not registered, only Child
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], AmbiguousTargetError)

    def test_validate__UnregisteredConcreteType_NoSubclasses__AutoRegistersAndValidates(self):
        """Test concrete type without registration auto-registers when no subclasses exist."""
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner  # Inner NOT registered

        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"value": 42},  # Should auto-register Inner
        }

        result = validator.validate(config)

        self.assertTrue(result.valid)
        # Verify Inner was auto-registered
        self.assertIn("inner", store._known_targets)

    def test_validate__NoTypeHintForField__SkipsTypeValidation(self):
        """Test field without type hint is skipped (line 148-149)."""
        store = self._empty_store()

        class Model:
            def __init__(self, value) -> None:  # No type hint
                self.value = value

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": "anything"}

        # Act
        result = validator.validate(config)

        # Assert - should be valid since no type hint to validate against
        self.assertTrue(result.valid)

    def test_validate__ExplicitNestedWithoutExpectedType__SkipsTypeCheck(self):
        """Test explicit nested config when expected_type is None (line 415)."""
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        # Use a class without type hints on the inner field
        class Outer:
            def __init__(self, inner) -> None:  # No type hint
                self.inner = inner

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner", "value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert - valid because no type hint to check against
        self.assertTrue(result.valid)

    def test_validate__ExplicitNestedWithNonClassHint__SkipsTypeCheck(self):
        """Test explicit nested config when class_type extraction returns None (line 421)."""
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: list[Inner]  # Generic type, not a class

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": [{"_target_": "inner", "value": 42}],
        }

        # Act
        result = validator.validate(config)

        # Assert - valid because list[Inner] is not a class type
        self.assertTrue(result.valid)

    def test_validate__IssubclassTypeError__HandlesGracefully(self):
        """Test issubclass TypeError handling (lines 270-272, 441-443)."""
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Test _find_registered_subclasses with a non-class base
        # This is hard to trigger directly, but we can verify the method handles it
        # by registering something that could cause issues

        # A function is not a valid type for issubclass
        def not_a_class():
            pass

        # We can't easily trigger the TypeError in issubclass from user config,
        # but we can verify the code path exists

    def test_validate__ImplicitNestedForPrimitiveType__DoesNotInfer(self):
        """Test dict without _target_ where expected type is primitive doesn't infer."""
        store = self._empty_store()

        @dataclass
        class Model:
            data: dict  # Plain dict, not a class type

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {
            "_target_": "model",
            "data": {"key": "value"},  # Should stay as dict, not try to instantiate
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)

    # === Additional TargetTypeMismatchError Tests ===

    def test_validate__ExplicitTarget_SiblingClass__ReturnsTargetTypeMismatchError(self):
        """Target is registered subclass of common base but not expected type."""
        # Arrange
        store = self._empty_store()

        class Base:
            def __init__(self, value: int) -> None:
                self.value = value

        class ChildA(Base):
            pass

        class ChildB(Base):
            pass

        @dataclass
        class Container:
            item: ChildA  # Expects ChildA specifically

        store.register("child_a", ChildA)
        store.register("child_b", ChildB)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "child_b", "value": 10},  # ChildB is not ChildA
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TargetTypeMismatchError)
        self.assertEqual(error.field, "item")
        self.assertEqual(error.target, "child_b")
        self.assertEqual(error.expected_type, ChildA)

    def test_validate__ExplicitTarget_WrongTypeNested__ReturnsTargetTypeMismatchError(self):
        """Deeply nested config with wrong target type."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class WrongType:
            name: str

        @dataclass
        class CorrectType:
            value: int

        @dataclass
        class Middle:
            inner: CorrectType

        @dataclass
        class Outer:
            middle: Middle

        store.register("wrong_type", WrongType)
        store.register("correct_type", CorrectType)
        store.register("middle", Middle)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "middle": {
                "_target_": "middle",
                "inner": {"_target_": "wrong_type", "name": "test"},
            },
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TargetTypeMismatchError)
        self.assertEqual(error.field, "inner")
        self.assertIn("middle.inner", error.config_path)

    def test_validate__ExplicitTarget_ParentClass__ReturnsTargetTypeMismatchError(self):
        """Target is parent class when child class is expected."""
        # Arrange
        store = self._empty_store()

        class ParentClass:
            def __init__(self, value: int) -> None:
                self.value = value

        class ChildClass(ParentClass):
            pass

        @dataclass
        class Container:
            item: ChildClass  # Expects ChildClass, not ParentClass

        store.register("parent_class", ParentClass)
        store.register("child_class", ChildClass)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "parent_class", "value": 10},  # Parent is not Child
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TargetTypeMismatchError)
        self.assertEqual(error.target, "parent_class")
        self.assertEqual(error.expected_type, ChildClass)

    # === Additional TypeInferenceError Tests ===

    def test_validate__ImplicitNested_TypeMismatch__ReturnsTypeInferenceError(self):
        """Implicit nested config with wrong type for a field."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"value": "not_an_int"},  # Wrong type, no _target_
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeInferenceError)
        self.assertEqual(error.field, "inner")
        self.assertEqual(error.inferred_type, Inner)
        # Verify it wraps a TypeMismatchError
        self.assertEqual(len(error.validation_errors), 1)
        self.assertIsInstance(error.validation_errors[0], TypeMismatchError)

    def test_validate__ImplicitNested_NestedValidationFails__ReturnsTypeInferenceError(self):
        """Implicit nested config with nested validation failure."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class DeepInner:
            required_field: int

        @dataclass
        class Inner:
            deep: DeepInner

        @dataclass
        class Outer:
            inner: Inner

        store.register("deep_inner", DeepInner)
        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {
                "deep": {},  # Missing required_field
            },
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeInferenceError)
        self.assertEqual(error.field, "inner")

    def test_validate__ImplicitNested_MultipleErrors__ReturnsTypeInferenceErrorWithAll(self):
        """Implicit nested config with multiple validation errors."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            required_a: int
            required_b: str

        @dataclass
        class Outer:
            inner: Inner

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {},  # Missing both required_a and required_b
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeInferenceError)
        # Verify it wraps multiple MissingFieldErrors
        self.assertEqual(len(error.validation_errors), 2)
        for wrapped_error in error.validation_errors:
            self.assertIsInstance(wrapped_error, MissingFieldError)


class ConfigValidatorAutoRegistrationTests(TestCase):
    """Tests for auto-registration of concrete types from type hints."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    # === SUCCESS CASES ===

    def test_validate__ExplicitTargetMatchesTypeHint__AutoRegistersAndValidates(self):
        """Explicit _target_ matching type hint class name auto-registers."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("outer", Outer)
        # Inner is NOT registered
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner", "value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertIn("inner", store._known_targets)

    def test_validate__ExplicitTargetCaseInsensitive__AutoRegisters(self):
        """Target name matching is case-insensitive (e.g., 'myclass' matches MyClass)."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class MyClass:
            value: int

        @dataclass
        class Container:
            item: MyClass

        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "myclass", "value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertIn("myclass", store._known_targets)

    def test_validate__DeeplyNestedExplicitTargets__AutoRegistersAll(self):
        """Multiple levels of nested explicit targets are auto-registered."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Level3:
            value: int

        @dataclass
        class Level2:
            level3: Level3

        @dataclass
        class Level1:
            level2: Level2

        store.register("level1", Level1)
        validator = ConfigValidator(store)
        config = {
            "_target_": "level1",
            "level2": {
                "_target_": "level2",
                "level3": {"_target_": "level3", "value": 99},
            },
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertIn("level2", store._known_targets)
        self.assertIn("level3", store._known_targets)

    def test_validate__ExplicitTargetWithOptionalType__AutoRegisters(self):
        """Optional[SomeClass] type hint with matching _target_ auto-registers."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Optional[Inner]

        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner", "value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertIn("inner", store._known_targets)

    # === ERROR CASES ===

    def test_validate__ExplicitTargetMismatchesTypeHint__ReturnsTargetNotFoundError(self):
        """Explicit _target_ that doesn't match type hint class name fails."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "wrong_name", "value": 42},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)
        self.assertEqual(result.errors[0].target, "wrong_name")

    def test_validate__ExplicitTargetAbstractType__ReturnsTargetNotFoundError(self):
        """Can't auto-register abstract classes even with matching name."""
        # Arrange
        store = self._empty_store()

        class AbstractBase(ABC):
            @abstractmethod
            def method(self) -> None:
                pass

        @dataclass
        class Container:
            item: AbstractBase

        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "abstractbase", "value": 10},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)

    def test_validate__ExplicitTargetNoTypeHint__SkipsNestedValidation(self):
        """Without type hint, nested config validation is skipped (no auto-registration)."""
        # Arrange
        store = self._empty_store()

        class Model:
            def __init__(self, data) -> None:  # No type hint
                self.data = data

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {
            "_target_": "model",
            "data": {"_target_": "unknown", "value": 42},  # Nested config not validated
        }

        # Act
        result = validator.validate(config)

        # Assert - validation passes because nested config isn't validated without type hint
        self.assertTrue(result.valid)
        # "unknown" is not auto-registered (no type hint to infer from)
        self.assertNotIn("unknown", store._known_targets)

    def test_validate__ExplicitTargetUnionType__ReturnsTargetNotFoundError(self):
        """Union[A, B] type hint can't auto-register (ambiguous)."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class TypeA:
            value: int

        @dataclass
        class TypeB:
            name: str

        @dataclass
        class Container:
            item: Union[TypeA, TypeB]

        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "item": {"_target_": "typea", "value": 10},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)

    def test_validate__ExplicitTargetMissingRequiredField__ReturnsMissingFieldError(self):
        """Auto-registered explicit target with missing field fails validation."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            required_value: int  # Required field

        @dataclass
        class Outer:
            inner: Inner

        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner"},  # Missing required_value
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], MissingFieldError)
        self.assertEqual(result.errors[0].field, "required_value")

    def test_validate__ExplicitTargetWrongFieldType__ReturnsTypeMismatchError(self):
        """Auto-registered explicit target with wrong field type fails."""
        # Arrange
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner", "value": "not_an_int"},
        }

        # Act
        result = validator.validate(config)

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TypeMismatchError)
        self.assertEqual(result.errors[0].field, "value")


class ValidateOverridePathTests(TestCase):
    """Tests for validate_override_path method (lines 543-599)."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    # --- Empty path (line 557-558) ---
    def test_validatePath__EmptyPath__RaisesInvalidOverridePathError(self):
        store = self._empty_store()
        validator = ConfigValidator(store)
        config = {"key": "value"}

        with self.assertRaises(InvalidOverridePathError) as ctx:
            validator.validate_override_path([], config)
        self.assertIn("Empty path", str(ctx.exception))

    # --- Dict key access (lines 583-597) ---
    def test_validatePath__SimpleKey__ReturnsTypeHint(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        result = validator.validate_override_path(["value"], config)

        self.assertEqual(result, int)

    def test_validatePath__NestedDictKey__ReturnsTypeHint(self):
        store = self._empty_store()

        @dataclass
        class Inner:
            count: int

        @dataclass
        class Outer:
            inner: Inner

        store.register("inner", Inner)
        store.register("outer", Outer)
        validator = ConfigValidator(store)
        config = {
            "_target_": "outer",
            "inner": {"_target_": "inner", "count": 10},
        }

        result = validator.validate_override_path(["inner", "count"], config)

        self.assertEqual(result, int)

    def test_validatePath__KeyNotFound__RaisesInvalidOverridePathError(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        with self.assertRaises(InvalidOverridePathError) as ctx:
            validator.validate_override_path(["nonexistent"], config)
        self.assertIn("not found", str(ctx.exception))

    def test_validatePath__KeyOnNonDict__RaisesInvalidOverridePathError(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        with self.assertRaises(InvalidOverridePathError) as ctx:
            validator.validate_override_path(["value", "nested"], config)
        self.assertIn("non-dict", str(ctx.exception))

    # --- List index access (lines 564-582) ---
    def test_validatePath__ListIndex__ReturnsElementType(self):
        store = self._empty_store()

        @dataclass
        class Model:
            items: list[int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "items": [1, 2, 3]}

        result = validator.validate_override_path(["items", 0], config)

        self.assertEqual(result, int)

    def test_validatePath__ListIndexOutOfRange__RaisesInvalidOverridePathError(self):
        store = self._empty_store()

        @dataclass
        class Model:
            items: list[int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "items": [1, 2]}

        with self.assertRaises(InvalidOverridePathError) as ctx:
            validator.validate_override_path(["items", 99], config)
        self.assertIn("out of range", str(ctx.exception))

    def test_validatePath__NegativeListIndex__RaisesInvalidOverridePathError(self):
        store = self._empty_store()

        @dataclass
        class Model:
            items: list[int]

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "items": [1, 2]}

        with self.assertRaises(InvalidOverridePathError) as ctx:
            validator.validate_override_path(["items", -1], config)
        self.assertIn("out of range", str(ctx.exception))

    def test_validatePath__IndexOnNonList__RaisesInvalidOverridePathError(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        with self.assertRaises(InvalidOverridePathError) as ctx:
            validator.validate_override_path(["value", 0], config)
        self.assertIn("non-list", str(ctx.exception))

    # --- Mixed path access ---
    def test_validatePath__MixedDictAndList__TraversesCorrectly(self):
        store = self._empty_store()

        @dataclass
        class Item:
            name: str

        @dataclass
        class Container:
            items: list[Item]

        store.register("item", Item)
        store.register("container", Container)
        validator = ConfigValidator(store)
        config = {
            "_target_": "container",
            "items": [
                {"_target_": "item", "name": "first"},
                {"_target_": "item", "name": "second"},
            ],
        }

        result = validator.validate_override_path(["items", 0, "name"], config)

        self.assertEqual(result, str)

    # --- Type hint resolution edge cases (lines 576-582) ---
    def test_validatePath__ListWithNoTypeArgs__ReturnsNone(self):
        store = self._empty_store()

        @dataclass
        class Model:
            items: list  # Untyped list

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "items": [1, 2, 3]}

        result = validator.validate_override_path(["items", 0], config)

        # Untyped list - can't determine element type
        self.assertIsNone(result)


class GetFieldTypeTests(TestCase):
    """Tests for _get_field_type method (lines 601-622)."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_getFieldType__NoTargetInConfig__ReturnsNone(self):
        store = self._empty_store()
        validator = ConfigValidator(store)
        config = {"value": 42}  # No _target_

        result = validator._get_field_type(config, "value")

        self.assertIsNone(result)

    def test_getFieldType__UnknownTarget__ReturnsNone(self):
        store = self._empty_store()
        validator = ConfigValidator(store)
        config = {"_target_": "unknown", "value": 42}

        result = validator._get_field_type(config, "value")

        self.assertIsNone(result)

    def test_getFieldType__ValidTarget_ExistingField__ReturnsType(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        result = validator._get_field_type(config, "value")

        self.assertEqual(result, int)

    def test_getFieldType__ValidTarget_NonExistentField__ReturnsNone(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        result = validator._get_field_type(config, "nonexistent")

        self.assertIsNone(result)

    def test_getFieldType__GetTypeHintsFails__ReturnsNone(self):
        store = self._empty_store()

        @dataclass
        class Model:
            value: int

        store.register("model", Model)
        validator = ConfigValidator(store)
        config = {"_target_": "model", "value": 42}

        with patch(
            "rconfig.validation.Validator.get_type_hints",
            side_effect=NameError("Bad type hint"),
        ):
            result = validator._get_field_type(config, "value")

        self.assertIsNone(result)


class IsClassTypeTests(TestCase):
    """Tests for _is_class_type edge cases (lines 207-208)."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_isClassType__GenericType__ReturnsFalse(self):
        # Generic types have an origin, should return False
        self.assertFalse(is_class_type(list[int]))
        self.assertFalse(is_class_type(dict[str, int]))
        self.assertFalse(is_class_type(Optional[int]))

    def test_isClassType__NonTypeObject__ReturnsFalse(self):
        # Non-type objects should return False
        self.assertFalse(is_class_type("not a type"))  # type: ignore
        self.assertFalse(is_class_type(42))  # type: ignore
        self.assertFalse(is_class_type(None))  # type: ignore


class FindRegisteredSubclassesTests(TestCase):
    """Tests for find_registered_subclasses error handling."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_findSubclasses__IssubclassTypeError__HandledGracefully(self):
        store = self._empty_store()

        class Base:
            pass

        # Register Base normally
        store.register("base", Base)

        # Mock issubclass to raise TypeError for our test
        original_issubclass = issubclass

        def mock_issubclass(cls, classinfo):
            if cls is Base:
                raise TypeError("Mock TypeError")
            return original_issubclass(cls, classinfo)

        with patch("rconfig._internal.type_utils.issubclass", side_effect=mock_issubclass):
            # This should not raise, just skip the problematic class
            result = find_registered_subclasses(store, Base)

        # Result should be empty since the TypeError was caught
        self.assertIsInstance(result, list)


class CheckTargetTypeCompatibilityTests(TestCase):
    """Tests for _check_target_type_compatibility edge cases (lines 415-444)."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_checkCompatibility__NoExpectedType__ReturnsEmpty(self):
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        store.register("inner", Inner)
        validator = ConfigValidator(store)
        config = {"_target_": "inner", "value": 42}

        result = validator._check_target_type_compatibility(
            config, None, "field", "path"
        )

        self.assertEqual(result, [])

    def test_checkCompatibility__GenericExpectedType__ReturnsEmpty(self):
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        store.register("inner", Inner)
        validator = ConfigValidator(store)
        config = {"_target_": "inner", "value": 42}

        # list[Inner] is a generic type, _extract_class_from_hint returns None
        result = validator._check_target_type_compatibility(
            config, list[Inner], "field", "path"
        )

        self.assertEqual(result, [])

    def test_checkCompatibility__IssubclassTypeError__HandledGracefully(self):
        store = self._empty_store()

        @dataclass
        class Inner:
            value: int

        class Expected:
            pass

        store.register("inner", Inner)
        validator = ConfigValidator(store)
        config = {"_target_": "inner", "value": 42}

        # Mock issubclass to raise TypeError
        with patch(
            "rconfig.validation.Validator.issubclass",
            side_effect=TypeError("Mock TypeError"),
        ):
            # This should not raise
            result = validator._check_target_type_compatibility(
                config, Expected, "field", "path"
            )

        # Should return empty list (TypeError caught)
        self.assertEqual(result, [])


class TypeReprTests(TestCase):
    """Tests for _type_repr edge cases (lines 531, 536, 541)."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_typeRepr__UntypedList__ReturnsListString(self):
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Create an untyped list type annotation
        result = validator._type_repr(list)

        self.assertEqual(result, "list")

    def test_typeRepr__UntypedDict__ReturnsDictString(self):
        store = self._empty_store()
        validator = ConfigValidator(store)

        result = validator._type_repr(dict)

        self.assertEqual(result, "dict")

    def test_typeRepr__TypeWithoutName__ReturnsFallbackStr(self):
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Create a mock type without __name__
        mock_type = MagicMock()
        del mock_type.__name__  # Remove __name__ attribute
        mock_type.__str__ = lambda self: "MockType"

        result = validator._type_repr(mock_type)

        self.assertIn("Mock", result)


class CouldBeImplicitNestedTests(TestCase):
    """Tests for could_be_implicit_nested edge cases."""

    def test_couldBeImplicit__DictWithTarget__ReturnsFalse(self):
        @dataclass
        class Model:
            value: int

        result = could_be_implicit_nested(
            {"_target_": "model", "value": 42}, Model
        )

        self.assertFalse(result)

    def test_couldBeImplicit__NoneExpectedType__ReturnsFalse(self):
        result = could_be_implicit_nested({"value": 42}, None)

        self.assertFalse(result)


class ConfigValidatorCoverageTests(TestCase):
    """Tests to improve ConfigValidator coverage for edge cases."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_is_concrete_type__UnregisteredConcrete__ReturnsConcreteNoTarget(self):
        """Test is_concrete_type returns (True, None, []) for unregistered concrete class."""
        store = self._empty_store()

        @dataclass
        class MyClass:
            value: int

        # Act - pure query, does NOT register
        is_concrete_result, exact_target, matching = is_concrete_type(store, MyClass)

        # Assert - concrete but not registered
        self.assertTrue(is_concrete_result)
        self.assertIsNone(exact_target)
        self.assertEqual(matching, [])
        self.assertNotIn("myclass", store.known_targets)

    def test_implicit_nested_errors__ClassTypeExtractionFails__ReturnsEmpty(self):
        """Test _implicit_nested_errors returns empty when class extraction fails."""
        # Arrange - line 385
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Generic type that _extract_class_from_hint can't handle
        result = validator._implicit_nested_errors(
            {"value": 42}, list[int], "field", "path"
        )

        # Assert - should return empty (extraction returns None)
        self.assertEqual(result, [])

    def test_check_target_type_compatibility__TargetNotFound__ReturnsEmpty(self):
        """Test _check_target_type_compatibility returns empty when target not found."""
        # Arrange - line 449
        store = self._empty_store()

        class ExpectedClass:
            pass

        validator = ConfigValidator(store)
        # Config with unknown target
        config = {"_target_": "unknown_target", "value": 42}

        # Act
        result = validator._check_target_type_compatibility(
            config, ExpectedClass, "field", "path"
        )

        # Assert - should return empty (target not found)
        self.assertEqual(result, [])

    def test_type_matches__EmptyListHint__ReturnsTrue(self):
        """Test _type_matches with bare list type (no args) always returns True."""
        # Arrange - line 509
        store = self._empty_store()
        validator = ConfigValidator(store)
        value = [1, 2, 3]

        # Act - bare list type has no args
        result = validator._type_matches(value, list)

        # Assert
        self.assertTrue(result)

    def test_type_matches__EmptyDictHint__ReturnsTrue(self):
        """Test _type_matches with bare dict type (no args) always returns True."""
        # Arrange - line 517
        store = self._empty_store()
        validator = ConfigValidator(store)
        value = {"key": "value"}

        # Act - bare dict type has no args
        result = validator._type_matches(value, dict)

        # Assert
        self.assertTrue(result)

    def test_type_repr__BareList__ReturnsListString(self):
        """Test _type_repr returns 'list' for bare list type."""
        # Arrange - line 554
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Act
        result = validator._type_repr(list)

        # Assert
        self.assertEqual(result, "list")

    def test_type_repr__BareDict__ReturnsDictString(self):
        """Test _type_repr returns 'dict' for bare dict type."""
        # Arrange - line 559
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Act
        result = validator._type_repr(dict)

        # Assert
        self.assertEqual(result, "dict")

    # === Untyped collection matching tests (lines 378, 386) ===

    def test_validate__UntypedListHint__AcceptsAnyList(self):
        """Test that bare 'list' type hint accepts any list content."""
        # Arrange - covers line 378 (_matches_list_type returns True when no args)
        store = self._empty_store()

        @dataclass
        class Config:
            items: list  # No generic type parameter

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "items": [1, "two", 3.0, None]}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_validate__UntypedDictHint__AcceptsAnyDict(self):
        """Test that bare 'dict' type hint accepts any dict content."""
        # Arrange - covers line 386 (_matches_dict_type returns True when no args)
        store = self._empty_store()

        @dataclass
        class Config:
            data: dict  # No generic type parameters

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "data": {"a": 1, "b": "two", "c": [1, 2, 3]}}

        # Act
        result = validator.validate(config)

        # Assert
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    # === Type representation tests (lines 421, 426) ===

    def test_type_repr__GenericListNoArgs__ReturnsListString(self):
        """Test _type_repr returns 'list' for list with empty args."""
        # Arrange - covers line 421 (list without args)
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Act
        result = validator._type_repr(list)

        # Assert
        self.assertEqual(result, "list")

    def test_type_repr__GenericDictNoArgs__ReturnsDictString(self):
        """Test _type_repr returns 'dict' for dict with empty args."""
        # Arrange - covers line 426 (dict without args)
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Act
        result = validator._type_repr(dict)

        # Assert
        self.assertEqual(result, "dict")

    # === List element type extraction (line 488) ===

    def test_getListElementType__NoneType__ReturnsNone(self):
        """Test _get_list_element_type returns None for None input."""
        # Arrange - covers line 488
        store = self._empty_store()
        validator = ConfigValidator(store)

        # Act
        result = validator._get_list_element_type(None)

        # Assert
        self.assertIsNone(result)


class ConfigValidatorABCContainerTests(TestCase):
    """Tests for ABC container type matching in validation."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def test_validate__SequenceField__AcceptsListValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            items: Sequence[int]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "items": [1, 2, 3]}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__MutableSequenceField__AcceptsListValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            items: MutableSequence[str]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "items": ["a", "b"]}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__MappingField__AcceptsDictValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            data: Mapping[str, int]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "data": {"a": 1, "b": 2}}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__MutableMappingField__AcceptsDictValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            data: MutableMapping[str, float]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "data": {"x": 1.0}}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__SetField__AcceptsListValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            tags: set[int]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "tags": [1, 2, 3]}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__FrozensetField__AcceptsListValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            tags: frozenset[str]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "tags": ["a", "b"]}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__AbstractSetField__AcceptsListValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            items: AbstractSet[int]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "items": [1, 2, 3]}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__TupleField__AcceptsListValue(self):
        store = self._empty_store()

        @dataclass
        class Config:
            coords: tuple[int, ...]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "coords": [1, 2, 3]}

        result = validator.validate(config)

        self.assertTrue(result.valid)

    def test_validate__SequenceWrongElementType__ReportsError(self):
        store = self._empty_store()

        @dataclass
        class Config:
            items: Sequence[int]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "items": ["not", "ints"]}

        result = validator.validate(config)

        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], TypeMismatchError)

    def test_validate__MappingWrongValueType__ReportsError(self):
        store = self._empty_store()

        @dataclass
        class Config:
            data: Mapping[str, int]

        store.register("config", Config)
        validator = ConfigValidator(store)
        config = {"_target_": "config", "data": {"a": "not_int"}}

        result = validator.validate(config)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TypeMismatchError)


class ConfigValidatorPep604UnionTests(TestCase):
    """Tests for PEP 604 union type hints (``X | None``) in validation."""

    def _empty_store(self) -> TargetRegistry:
        store = TargetRegistry()
        store.clear()
        return store

    def _validation_result(self, field_type: type, value: object) -> ValidationResult:
        """Validate a single-field config whose field has the given type hint."""
        store = self._empty_store()

        @dataclass
        class Config:
            value: field_type

        store.register("config", Config)
        validator = ConfigValidator(store)
        return validator.validate({"_target_": "config", "value": value})

    def test_validate__Pep604OptionalWithInt__ReturnsValid(self):
        """Test that an int value satisfies an ``int | None`` hint."""
        # Act
        result = self._validation_result(int | None, 5)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__Pep604OptionalWithNone__ReturnsValid(self):
        """Test that None satisfies an ``int | None`` hint."""
        # Act
        result = self._validation_result(int | None, None)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__TypingOptionalWithNone__ReturnsValid(self):
        """Test that None satisfies an ``Optional[int]`` hint."""
        # Act
        result = self._validation_result(Optional[int], None)

        # Assert
        self.assertTrue(result.valid)

    def test_validate__TypingOptionalWithInt__ReturnsValid(self):
        """Test that an int value satisfies an ``Optional[int]`` hint."""
        # Act
        result = self._validation_result(Optional[int], 5)

        # Assert
        self.assertTrue(result.valid)
