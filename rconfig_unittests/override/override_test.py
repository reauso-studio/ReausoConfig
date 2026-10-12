"""Tests for the override module."""

from enum import StrEnum
from typing import Optional
from unittest import TestCase

from rconfig.errors import InvalidOverrideSyntaxError
from rconfig.override import (
    Override,
    apply_overrides,
    extract_cli_overrides,
    parse_cli_arg,
    parse_dict_overrides,
    parse_override_key,
    parse_override_value,
)
from rconfig.override.override import (
    _should_convert_to_ref,
    apply_cli_overrides_with_ref_shorthand,
)


class ParseOverrideKeyTests(TestCase):
    def test_parse__SimpleKey__ReturnsPathAndSetOperation(self):
        path, operation = parse_override_key("model")

        self.assertEqual(path, ["model"])
        self.assertEqual(operation, "set")

    def test_parse__DottedKey__ReturnsSplitPath(self):
        path, operation = parse_override_key("model.lr")

        self.assertEqual(path, ["model", "lr"])
        self.assertEqual(operation, "set")

    def test_parse__DeepDottedKey__ReturnsSplitPath(self):
        path, operation = parse_override_key("model.optimizer.learning_rate")

        self.assertEqual(path, ["model", "optimizer", "learning_rate"])
        self.assertEqual(operation, "set")

    def test_parse__ListIndex__ReturnsIntInPath(self):
        path, operation = parse_override_key("layers[0]")

        self.assertEqual(path, ["layers", 0])
        self.assertEqual(operation, "set")

    def test_parse__ListIndexWithDot__ReturnsComplexPath(self):
        path, operation = parse_override_key("layers[0].size")

        self.assertEqual(path, ["layers", 0, "size"])
        self.assertEqual(operation, "set")

    def test_parse__MultipleListIndices__ReturnsCorrectPath(self):
        path, operation = parse_override_key("model.layers[1].weights[0]")

        self.assertEqual(path, ["model", "layers", 1, "weights", 0])
        self.assertEqual(operation, "set")

    def test_parse__AddPrefix__ReturnsAddOperation(self):
        path, operation = parse_override_key("+callbacks")

        self.assertEqual(path, ["callbacks"])
        self.assertEqual(operation, "add")

    def test_parse__AddPrefixWithDot__ReturnsAddOperation(self):
        path, operation = parse_override_key("+model.callbacks")

        self.assertEqual(path, ["model", "callbacks"])
        self.assertEqual(operation, "add")

    def test_parse__RemovePrefix__ReturnsRemoveOperation(self):
        path, operation = parse_override_key("~dropout")

        self.assertEqual(path, ["dropout"])
        self.assertEqual(operation, "remove")

    def test_parse__RemovePrefixWithDot__ReturnsRemoveOperation(self):
        path, operation = parse_override_key("~model.dropout")

        self.assertEqual(path, ["model", "dropout"])
        self.assertEqual(operation, "remove")

    def test_parse__UnderscoreInKey__Works(self):
        path, operation = parse_override_key("learning_rate")

        self.assertEqual(path, ["learning_rate"])
        self.assertEqual(operation, "set")

    def test_parse__InvalidSyntax__RaisesInvalidOverrideSyntaxError(self):
        with self.assertRaises(InvalidOverrideSyntaxError):
            parse_override_key("[invalid")

    def test_parse__EmptyString__RaisesInvalidOverrideSyntaxError(self):
        with self.assertRaises(InvalidOverrideSyntaxError):
            parse_override_key("")

    def test_parse__StartsWithNumber__RaisesInvalidOverrideSyntaxError(self):
        with self.assertRaises(InvalidOverrideSyntaxError):
            parse_override_key("123invalid")


class ParseOverrideValueTests(TestCase):
    def test_parse__IntString_NoTypeHint__ReturnsInt(self):
        result = parse_override_value("42", None)

        self.assertEqual(result, 42)
        self.assertIsInstance(result, int)

    def test_parse__NegativeIntString_NoTypeHint__ReturnsInt(self):
        result = parse_override_value("-10", None)

        self.assertEqual(result, -10)
        self.assertIsInstance(result, int)

    def test_parse__FloatString_NoTypeHint__ReturnsFloat(self):
        result = parse_override_value("0.01", None)

        self.assertEqual(result, 0.01)
        self.assertIsInstance(result, float)

    def test_parse__NegativeFloatString_NoTypeHint__ReturnsFloat(self):
        result = parse_override_value("-3.14", None)

        self.assertEqual(result, -3.14)
        self.assertIsInstance(result, float)

    def test_parse__TrueLowercase_NoTypeHint__ReturnsBoolTrue(self):
        result = parse_override_value("true", None)

        self.assertIs(result, True)

    def test_parse__FalseLowercase_NoTypeHint__ReturnsBoolFalse(self):
        result = parse_override_value("false", None)

        self.assertIs(result, False)

    def test_parse__YesLowercase_NoTypeHint__ReturnsBoolTrue(self):
        result = parse_override_value("yes", None)

        self.assertIs(result, True)

    def test_parse__NoLowercase_NoTypeHint__ReturnsBoolFalse(self):
        result = parse_override_value("no", None)

        self.assertIs(result, False)

    def test_parse__NoneLowercase_NoTypeHint__ReturnsNone(self):
        result = parse_override_value("none", None)

        self.assertIsNone(result)

    def test_parse__NullLowercase_NoTypeHint__ReturnsNone(self):
        result = parse_override_value("null", None)

        self.assertIsNone(result)

    def test_parse__RegularString_NoTypeHint__ReturnsString(self):
        result = parse_override_value("hello", None)

        self.assertEqual(result, "hello")
        self.assertIsInstance(result, str)

    def test_parse__String_WithFloatTypeHint__ReturnsFloat(self):
        result = parse_override_value("42", float)

        self.assertEqual(result, 42.0)
        self.assertIsInstance(result, float)

    def test_parse__String_WithIntTypeHint__ReturnsInt(self):
        result = parse_override_value("42", int)

        self.assertEqual(result, 42)
        self.assertIsInstance(result, int)

    def test_parse__String_WithStrTypeHint__ReturnsStr(self):
        result = parse_override_value("42", str)

        self.assertEqual(result, "42")
        self.assertIsInstance(result, str)

    def test_parse__TrueString_WithBoolTypeHint__ReturnsBool(self):
        result = parse_override_value("true", bool)

        self.assertIs(result, True)

    def test_parse__InvalidValue_WithIntTypeHint__RaisesValueError(self):
        with self.assertRaises(ValueError):
            parse_override_value("abc", int)

    def test_parse__InvalidValue_WithFloatTypeHint__RaisesValueError(self):
        with self.assertRaises(ValueError):
            parse_override_value("abc", float)

    # --- Type Coercion: None type (lines 114-117) ---
    def test_parse__ValidNoneString_WithNoneTypeHint__ReturnsNone(self):
        self.assertIsNone(parse_override_value("none", type(None)))
        self.assertIsNone(parse_override_value("null", type(None)))
        self.assertIsNone(parse_override_value("~", type(None)))

    def test_parse__InvalidValue_WithNoneTypeHint__RaisesValueError(self):
        with self.assertRaises(ValueError) as ctx:
            parse_override_value("invalid", type(None))
        self.assertIn("Cannot convert", str(ctx.exception))

    # --- Type Coercion: Bool variants (lines 121-125) ---
    def test_parse__BoolFalseVariants_WithBoolTypeHint__ReturnsFalse(self):
        for value in ("false", "no", "0", "off"):
            with self.subTest(value=value):
                result = parse_override_value(value, bool)
                self.assertIs(result, False)

    def test_parse__BoolTrueVariants_WithBoolTypeHint__ReturnsTrue(self):
        for value in ("true", "yes", "1", "on"):
            with self.subTest(value=value):
                result = parse_override_value(value, bool)
                self.assertIs(result, True)

    def test_parse__InvalidBool_WithBoolTypeHint__RaisesValueError(self):
        with self.assertRaises(ValueError) as ctx:
            parse_override_value("maybe", bool)
        self.assertIn("Cannot convert", str(ctx.exception))
        self.assertIn("bool", str(ctx.exception))

    # --- Type Coercion: List type (lines 135-136) ---
    def test_parse__YamlList_WithListTypeHint__ReturnsList(self):
        result = parse_override_value("[1, 2, 3]", list)
        self.assertEqual(result, [1, 2, 3])

    def test_parse__YamlList_WithTypedListHint__ReturnsList(self):
        result = parse_override_value("[1, 2, 3]", list[int])
        self.assertEqual(result, [1, 2, 3])

    # --- Type Coercion: Dict type (lines 138-139) ---
    def test_parse__YamlDict_WithDictTypeHint__ReturnsDict(self):
        result = parse_override_value("{key: value}", dict)
        self.assertEqual(result, {"key": "value"})

    def test_parse__YamlDict_WithTypedDictHint__ReturnsDict(self):
        result = parse_override_value("{a: 1, b: 2}", dict[str, int])
        self.assertEqual(result, {"a": 1, "b": 2})

    # --- Type Coercion: Fallback (lines 141-145) ---
    def test_parse__CustomType_WithCallableTypeHint__CallsTypeConstructor(self):
        class CustomType:
            def __init__(self, value: str):
                self.value = value

        result = parse_override_value("test", CustomType)
        self.assertIsInstance(result, CustomType)
        self.assertEqual(result.value, "test")

    def test_parse__InvalidCustomType_WithNonCallableTypeHint__RaisesValueError(self):
        class NonConstructable:
            def __init__(self, a, b, c):  # Requires multiple args
                pass

        with self.assertRaises(ValueError) as ctx:
            parse_override_value("test", NonConstructable)
        self.assertIn("Cannot convert", str(ctx.exception))

    # --- YAML Parsing auto-inference (lines 173-177) ---
    def test_parse__YamlListSyntax_NoTypeHint__ReturnsListInferred(self):
        result = parse_override_value("[1, 2, 3]", None)
        self.assertEqual(result, [1, 2, 3])

    def test_parse__YamlDictSyntax_NoTypeHint__ReturnsDictInferred(self):
        result = parse_override_value("{key: value}", None)
        self.assertEqual(result, {"key": "value"})

    def test_parse__InvalidYamlSyntax_NoTypeHint__ReturnsStringFallback(self):
        # Invalid YAML that starts with [ but can't be parsed
        result = parse_override_value("[invalid yaml", None)
        self.assertEqual(result, "[invalid yaml")

    # --- YAML Parsing error (lines 185-191) ---
    def test_parse__InvalidYaml_WithListTypeHint__RaisesValueError(self):
        with self.assertRaises(ValueError) as ctx:
            parse_override_value("[[[invalid", list)
        self.assertIn("Cannot parse YAML", str(ctx.exception))


class ParseCliArgTests(TestCase):
    def test_parse__SetOverride__ReturnsOverride(self):
        result = parse_cli_arg("model.lr=0.01")

        self.assertIsNotNone(result)
        self.assertEqual(result.path, ["model", "lr"])
        self.assertEqual(result.value, "0.01")
        self.assertEqual(result.operation, "set")

    def test_parse__AddOverride__ReturnsOverride(self):
        result = parse_cli_arg("+callbacks=logger")

        self.assertIsNotNone(result)
        self.assertEqual(result.path, ["callbacks"])
        self.assertEqual(result.value, "logger")
        self.assertEqual(result.operation, "add")

    def test_parse__RemoveOverride__ReturnsOverride(self):
        result = parse_cli_arg("~dropout")

        self.assertIsNotNone(result)
        self.assertEqual(result.path, ["dropout"])
        self.assertIsNone(result.value)
        self.assertEqual(result.operation, "remove")

    def test_parse__FlagArg__ReturnsNone(self):
        result = parse_cli_arg("--help")

        self.assertIsNone(result)

    def test_parse__ShortFlagArg__ReturnsNone(self):
        result = parse_cli_arg("-v")

        self.assertIsNone(result)

    def test_parse__PositionalArg__ReturnsNone(self):
        result = parse_cli_arg("config.yaml")

        self.assertIsNone(result)

    def test_parse__ValueWithEquals__PreservesFullValue(self):
        result = parse_cli_arg("path=/home/user=name/file")

        self.assertIsNotNone(result)
        self.assertEqual(result.path, ["path"])
        self.assertEqual(result.value, "/home/user=name/file")

    def test_parse__EmptyValue__ReturnsEmptyString(self):
        result = parse_cli_arg("key=")

        self.assertIsNotNone(result)
        self.assertEqual(result.path, ["key"])
        self.assertEqual(result.value, "")

    # --- Invalid syntax tests (lines 216-237) ---
    def test_parse__InvalidRemoveSyntax__ReturnsNone(self):
        # ~123invalid is not a valid identifier (starts with number)
        result = parse_cli_arg("~123invalid")
        self.assertIsNone(result)

    def test_parse__RemoveWithEquals__ReturnsNone(self):
        # ~key=value is invalid for remove
        result = parse_cli_arg("~key=value")
        self.assertIsNone(result)

    def test_parse__InvalidSetKeySyntax__ReturnsNone(self):
        # 123invalid=value is not valid (key starts with number)
        result = parse_cli_arg("123invalid=value")
        self.assertIsNone(result)

    def test_parse__TildeOnly__ReturnsNone(self):
        # Just ~ with no key
        result = parse_cli_arg("~")
        self.assertIsNone(result)


class ExtractCliOverridesTests(TestCase):
    def test_extract__MixedArgs__ReturnsOnlyOverrides(self):
        argv = ["--debug", "model.lr=0.01", "-v", "epochs=10"]

        result = extract_cli_overrides(argv)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].path, ["model", "lr"])
        self.assertEqual(result[1].path, ["epochs"])

    def test_extract__EmptyList__ReturnsEmpty(self):
        result = extract_cli_overrides([])

        self.assertEqual(result, [])

    def test_extract__NoOverrides__ReturnsEmpty(self):
        result = extract_cli_overrides(["--help", "-v", "config.yaml"])

        self.assertEqual(result, [])

    def test_extract__AllOverrides__ReturnsAll(self):
        argv = ["lr=0.01", "+callback=log", "~dropout"]

        result = extract_cli_overrides(argv)

        self.assertEqual(len(result), 3)


class ParseDictOverridesTests(TestCase):
    def test_parse__SimpleDict__ReturnsOverrides(self):
        result = parse_dict_overrides({"model.lr": 0.01})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path, ["model", "lr"])
        self.assertEqual(result[0].value, 0.01)
        self.assertEqual(result[0].operation, "set")

    def test_parse__MultipleKeys__ReturnsAllOverrides(self):
        result = parse_dict_overrides({
            "model.lr": 0.01,
            "epochs": 100,
        })

        self.assertEqual(len(result), 2)

    def test_parse__WithOperations__ReturnsCorrectOperations(self):
        result = parse_dict_overrides({
            "+callbacks": "logger",
            "~dropout": None,
        })

        self.assertEqual(len(result), 2)

        add_override = next(o for o in result if o.operation == "add")
        remove_override = next(o for o in result if o.operation == "remove")

        self.assertEqual(add_override.path, ["callbacks"])
        self.assertEqual(add_override.value, "logger")
        self.assertEqual(remove_override.path, ["dropout"])

    def test_parse__EmptyDict__ReturnsEmpty(self):
        result = parse_dict_overrides({})

        self.assertEqual(result, [])


class ApplyOverridesTests(TestCase):
    def test_apply__SetTopLevelValue__ModifiesConfig(self):
        config = {"lr": 0.1, "epochs": 10}
        overrides = [Override(path=["lr"], value=0.01, operation="set")]

        result = apply_overrides(config, overrides)

        self.assertEqual(result["lr"], 0.01)
        self.assertEqual(result["epochs"], 10)
        # Original unchanged
        self.assertEqual(config["lr"], 0.1)

    def test_apply__SetNestedValue__ModifiesConfig(self):
        config = {"model": {"lr": 0.1, "size": 256}}
        overrides = [Override(path=["model", "lr"], value=0.01, operation="set")]

        result = apply_overrides(config, overrides)

        self.assertEqual(result["model"]["lr"], 0.01)
        self.assertEqual(result["model"]["size"], 256)

    def test_apply__SetListElement__ModifiesConfig(self):
        config = {"layers": [{"size": 64}, {"size": 64}]}
        overrides = [Override(path=["layers", 1, "size"], value=128, operation="set")]

        result = apply_overrides(config, overrides)

        self.assertEqual(result["layers"][0]["size"], 64)
        self.assertEqual(result["layers"][1]["size"], 128)

    def test_apply__AddToExistingList__AppendsValue(self):
        config = {"callbacks": ["a", "b"]}
        overrides = [Override(path=["callbacks"], value="c", operation="add")]

        result = apply_overrides(config, overrides)

        self.assertEqual(result["callbacks"], ["a", "b", "c"])

    def test_apply__AddToNonexistentKey__CreatesList(self):
        config = {"lr": 0.01}
        overrides = [Override(path=["callbacks"], value="logger", operation="add")]

        result = apply_overrides(config, overrides)

        self.assertEqual(result["callbacks"], ["logger"])

    def test_apply__RemoveKey__DeletesKey(self):
        config = {"dropout": 0.1, "lr": 0.01}
        overrides = [Override(path=["dropout"], value=None, operation="remove")]

        result = apply_overrides(config, overrides)

        self.assertNotIn("dropout", result)
        self.assertIn("lr", result)

    def test_apply__RemoveListElement__DeletesElement(self):
        config = {"layers": [{"size": 64}, {"size": 128}, {"size": 256}]}
        overrides = [Override(path=["layers", 1], value=None, operation="remove")]

        result = apply_overrides(config, overrides)

        self.assertEqual(len(result["layers"]), 2)
        self.assertEqual(result["layers"][0]["size"], 64)
        self.assertEqual(result["layers"][1]["size"], 256)

    def test_apply__MultipleOverrides_SamePath__LastWins(self):
        config = {"lr": 0.1}
        overrides = [
            Override(path=["lr"], value=0.01, operation="set"),
            Override(path=["lr"], value=0.001, operation="set"),
        ]

        result = apply_overrides(config, overrides)

        self.assertEqual(result["lr"], 0.001)

    def test_apply__EmptyOverrides__ReturnsUnchangedCopy(self):
        config = {"lr": 0.1}

        result = apply_overrides(config, [])

        self.assertEqual(result, config)
        self.assertIsNot(result, config)

    def test_apply__InvalidPath__RaisesKeyError(self):
        config = {"lr": 0.1}
        overrides = [Override(path=["nonexistent", "key"], value=1, operation="set")]

        with self.assertRaises(KeyError):
            apply_overrides(config, overrides)

    def test_apply__ListIndexOutOfRange__RaisesKeyError(self):
        config = {"layers": [{"size": 64}]}
        overrides = [Override(path=["layers", 5, "size"], value=128, operation="set")]

        with self.assertRaises(KeyError):
            apply_overrides(config, overrides)

    def test_apply__AddToNonList__RaisesValueError(self):
        config = {"lr": 0.1}
        overrides = [Override(path=["lr"], value="x", operation="add")]

        with self.assertRaises(ValueError):
            apply_overrides(config, overrides)

    # --- Empty path (line 300-301) ---
    def test_apply__EmptyPath__NoOp(self):
        config = {"lr": 0.1}
        overrides = [Override(path=[], value=999, operation="set")]

        result = apply_overrides(config, overrides)

        # Config unchanged (empty path is a no-op)
        self.assertEqual(result, {"lr": 0.1})

    # --- Set on non-dict (line 324-325) ---
    def test_apply__SetOnNonDict__RaisesKeyError(self):
        config = {"value": "string"}
        overrides = [Override(path=["value", "nested"], value=1, operation="set")]

        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("non-dict", str(ctx.exception))

    # --- Add with list index (line 329-330) ---
    def test_apply__AddWithListIndex__RaisesValueError(self):
        config = {"items": ["a", "b", "c"]}
        overrides = [Override(path=["items", 0], value="new", operation="add")]

        with self.assertRaises(ValueError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("add operation with list index", str(ctx.exception))

    # --- Add on non-dict target (line 331-332) ---
    def test_apply__AddOnNonDictTarget__RaisesKeyError(self):
        config = {"value": "string"}
        overrides = [Override(path=["value", "key"], value="x", operation="add")]

        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("non-dict", str(ctx.exception))

    # --- Remove list index out of range (line 342-343) ---
    def test_apply__RemoveListIndexOutOfRange__RaisesKeyError(self):
        config = {"items": ["a", "b"]}
        overrides = [Override(path=["items", 99], value=None, operation="remove")]

        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("out of range", str(ctx.exception))

    # --- Remove on non-dict target (line 346-347) ---
    def test_apply__RemoveOnNonDictTarget__RaisesKeyError(self):
        config = {"value": "string"}
        overrides = [Override(path=["value", "key"], value=None, operation="remove")]

        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("non-dict", str(ctx.exception))

    # --- Remove non-existent key (line 348-349) ---
    def test_apply__RemoveNonExistentKey__RaisesKeyError(self):
        config = {"existing": 1}
        overrides = [Override(path=["nonexistent"], value=None, operation="remove")]

        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("not found for removal", str(ctx.exception))


class OverrideCoverageTests(TestCase):
    """Tests to improve override.py coverage for edge cases."""

    def test_parse_cli_arg__TildeWithEmptyKey__ReturnsNone(self):
        """Test parsing tilde with empty/invalid key returns None."""
        # Arrange - line 219
        # Act - empty key after ~
        result = parse_cli_arg("~")

        # Assert
        self.assertIsNone(result)

    def test_parse_cli_arg__TildeWithEquals__ReturnsNone(self):
        """Test parsing ~key=value (invalid remove syntax) returns None."""
        # The ~key=value is actually parsed as a valid remove in some cases
        # but ~=value should fail
        result = parse_cli_arg("~=value")

        # This should be None (invalid key syntax)
        self.assertIsNone(result)

    def test_apply_single_override__SetListIndex__UpdatesItem(self):
        """Test setting a list item by index."""
        # Arrange - lines 320-322
        config = {"items": ["a", "b", "c"]}
        override = Override(path=["items", 1], value="updated", operation="set")

        # Act - apply_overrides returns a new dict
        result = apply_overrides(config, [override])

        # Assert - the result should have the updated value
        self.assertEqual(result["items"][1], "updated")

    def test_apply_single_override__SetListIndexOutOfRange__RaisesKeyError(self):
        """Test setting a list item with out of range index."""
        # Arrange - lines 320-321
        config = {"items": ["a", "b"]}
        override = Override(path=["items", 99], value="x", operation="set")

        # Act & Assert
        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, [override])
        self.assertIn("out of range", str(ctx.exception))


class OverrideDataclassTests(TestCase):
    """Tests for Override dataclass fields."""

    def test_Override__DefaultSourceType__IsProgrammatic(self):
        """Test that default source_type is 'programmatic'."""
        # Act
        override = Override(path=["test"], value=42, operation="set")

        # Assert
        self.assertEqual("programmatic", override.source_type)

    def test_Override__DefaultCliArg__IsNone(self):
        """Test that default cli_arg is None."""
        # Act
        override = Override(path=["test"], value=42, operation="set")

        # Assert
        self.assertIsNone(override.cli_arg)

    def test_Override__AllFieldsSet__StoresCorrectly(self):
        """Test that all fields are stored correctly when set."""
        # Act
        override = Override(
            path=["model", "lr"],
            value=0.01,
            operation="set",
            source_type="cli",
            cli_arg="model.lr=0.01",
        )

        # Assert
        self.assertEqual(["model", "lr"], override.path)
        self.assertEqual(0.01, override.value)
        self.assertEqual("set", override.operation)
        self.assertEqual("cli", override.source_type)
        self.assertEqual("model.lr=0.01", override.cli_arg)


class ParseCliArgSourceTypeTests(TestCase):
    """Tests for CLI argument parsing with source tracking."""

    def test_parseCliArg__SetOverride__SetsCliSourceType(self):
        """Test that set overrides get 'cli' source type."""
        # Act
        result = parse_cli_arg("model.lr=0.01")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual("cli", result.source_type)

    def test_parseCliArg__AddOverride__SetsCliSourceType(self):
        """Test that add overrides get 'cli' source type."""
        # Act
        result = parse_cli_arg("+callbacks=logger")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual("cli", result.source_type)

    def test_parseCliArg__RemoveOverride__SetsCliSourceType(self):
        """Test that remove overrides get 'cli' source type."""
        # Act
        result = parse_cli_arg("~dropout")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual("cli", result.source_type)

    def test_parseCliArg__SetOverride__StoresCliArg(self):
        """Test that the original CLI argument string is stored."""
        # Act
        result = parse_cli_arg("model.lr=0.01")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual("model.lr=0.01", result.cli_arg)


class ParseDictOverridesSourceTypeTests(TestCase):
    """Tests for dict override parsing with source tracking."""

    def test_parseDictOverrides__SimpleDict__SetsProgrammaticSourceType(self):
        """Test that dict overrides get 'programmatic' source type."""
        # Act
        result = parse_dict_overrides({"model.lr": 0.01})

        # Assert
        self.assertEqual(1, len(result))
        self.assertEqual("programmatic", result[0].source_type)

    def test_parseDictOverrides__SimpleDict__CliArgIsNone(self):
        """Test that dict overrides have None cli_arg."""
        # Act
        result = parse_dict_overrides({"model.lr": 0.01})

        # Assert
        self.assertEqual(1, len(result))
        self.assertIsNone(result[0].cli_arg)


class UpdateProvenanceForOverrideTests(TestCase):
    """Tests for _update_provenance_for_override function."""

    def test_updateProvenance__CliOverride__SetsCliSourceType(self):
        """Test that CLI override sets cli source type in provenance."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()
        builder.add("model.lr", file="config.yaml", line=5, value=0.001)
        override = Override(
            path=["model", "lr"],
            value=0.01,
            operation="set",
            source_type=EntrySourceType.CLI,
            cli_arg="model.lr=0.01",
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("model.lr")
        self.assertEqual("cli", entry.source_type)
        self.assertEqual("model.lr=0.01", entry.cli_arg)

    def test_updateProvenance__ProgrammaticOverride__SetsProgrammaticType(self):
        """Test that programmatic override sets programmatic source type."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()
        builder.add("model.epochs", file="config.yaml", line=6, value=100)
        override = Override(
            path=["model", "epochs"],
            value=200,
            operation="set",
            source_type=EntrySourceType.PROGRAMMATIC,
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("model.epochs")
        self.assertEqual("programmatic", entry.source_type)
        self.assertIsNone(entry.cli_arg)

    def test_updateProvenance__ExistingEntry__RecordsOverrode(self):
        """Test that overriding existing entry records what was overridden."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()
        builder.add("model.lr", file="config.yaml", line=5, value=0.001)
        override = Override(
            path=["model", "lr"],
            value=0.01,
            operation="set",
            source_type=EntrySourceType.CLI,
            cli_arg="model.lr=0.01",
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("model.lr")
        self.assertEqual("config.yaml:5", entry.overrode)

    def test_updateProvenance__NewPath__NoOverrode(self):
        """Test that new path has no overrode field."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()  # Empty builder
        override = Override(
            path=["new", "path"],
            value=42,
            operation="set",
            source_type=EntrySourceType.CLI,
            cli_arg="new.path=42",
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("new.path")
        self.assertIsNone(entry.overrode)

    def test_updateProvenance__SetsValue(self):
        """Test that override value is stored in provenance entry."""
        # Arrange
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()
        builder.add("test", file="config.yaml", line=1)
        override = Override(
            path=["test"],
            value="new_value",
            operation="set",
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("test")
        self.assertEqual("new_value", entry.value)

    def test_updateProvenance__CliArg__OnlyForCliType(self):
        """Test that cli_arg is only set for cli source type."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()
        builder.add("test", file="config.yaml", line=1)
        override = Override(
            path=["test"],
            value=42,
            operation="set",
            source_type=EntrySourceType.CLI,
            cli_arg="test=42",
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("test")
        self.assertEqual("test=42", entry.cli_arg)

    def test_updateProvenance__ProgrammaticArg__CliArgIsNone(self):
        """Test that programmatic override has None cli_arg."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder
        from rconfig.override.override import _update_provenance_for_override

        builder = ProvenanceBuilder()
        builder.add("test", file="config.yaml", line=1)
        override = Override(
            path=["test"],
            value=42,
            operation="set",
            source_type=EntrySourceType.PROGRAMMATIC,
        )

        # Act
        _update_provenance_for_override(builder, override)

        # Assert
        entry = builder.get("test")
        self.assertIsNone(entry.cli_arg)


class ApplyOverridesWithProvenanceTests(TestCase):
    """Tests for apply_overrides with provenance tracking."""

    def test_applyOverrides__SetOperation__UpdatesProvenance(self):
        """Test that set operation updates provenance."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder

        builder = ProvenanceBuilder()
        builder.add("model.lr", file="config.yaml", line=5, value=0.001)
        config = {"model": {"lr": 0.001}}
        overrides = [
            Override(
                path=["model", "lr"],
                value=0.01,
                operation="set",
                source_type=EntrySourceType.CLI,
                cli_arg="model.lr=0.01",
            )
        ]

        # Act
        apply_overrides(config, overrides, builder)

        # Assert
        entry = builder.get("model.lr")
        self.assertEqual("cli", entry.source_type)
        self.assertEqual(0.01, entry.value)

    def test_applyOverrides__AddOperation__NoProvenanceUpdate(self):
        """Test that add operation doesn't crash with provenance."""
        # Arrange
        from rconfig.provenance import ProvenanceBuilder

        builder = ProvenanceBuilder()
        builder.add("callbacks", file="config.yaml", line=5)
        config = {"callbacks": ["a"]}
        overrides = [
            Override(
                path=["callbacks"],
                value="b",
                operation="add",
            )
        ]

        # Act - should not raise
        result = apply_overrides(config, overrides, builder)

        # Assert
        self.assertEqual(["a", "b"], result["callbacks"])

    def test_applyOverrides__RemoveOperation__NoProvenanceUpdate(self):
        """Test that remove operation doesn't crash with provenance."""
        # Arrange
        from rconfig.provenance import ProvenanceBuilder

        builder = ProvenanceBuilder()
        builder.add("dropout", file="config.yaml", line=5, value=0.1)
        config = {"dropout": 0.1, "lr": 0.01}
        overrides = [
            Override(
                path=["dropout"],
                value=None,
                operation="remove",
            )
        ]

        # Act - should not raise
        result = apply_overrides(config, overrides, builder)

        # Assert
        self.assertNotIn("dropout", result)

    def test_applyOverrides__NoProvenance__SkipsUpdate(self):
        """Test that passing None provenance works without error."""
        # Arrange
        config = {"lr": 0.1}
        overrides = [Override(path=["lr"], value=0.01, operation="set")]

        # Act - should not raise
        result = apply_overrides(config, overrides, None)

        # Assert
        self.assertEqual(0.01, result["lr"])

    def test_applyOverrides__MultipleOverrides__AllTracked(self):
        """Test that multiple overrides are all tracked in provenance."""
        # Arrange
        from rconfig.composition import EntrySourceType
        from rconfig.provenance import ProvenanceBuilder

        builder = ProvenanceBuilder()
        builder.add("model.lr", file="config.yaml", line=5)
        builder.add("model.epochs", file="config.yaml", line=6)
        config = {"model": {"lr": 0.1, "epochs": 10}}
        overrides = [
            Override(
                path=["model", "lr"],
                value=0.01,
                operation="set",
                source_type=EntrySourceType.CLI,
                cli_arg="model.lr=0.01",
            ),
            Override(
                path=["model", "epochs"],
                value=100,
                operation="set",
                source_type=EntrySourceType.CLI,
                cli_arg="model.epochs=100",
            ),
        ]

        # Act
        apply_overrides(config, overrides, builder)

        # Assert
        lr_entry = builder.get("model.lr")
        epochs_entry = builder.get("model.epochs")
        self.assertEqual("cli", lr_entry.source_type)
        self.assertEqual("cli", epochs_entry.source_type)
        self.assertEqual(0.01, lr_entry.value)
        self.assertEqual(100, epochs_entry.value)


class ApplyOverridesNonListTests(TestCase):
    """Tests for override operations on non-list types with integer indices."""

    def test_apply__SetIndexOnNonList__RaisesKeyError(self):
        """Test that setting an index on a non-list raises KeyError."""
        # Arrange
        config = {"value": "string"}  # Not a list
        overrides = [Override(path=["value", 0], value="new", operation="set")]

        # Act & Assert
        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("non-list", str(ctx.exception))

    def test_apply__RemoveIndexOnNonList__RaisesKeyError(self):
        """Test that removing an index from a non-list raises KeyError."""
        # Arrange
        config = {"value": "string"}  # Not a list
        overrides = [Override(path=["value", 0], value=None, operation="remove")]

        # Act & Assert
        with self.assertRaises(KeyError) as ctx:
            apply_overrides(config, overrides)
        self.assertIn("non-list", str(ctx.exception))


class ShouldConvertToRefTests(TestCase):
    """Tests for _should_convert_to_ref function."""

    def test__TargetIsDict__ReturnsTrue(self):
        """Test that dict fields return True."""
        config = {"model": {"_target_": "resnet"}}

        result = _should_convert_to_ref(["model"], config)

        self.assertTrue(result)

    def test__TargetIsString__ReturnsFalse(self):
        """Test that string fields return False."""
        config = {"name": "experiment_1"}

        result = _should_convert_to_ref(["name"], config)

        self.assertFalse(result)

    def test__TargetIsInt__ReturnsFalse(self):
        """Test that int fields return False."""
        config = {"epochs": 100}

        result = _should_convert_to_ref(["epochs"], config)

        self.assertFalse(result)

    def test__TargetIsList__ReturnsFalse(self):
        """Test that list fields return False."""
        config = {"callbacks": ["logger", "checkpoint"]}

        result = _should_convert_to_ref(["callbacks"], config)

        self.assertFalse(result)

    def test__TargetDoesNotExist__ReturnsFalse(self):
        """Test that non-existent fields return False."""
        config = {"model": {"_target_": "resnet"}}

        result = _should_convert_to_ref(["new_field"], config)

        self.assertFalse(result)

    def test__NestedDictTarget__ReturnsTrue(self):
        """Test that nested dict fields return True."""
        config = {"trainer": {"model": {"_target_": "resnet"}}}

        result = _should_convert_to_ref(["trainer", "model"], config)

        self.assertTrue(result)

    def test__EmptyDict__ReturnsTrue(self):
        """Test that empty dict fields return True."""
        config = {"model": {}}

        result = _should_convert_to_ref(["model"], config)

        self.assertTrue(result)

    def test__DictWithRef__ReturnsTrue(self):
        """Test that dict fields with _ref_ return True."""
        config = {"model": {"_ref_": "models/resnet.yaml"}}

        result = _should_convert_to_ref(["model"], config)

        self.assertTrue(result)

    def test__NestedPathDoesNotExist__ReturnsFalse(self):
        """Test that nested non-existent paths return False."""
        config = {"model": {"_target_": "resnet"}}

        result = _should_convert_to_ref(["model", "nonexistent"], config)

        self.assertFalse(result)

    def test__ListIndex__ReturnsFalse(self):
        """Test that list indices return False (list element is not dict)."""
        config = {"items": [1, 2, 3]}

        result = _should_convert_to_ref(["items", 0], config)

        self.assertFalse(result)

    def test__ListOfDicts__ElementIsDict__ReturnsTrue(self):
        """Test that dict elements in lists return True."""
        config = {"layers": [{"size": 64}, {"size": 128}]}

        result = _should_convert_to_ref(["layers", 0], config)

        self.assertTrue(result)


class ParseCliArgQuotedValueTests(TestCase):
    """Tests for parse_cli_arg with quoted values."""

    def test_parse__DoubleQuotedValue__StripsQuotesAndSetsLiteral(self):
        """Test that double-quoted values are stripped and marked literal."""
        result = parse_cli_arg('model="models/vit.yaml"')

        self.assertIsNotNone(result)
        self.assertEqual(result.value, "models/vit.yaml")
        self.assertTrue(result.is_literal)

    def test_parse__SingleQuotedValue__StripsQuotesAndSetsLiteral(self):
        """Test that single-quoted values are stripped and marked literal."""
        result = parse_cli_arg("model='models/vit.yaml'")

        self.assertIsNotNone(result)
        self.assertEqual(result.value, "models/vit.yaml")
        self.assertTrue(result.is_literal)

    def test_parse__UnquotedValue__NotLiteral(self):
        """Test that unquoted values are not marked literal."""
        result = parse_cli_arg("model=models/vit.yaml")

        self.assertIsNotNone(result)
        self.assertEqual(result.value, "models/vit.yaml")
        self.assertFalse(result.is_literal)

    def test_parse__PartiallyQuotedStart__NotLiteral(self):
        """Test that values with only start quote are not stripped."""
        result = parse_cli_arg('model="models/vit.yaml')

        self.assertIsNotNone(result)
        self.assertEqual(result.value, '"models/vit.yaml')
        self.assertFalse(result.is_literal)

    def test_parse__PartiallyQuotedEnd__NotLiteral(self):
        """Test that values with only end quote are not stripped."""
        result = parse_cli_arg('model=models/vit.yaml"')

        self.assertIsNotNone(result)
        self.assertEqual(result.value, 'models/vit.yaml"')
        self.assertFalse(result.is_literal)

    def test_parse__EmptyQuotedValue__StripsQuotes(self):
        """Test that empty quoted values work."""
        result = parse_cli_arg('name=""')

        self.assertIsNotNone(result)
        self.assertEqual(result.value, "")
        self.assertTrue(result.is_literal)


class ApplyCliOverridesWithRefShorthandTests(TestCase):
    """Tests for apply_cli_overrides_with_ref_shorthand function."""

    def test_apply__DictField_UnquotedValue__ConvertsToRef(self):
        """Test that unquoted value on dict field converts to _ref_."""
        config = {"model": {"_target_": "resnet"}}
        overrides = [
            Override(
                path=["model"],
                value="models/vit.yaml",
                operation="set",
                source_type="cli",
                cli_arg="model=models/vit.yaml",
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["model"]["_ref_"], "models/vit.yaml")
        # Original dict keys should still exist (will be overwritten by _ref_ processing)
        self.assertIn("_target_", result["model"])

    def test_apply__StringField_UnquotedValue__NoConversion(self):
        """Test that unquoted value on string field is set directly."""
        config = {"name": "experiment_1"}
        overrides = [
            Override(
                path=["name"],
                value="models/vit.yaml",
                operation="set",
                source_type="cli",
                cli_arg="name=models/vit.yaml",
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["name"], "models/vit.yaml")

    def test_apply__DictField_QuotedValue__NoConversion(self):
        """Test that quoted value on dict field is set directly (replaces dict)."""
        config = {"model": {"_target_": "resnet"}}
        overrides = [
            Override(
                path=["model"],
                value="models/vit.yaml",
                operation="set",
                source_type="cli",
                cli_arg='model="models/vit.yaml"',
                is_literal=True,  # Quoted
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["model"], "models/vit.yaml")

    def test_apply__NewField__NoConversion(self):
        """Test that new field assignment doesn't convert to _ref_."""
        config = {"model": {"_target_": "resnet"}}
        overrides = [
            Override(
                path=["new_field"],
                value="models/vit.yaml",
                operation="set",
                source_type="cli",
                cli_arg="new_field=models/vit.yaml",
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["new_field"], "models/vit.yaml")

    def test_apply__NestedDictField__ConvertsToRef(self):
        """Test that nested dict field converts to _ref_."""
        config = {"trainer": {"model": {"_target_": "resnet"}}}
        overrides = [
            Override(
                path=["trainer", "model"],
                value="models/vit.yaml",
                operation="set",
                source_type="cli",
                cli_arg="trainer.model=models/vit.yaml",
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["trainer"]["model"]["_ref_"], "models/vit.yaml")

    def test_apply__ProgrammaticOverride__NoConversion(self):
        """Test that programmatic overrides don't convert to _ref_."""
        config = {"model": {"_target_": "resnet"}}
        overrides = [
            Override(
                path=["model"],
                value="models/vit.yaml",
                operation="set",
                source_type="programmatic",  # Not CLI
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        # Should set model directly, not convert to _ref_
        self.assertEqual(result["model"], "models/vit.yaml")

    def test_apply__AddOperation__NoConversion(self):
        """Test that add operations don't convert to _ref_."""
        config = {"callbacks": ["logger"]}
        overrides = [
            Override(
                path=["callbacks"],
                value="models/vit.yaml",
                operation="add",  # Not set
                source_type="cli",
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["callbacks"], ["logger", "models/vit.yaml"])

    def test_apply__NonStringValue__NoConversion(self):
        """Test that non-string values don't convert to _ref_."""
        config = {"model": {"_target_": "resnet"}}
        overrides = [
            Override(
                path=["model"],
                value={"_target_": "vit"},  # Dict, not string
                operation="set",
                source_type="cli",
                is_literal=False,
            )
        ]

        result = apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(result["model"], {"_target_": "vit"})

    def test_apply__OriginalConfigUnchanged(self):
        """Test that original config is not modified."""
        config = {"model": {"_target_": "resnet"}}
        overrides = [
            Override(
                path=["model"],
                value="models/vit.yaml",
                operation="set",
                source_type="cli",
                is_literal=False,
            )
        ]

        apply_cli_overrides_with_ref_shorthand(config, overrides)

        self.assertEqual(config, {"model": {"_target_": "resnet"}})


class LogLevel(StrEnum):
    """Enum used to test coercion of string values to enum members."""

    DEBUG = "DEBUG"
    INFO = "INFO"


class ParseOverrideValueTypeCoercionTests(TestCase):
    """Tests for coercing override strings to union, list and enum type hints."""

    def test_parse__Pep604OptionalIntWithInt__ReturnsInt(self):
        """Test that '5' is coerced to int for an ``int | None`` hint."""
        # Act
        result = parse_override_value("5", int | None)

        # Assert
        self.assertEqual(result, 5)
        self.assertIsInstance(result, int)

    def test_parse__Pep604OptionalIntWithNoneToken__ReturnsNone(self):
        """Test that 'none' is coerced to None for an ``int | None`` hint."""
        # Act
        result = parse_override_value("none", int | None)

        # Assert
        self.assertIsNone(result)

    def test_parse__TypingOptionalIntWithInt__ReturnsInt(self):
        """Test that '5' is coerced to int for an ``Optional[int]`` hint."""
        # Act
        result = parse_override_value("5", Optional[int])

        # Assert
        self.assertEqual(result, 5)
        self.assertIsInstance(result, int)

    def test_parse__ListOfStrWithCommaSeparatedValue__KeepsString(self):
        """Test that CLI overrides do not split 'a, b'; use '[a, b]' for lists.

        Comma-separated values are sweeps in multirun, so overrides keep YAML
        list syntax. The string is left for validation to reject.
        """
        # Act
        result = parse_override_value("localhost, 127.0.0.1", list[str])

        # Assert
        self.assertEqual(result, "localhost, 127.0.0.1")

    def test_parse__IntWithInterpolation__ReturnsRawForLaterCoercion(self):
        """Test that interpolations are kept as-is and coerced after resolution."""
        # Act
        result = parse_override_value("${env:PORT}", int)

        # Assert
        self.assertEqual(result, "${env:PORT}")

    def test_parse__ListOfStrWithYamlNumbers__ReturnsStrItems(self):
        """Test that '[1, 2]' yields string elements for a ``list[str]`` hint."""
        # Act
        result = parse_override_value("[1, 2]", list[str])

        # Assert
        self.assertEqual(result, ["1", "2"])

    def test_parse__ListOfStrWithYamlList__ReturnsList(self):
        """Test that a YAML list literal is parsed for a ``list[str]`` hint."""
        # Act
        result = parse_override_value("[localhost, example.com]", list[str])

        # Assert
        self.assertEqual(result, ["localhost", "example.com"])

    def test_parse__StrEnumWithValidValue__ReturnsMember(self):
        """Test that a valid value is coerced to the enum member."""
        # Act
        result = parse_override_value("INFO", LogLevel)

        # Assert
        self.assertIs(result, LogLevel.INFO)

    def test_parse__StrEnumWithInvalidValue__ErrorListsValidMembers(self):
        """Test that an invalid enum value names the valid members."""
        # Act & Assert
        with self.assertRaises(ValueError) as ctx:
            parse_override_value("VERBOSE", LogLevel)

        self.assertIn("DEBUG", str(ctx.exception))
        self.assertIn("INFO", str(ctx.exception))

    def test_parse__BoolWithFalsyTokens__ReturnsFalse(self):
        """Test that all documented falsy tokens are coerced to False."""
        for token in ("False", "false", "FALSE", "0", "no", "off"):
            with self.subTest(token=token):
                # Act
                result = parse_override_value(token, bool)

                # Assert
                self.assertIs(result, False)

    def test_parse__BoolWithTruthyTokens__ReturnsTrue(self):
        """Test that all documented truthy tokens are coerced to True."""
        for token in ("True", "true", "TRUE", "1", "yes", "on"):
            with self.subTest(token=token):
                # Act
                result = parse_override_value(token, bool)

                # Assert
                self.assertIs(result, True)

    def test_parse__BoolWithTypo__RaisesValueError(self):
        """Test that an unrecognised boolean token raises instead of reading as False."""
        # Act & Assert
        with self.assertRaises(ValueError):
            parse_override_value("ture", bool)