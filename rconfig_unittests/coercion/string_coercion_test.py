"""Unit tests for coerced_value()."""

from enum import Enum, IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, Any, NewType, Optional, TypeVar, Union
from unittest import TestCase

from rconfig.coercion import coerced_value


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


class Color(Enum):
    RED = "red"
    BLUE = "blue"


Port = NewType("Port", int)
T = TypeVar("T")


class CoercedValuePassThroughTests(TestCase):
    """Hints that accept any string leave it unchanged."""

    def test_coercedValue__StrAnyObjectTypeVarOrNoHint__ReturnsRawString(self):
        """Test that str, Any, object, TypeVar and None hints keep the string."""
        for hint in (str, Any, object, T, None):
            with self.subTest(hint=hint):
                # Act
                result = coerced_value("false", hint)

                # Assert
                self.assertEqual(result, "false")

    def test_coercedValue__UnknownClassWithoutConstruct__ReturnsRawString(self):
        """Test that other classes are left to the validator by default."""
        # Act
        result = coerced_value("x", bytes)

        # Assert
        self.assertEqual(result, "x")

    def test_coercedValue__UnknownClassWithConstruct__CallsClass(self):
        """Test that construct_unknown calls the class with the raw string."""
        # Act
        result = coerced_value("3", complex, construct_unknown=True)

        # Assert
        self.assertEqual(result, complex(3))


class CoercedValueScalarTests(TestCase):
    """Tests for bool, int, float, None and path hints."""

    def test_coercedValue__BoolTokensWithWhitespaceAndCase__ReturnsBool(self):
        """Test that bool tokens are case-insensitive and stripped."""
        # Act & Assert
        self.assertIs(coerced_value(" ON ", bool), True)
        self.assertIs(coerced_value("Off", bool), False)

    def test_coercedValue__BoolTypo__RaisesValueErrorListingTokens(self):
        """Test that an unknown bool token raises and lists the accepted tokens."""
        # Act & Assert
        with self.assertRaises(ValueError) as ctx:
            coerced_value("ture", bool)

        self.assertIn("true", str(ctx.exception))

    def test_coercedValue__IntAndFloat__ReturnsNumbers(self):
        """Test int and float conversion."""
        # Act & Assert
        self.assertEqual(coerced_value("42", int), 42)
        self.assertEqual(coerced_value("0.5", float), 0.5)

    def test_coercedValue__InvalidInt__RaisesValueError(self):
        """Test that a non-numeric string raises for an int hint."""
        # Act & Assert
        with self.assertRaises(ValueError):
            coerced_value("eighty", int)

    def test_coercedValue__NoneTypeWithNullToken__ReturnsNone(self):
        """Test none-tokens for a NoneType hint."""
        # Act & Assert
        self.assertIsNone(coerced_value("null", type(None)))

    def test_coercedValue__PathHint__ReturnsPath(self):
        """Test that path hints produce Path objects."""
        # Act
        result = coerced_value("/data", Path)

        # Assert
        self.assertEqual(result, Path("/data"))

    def test_coercedValue__AnnotatedAndNewType__UnwrapsToBaseType(self):
        """Test that Annotated and NewType wrappers are unwrapped."""
        # Act & Assert
        self.assertEqual(coerced_value("8080", Port), 8080)
        self.assertEqual(coerced_value("8080", Annotated[int, "port"]), 8080)


class CoercedValueEnumTests(TestCase):
    """Tests for enum hints."""

    def test_coercedValue__StrEnumValue__ReturnsMember(self):
        """Test matching by value."""
        # Act & Assert
        self.assertIs(coerced_value("INFO", LogLevel), LogLevel.INFO)

    def test_coercedValue__EnumName__ReturnsMember(self):
        """Test matching by name when no value matches."""
        # Act & Assert
        self.assertIs(coerced_value("RED", Color), Color.RED)

    def test_coercedValue__IntEnumValueAsString__ReturnsMember(self):
        """Test that an IntEnum matches the string form of its value."""
        # Act & Assert
        self.assertIs(coerced_value("2", Priority), Priority.HIGH)

    def test_coercedValue__InvalidEnumValue__RaisesListingValues(self):
        """Test that the error lists the valid values."""
        # Act & Assert
        with self.assertRaises(ValueError) as ctx:
            coerced_value("green", Color)

        self.assertIn("red, blue", str(ctx.exception))


class CoercedValueUnionTests(TestCase):
    """Tests for union hints in both spellings."""

    def test_coercedValue__OptionalBothSpellings__ConvertsToMember(self):
        """Test Optional[int] and int | None."""
        for hint in (Optional[int], int | None):
            with self.subTest(hint=hint):
                # Act & Assert
                self.assertEqual(coerced_value("5", hint), 5)
                self.assertIsNone(coerced_value("none", hint))

    def test_coercedValue__UnionWithStr__KeepsString(self):
        """Test that a union including str keeps numeric-looking strings."""
        # Act & Assert
        self.assertEqual(coerced_value("5", str | None), "5")
        self.assertEqual(coerced_value("5", Union[int, str]), "5")

    def test_coercedValue__UnionMembers__TriesInOrder(self):
        """Test that the first member accepting the string wins."""
        # Act & Assert
        self.assertEqual(coerced_value("5", int | float), 5)
        self.assertEqual(coerced_value("0.5", int | float), 0.5)

    def test_coercedValue__NoMemberAccepts__RaisesValueError(self):
        """Test that a union raises when every member rejects the string."""
        # Act & Assert
        with self.assertRaises(ValueError):
            coerced_value("abc", int | float)


class CoercedValueSequenceTests(TestCase):
    """Tests for list-like hints."""

    def test_coercedValue__CommaSeparatedWithSplit__ReturnsStrippedItems(self):
        """Test that split_lists splits, strips and drops empty items."""
        # Act
        result = coerced_value("localhost, 127.0.0.1, ", list[str], split_lists=True)

        # Assert
        self.assertEqual(result, ["localhost", "127.0.0.1"])

    def test_coercedValue__CommaSeparatedIntsWithSplit__CoercesItems(self):
        """Test that split items are coerced to the element type."""
        # Act
        result = coerced_value("1, 2", list[int], split_lists=True)

        # Assert
        self.assertEqual(result, [1, 2])

    def test_coercedValue__SingleValueWithSplit__ReturnsOneItemList(self):
        """Test that a single value becomes a one-item list."""
        # Act
        result = coerced_value("localhost", list[str], split_lists=True)

        # Assert
        self.assertEqual(result, ["localhost"])

    def test_coercedValue__YamlListForStrItems__KeepsItemsAsStrings(self):
        """Test that YAML list items stay strings for list[str]."""
        # Act
        result = coerced_value("[1, true]", list[str], split_lists=True)

        # Assert
        self.assertEqual(result, ["1", "true"])

    def test_coercedValue__NestedYamlList__CoercesNestedItems(self):
        """Test that nested lists are coerced to nested element types."""
        # Act
        result = coerced_value("[[1, 2], [3]]", list[list[int]])

        # Assert
        self.assertEqual(result, [[1, 2], [3]])

    def test_coercedValue__UntypedListYaml__KeepsYamlTypes(self):
        """Test that a bare list hint keeps YAML-inferred item types."""
        # Act
        result = coerced_value("[1, x]", list)

        # Assert
        self.assertEqual(result, [1, "x"])

    def test_coercedValue__VariadicTuple__ReturnsListOfElementType(self):
        """Test tuple[int, ...] (YAML has no tuples, so a list is returned)."""
        # Act
        result = coerced_value("4, 5", tuple[int, ...], split_lists=True)

        # Assert
        self.assertEqual(result, [4, 5])

    def test_coercedValue__InvalidItem__RaisesValueError(self):
        """Test that an unconvertible item raises."""
        # Act & Assert
        with self.assertRaises(ValueError):
            coerced_value("1, x", list[int], split_lists=True)
