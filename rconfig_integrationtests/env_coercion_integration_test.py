"""Integration tests for coercing environment variable values to declared field types.

``${env:VAR}`` yields a raw string from the environment. After interpolation, string
values are converted to the type their field declares, the same way CLI overrides
are. These tests cover that conversion through the public API.
"""

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest.mock import patch

import rconfig as rc
from rconfig.errors import ConfigError


# Path to env coercion config files directory
CONFIG_DIR = Path(__file__).parent / "config_files" / "env_coercion"

# Prefix of every env var used by these tests
ENV_PREFIX = "RCT_"


# =============================================================================
# Test Dataclasses
# =============================================================================


class LogLevel(StrEnum):
    """Log level enum for enum coercion tests."""

    DEBUG = "DEBUG"
    INFO = "INFO"


@dataclass
class EnvScalars:
    """Dataclass with scalar fields fed from env vars."""

    debug: bool
    port: int
    ratio: float
    name: str


@dataclass
class EnvShapes:
    """Dataclass for env expressions without a default and with ``??``."""

    bare_port: int
    coalesce_port: int


@dataclass
class EnvEnum:
    """Dataclass with an enum field fed from an env var."""

    level: LogLevel


@dataclass
class EnvLists:
    """Dataclass with a list field fed from an env var."""

    hosts: list[str]


@dataclass
class EnvOptional:
    """Dataclass with optional fields fed from env vars."""

    timeout: int | None
    label: str | None


@dataclass
class EnvLiterals:
    """Dataclass with fields whose values must never be coerced."""

    flag_text: str
    path: str
    untyped: dict


@dataclass
class EnvAny:
    """Dataclass with a field typed Any."""

    anything: Any


@dataclass
class EnvServer:
    """Nested dataclass with an env-sourced field."""

    port: int


@dataclass
class EnvNested:
    """Dataclass containing a nested dataclass."""

    server: EnvServer


@dataclass
class EnvListElement:
    """Dataclass with an env-sourced list element."""

    ports: list[int]


@dataclass
class EnvChained:
    """Dataclass with a config reference to an env-sourced value."""

    base_port: int
    derived_port: int


# =============================================================================
# Test Base
# =============================================================================


class EnvCoercionTestBase(TestCase):
    """Base class registering all targets and isolating the environment."""

    def setUp(self) -> None:
        rc._store._known_targets.clear()
        rc.register("env_scalars", EnvScalars)
        rc.register("env_shapes", EnvShapes)
        rc.register("env_enum", EnvEnum)
        rc.register("env_lists", EnvLists)
        rc.register("env_optional", EnvOptional)
        rc.register("env_literals", EnvLiterals)
        rc.register("env_any", EnvAny)
        rc.register("env_server", EnvServer)
        rc.register("env_nested", EnvNested)
        rc.register("env_list_element", EnvListElement)
        rc.register("env_chained", EnvChained)
        clean_env = {key: value for key, value in os.environ.items() if not key.startswith(ENV_PREFIX)}
        self._env_patch = patch.dict(os.environ, clean_env, clear=True)
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def _instantiate(self, file_name: str, **env: str) -> Any:
        """Instantiate a fixture file with the given env vars set."""
        os.environ.update(env)
        return rc.instantiate(CONFIG_DIR / file_name, cli_overrides=False)


# =============================================================================
# Scalar Coercion
# =============================================================================


class EnvBoolCoercionIntegrationTests(EnvCoercionTestBase):
    """Tests for env values reaching bool fields."""

    def test_instantiate__BoolEnvUnset__UsesTypedLiteralDefault(self) -> None:
        """Test that an unset env var yields the literal default with its type."""
        # Act
        result = self._instantiate("scalars.yaml")

        # Assert
        self.assertIs(result.debug, False)

    def test_instantiate__BoolEnvFalsyTokens__ReturnsFalse(self) -> None:
        """Test that set-but-false env tokens yield a real False."""
        for token in ("False", "false", "FALSE", "0", "no", "off"):
            # Act
            result = self._instantiate("scalars.yaml", RCT_DEBUG=token)

            # Assert
            self.assertIs(result.debug, False, token)

    def test_instantiate__BoolEnvTruthyTokens__ReturnsTrue(self) -> None:
        """Test that true-ish env tokens yield a real True."""
        for token in ("True", "true", "TRUE", "1", "yes", "on"):
            # Act
            result = self._instantiate("scalars.yaml", RCT_DEBUG=token)

            # Assert
            self.assertIs(result.debug, True, token)

    def test_instantiate__BoolEnvTypo__RaisesErrorNamingVariable(self) -> None:
        """Test that an unrecognised boolean token raises and names the env var."""
        # Act & Assert
        with self.assertRaises(ConfigError) as ctx:
            self._instantiate("scalars.yaml", RCT_DEBUG="ture")

        self.assertIn("RCT_DEBUG", str(ctx.exception))


class EnvNumericCoercionIntegrationTests(EnvCoercionTestBase):
    """Tests for env values reaching int and float fields."""

    def test_instantiate__NumericEnvUnset__UsesTypedLiteralDefaults(self) -> None:
        """Test that unset env vars yield int and float literal defaults."""
        # Act
        result = self._instantiate("scalars.yaml")

        # Assert
        self.assertEqual(result.port, 8080)
        self.assertIsInstance(result.port, int)
        self.assertEqual(result.ratio, 0.5)

    def test_instantiate__IntEnvSet__ReturnsInt(self) -> None:
        """Test that an int field receives an int from the environment."""
        # Act
        result = self._instantiate("scalars.yaml", RCT_PORT="9000")

        # Assert
        self.assertEqual(result.port, 9000)

    def test_instantiate__FloatEnvSet__ReturnsFloat(self) -> None:
        """Test that a float field receives a float from the environment."""
        # Act
        result = self._instantiate("scalars.yaml", RCT_RATIO="0.25")

        # Assert
        self.assertEqual(result.ratio, 0.25)

    def test_instantiate__IntEnvUnparseable__RaisesErrorNamingVariable(self) -> None:
        """Test that an unparseable int env value raises and names the env var."""
        # Act & Assert
        with self.assertRaises(ConfigError) as ctx:
            self._instantiate("scalars.yaml", RCT_PORT="eighty")

        self.assertIn("RCT_PORT", str(ctx.exception))


class EnvExpressionShapeIntegrationTests(EnvCoercionTestBase):
    """Tests for env references without a default and with the ?? operator."""

    def test_instantiate__BareAndNullCoalesceEnvSet__ReturnsInts(self) -> None:
        """Test that ``${env:X}`` and ``${env:X ?? d}`` both coerce to int."""
        # Act
        result = self._instantiate("shapes.yaml", RCT_PORT="9000")

        # Assert
        self.assertEqual(result.bare_port, 9000)
        self.assertEqual(result.coalesce_port, 9000)


# =============================================================================
# Enum, List and Optional Coercion
# =============================================================================


class EnvEnumCoercionIntegrationTests(EnvCoercionTestBase):
    """Tests for env values reaching enum fields."""

    def test_instantiate__EnumEnvUnset__ReturnsMemberForDefault(self) -> None:
        """Test that the literal string default resolves to the enum member."""
        # Act
        result = self._instantiate("enum.yaml")

        # Assert
        self.assertIs(result.level, LogLevel.INFO)

    def test_instantiate__EnumEnvSet__ReturnsMember(self) -> None:
        """Test that an env value resolves to the enum member."""
        # Act
        result = self._instantiate("enum.yaml", RCT_LEVEL="DEBUG")

        # Assert
        self.assertIs(result.level, LogLevel.DEBUG)

    def test_instantiate__EnumEnvInvalid__RaisesErrorListingMembers(self) -> None:
        """Test that an invalid enum env value raises and lists valid members."""
        # Act & Assert
        with self.assertRaises(ConfigError) as ctx:
            self._instantiate("enum.yaml", RCT_LEVEL="VERBOSE")

        self.assertIn("DEBUG", str(ctx.exception))
        self.assertIn("INFO", str(ctx.exception))


class EnvListCoercionIntegrationTests(EnvCoercionTestBase):
    """Tests for env values reaching list fields."""

    def test_instantiate__ListEnvUnset__UsesListLiteralDefault(self) -> None:
        """Test that an unset env var yields the list literal default."""
        # Act
        result = self._instantiate("lists.yaml")

        # Assert
        self.assertEqual(result.hosts, ["localhost"])

    def test_instantiate__ListEnvCommaSeparated__ReturnsStrippedItems(self) -> None:
        """Test that a comma-separated env value is split and stripped."""
        # Act
        result = self._instantiate("lists.yaml", RCT_HOSTS="localhost, 127.0.0.1")

        # Assert
        self.assertEqual(result.hosts, ["localhost", "127.0.0.1"])


class EnvOptionalCoercionIntegrationTests(EnvCoercionTestBase):
    """Tests for env values reaching ``X | None`` fields."""

    def test_instantiate__OptionalEnvUnset__ReturnsNone(self) -> None:
        """Test that an unset env var with a null default yields None."""
        # Act
        result = self._instantiate("optional.yaml")

        # Assert
        self.assertIsNone(result.timeout)
        self.assertIsNone(result.label)

    def test_instantiate__OptionalIntEnvSet__ReturnsInt(self) -> None:
        """Test that an ``int | None`` field receives an int from the environment."""
        # Act
        result = self._instantiate("optional.yaml", RCT_TIMEOUT="30")

        # Assert
        self.assertEqual(result.timeout, 30)

    def test_instantiate__OptionalStrEnvSet__KeepsString(self) -> None:
        """Test that a ``str | None`` field keeps a numeric-looking env value as str."""
        # Act
        result = self._instantiate("optional.yaml", RCT_LABEL="5")

        # Assert
        self.assertEqual(result.label, "5")


# =============================================================================
# Empty Values and Validation
# =============================================================================


class EnvEmptyValueIntegrationTests(EnvCoercionTestBase):
    """Tests for env vars that are set to an empty string."""

    def test_instantiate__EmptyIntEnv__UsesDefault(self) -> None:
        """Test that ``VAR=`` falls back to the declared default."""
        # Act
        result = self._instantiate("scalars.yaml", RCT_PORT="")

        # Assert
        self.assertEqual(result.port, 8080)


class ValidateWithEnvInterpolationIntegrationTests(EnvCoercionTestBase):
    """Tests for rc.validate() on configs that use env interpolation."""

    def test_validate__EnvUnsetWithTypedDefaults__ReturnsValid(self) -> None:
        """Test that a config valid for instantiate() is also valid for validate()."""
        # Act
        result = rc.validate(CONFIG_DIR / "scalars.yaml", cli_overrides=False)

        # Assert
        self.assertTrue(result.valid, result.errors)


# =============================================================================
# Entry Points Other Than instantiate()
# =============================================================================


class EnvCoercionEntryPointIntegrationTests(EnvCoercionTestBase):
    """Tests that env coercion applies to every public entry point."""

    def test_instantiateMultirun__BoolEnvSet__ReturnsBool(self) -> None:
        """Test that multirun instances receive a coerced env value."""
        # Arrange
        os.environ["RCT_DEBUG"] = "false"

        # Act
        results = list(
            rc.instantiate_multirun(
                CONFIG_DIR / "scalars.yaml",
                sweep={"name": ["run"]},
                cli_overrides=False,
            )
        )

        # Assert
        self.assertIs(results[0].instance.debug, False)

    def test_toDict__BoolEnvSet__ExportsBool(self) -> None:
        """Test that exported configs contain coerced env values."""
        # Arrange
        os.environ["RCT_DEBUG"] = "false"

        # Act
        result = rc.to_dict(CONFIG_DIR / "scalars.yaml", cli_overrides=False)

        # Assert
        self.assertIs(result["debug"], False)

    def test_getProvenance__BoolEnvSet__RecordsBoolWithEnvSource(self) -> None:
        """Test that provenance records the coerced value and its env source."""
        # Arrange
        os.environ["RCT_DEBUG"] = "false"

        # Act
        provenance = rc.get_provenance(CONFIG_DIR / "scalars.yaml", cli_overrides=False)

        # Assert
        entry = provenance["debug"]
        self.assertEqual(entry.interpolation.kind, "env")
        self.assertEqual(entry.interpolation.env_var, "RCT_DEBUG")
        self.assertIs(entry.value, False)


# =============================================================================
# Locations: Nested, List Element, Chained Reference
# =============================================================================


class EnvCoercionLocationIntegrationTests(EnvCoercionTestBase):
    """Tests for env values in nested objects, list elements and references."""

    def test_instantiate__NestedIntEnvSet__ReturnsInt(self) -> None:
        """Test that a nested dataclass field receives a coerced env value."""
        # Act
        result = self._instantiate("nested.yaml", RCT_PORT="9000")

        # Assert
        self.assertEqual(result.server.port, 9000)

    def test_instantiate__ListElementIntEnvSet__ReturnsInt(self) -> None:
        """Test that an env-sourced list element is coerced to the element type."""
        # Act
        result = self._instantiate("list_element.yaml", RCT_PORT="9000")

        # Assert
        self.assertEqual(result.ports, [9000, 9000])

    def test_instantiate__ChainedReferenceToIntEnv__ReturnsInts(self) -> None:
        """Test that a reference to an env-sourced value is coerced too."""
        # Act
        result = self._instantiate("chained.yaml", RCT_PORT="9000")

        # Assert
        self.assertEqual(result.base_port, 9000)
        self.assertEqual(result.derived_port, 9000)


# =============================================================================
# Values That Must Not Be Coerced
# =============================================================================


class EnvStringPreservationIntegrationTests(EnvCoercionTestBase):
    """Regression guards against over-eager coercion."""

    def test_instantiate__LiteralFalseInStrField__StaysString(self) -> None:
        """Test that a literal 'false' in a str field stays the string 'false'."""
        # Act
        result = self._instantiate("literals.yaml")

        # Assert
        self.assertEqual(result.flag_text, "false")

    def test_instantiate__EmbeddedEnvInString__StaysString(self) -> None:
        """Test that an env value embedded in a string stays a string."""
        # Act
        result = self._instantiate("literals.yaml", RCT_A="1")

        # Assert
        self.assertEqual(result.path, "x-1")

    def test_instantiate__EnvIntoStrField__StaysString(self) -> None:
        """Test that a numeric-looking env value in a str field stays a string."""
        # Act
        result = self._instantiate("scalars.yaml", RCT_NAME="123")

        # Assert
        self.assertEqual(result.name, "123")

    def test_instantiate__EnvIntoAnyField__StaysString(self) -> None:
        """Test that an env value in an Any field is not coerced."""
        # Act
        result = self._instantiate("any_field.yaml", RCT_DEBUG="false")

        # Assert
        self.assertEqual(result.anything, "false")

    def test_instantiate__EnvIntoUntypedDict__StaysString(self) -> None:
        """Test that an env value under a dict without a type hint is not coerced."""
        # Act
        result = self._instantiate("literals.yaml", RCT_DEBUG="false")

        # Assert
        self.assertEqual(result.untyped["debug"], "false")
