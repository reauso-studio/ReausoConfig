"""Tests for the module-level API (rconfig.register, rconfig.instantiate, etc.)."""

import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from unittest import TestCase
from unittest.mock import patch

import rconfig as rc
from rconfig.composition import clear_cache

from rconfig_unittests.fixtures import MockFileSystem, mock_filesystem
from rconfig import (
    AmbiguousTargetError,
    ConfigError,
    ConfigFileError,
    ConfigInstantiator,
    ConfigValidator,
    InstantiationError,
    InvalidOverridePathError,
    InvalidOverrideSyntaxError,
    MissingFieldError,
    Override,
    OverrideError,
    TargetNotFoundError,
    TypeMismatchError,
    ValidationError,
    ValidationResult,
)
from rconfig.target import TargetRegistry, TargetEntry


class ModuleLevelAPITests(TestCase):
    def setUp(self):
        # Clear the store before each test
        rc._store.clear()
        clear_cache()

    def test_register__TargetClass__AddsToKnownReferences(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        # Act
        rc.register("model", Model)

        # Assert
        refs = rc.known_targets()
        self.assertIn("model", refs)
        self.assertIs(refs["model"].target_class, Model)

    def test_unregister__RegisteredName__RemovesReference(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Act
        rc.unregister("model")

        # Assert
        refs = rc.known_targets()
        self.assertNotIn("model", refs)

    def test_unregister__UnknownName__RaisesKeyError(self):
        # Act & Assert
        with self.assertRaises(KeyError):
            rc.unregister("unknown")

    def test_validate__FilePath__LoadsAndValidates(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act
            result = rc.validate(Path("/configs/model.yaml"))

            # Assert
            self.assertIsInstance(result, ValidationResult)
            self.assertTrue(result.valid)

    def test_validate__NonexistentFile__RaisesConfigFileError(self):
        # Act & Assert
        with self.assertRaises(ConfigFileError):
            rc.validate(Path("/nonexistent/config.yaml"))

    def test_instantiate__FilePath__LoadsAndInstantiates(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 512\n")

        with mock_filesystem(fs):
            # Act
            result = rc.instantiate(Path("/configs/model.yaml"), cli_overrides=False)

            # Assert
            self.assertIsInstance(result, Model)
            self.assertEqual(result.size, 512)

    def test_known_targets__ReturnsImmutableMapping(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Act
        refs = rc.known_targets()

        # Assert
        self.assertIsInstance(refs, MappingProxyType)
        with self.assertRaises(TypeError):
            refs["new"] = object()  # type: ignore[index]


class ExportsTests(TestCase):
    def test_exports__AllClassesAccessible(self):
        # Act & Assert
        self.assertTrue(issubclass(TargetRegistry, object))
        self.assertTrue(issubclass(TargetEntry, object))
        self.assertTrue(issubclass(ConfigValidator, object))
        self.assertTrue(issubclass(ConfigInstantiator, object))

    def test_exports__AllExceptionsAccessible(self):
        # Act & Assert
        self.assertTrue(issubclass(ConfigError, Exception))
        self.assertTrue(issubclass(ConfigFileError, ConfigError))
        self.assertTrue(issubclass(TargetNotFoundError, ConfigError))
        self.assertTrue(issubclass(ValidationError, ConfigError))
        self.assertTrue(issubclass(MissingFieldError, ValidationError))
        self.assertTrue(issubclass(TypeMismatchError, ValidationError))
        self.assertTrue(issubclass(InstantiationError, ConfigError))
        self.assertTrue(issubclass(OverrideError, ConfigError))
        self.assertTrue(issubclass(InvalidOverridePathError, OverrideError))
        self.assertTrue(issubclass(InvalidOverrideSyntaxError, OverrideError))

    def test_exports__OverrideClassAccessible(self):
        # Act - Create an instance to verify class is properly exported
        override = Override(path=["test"], value=1, operation="set")

        # Assert
        self.assertEqual(override.path, ["test"])
        self.assertEqual(override.value, 1)
        self.assertEqual(override.operation, "set")


class IntegrationTests(TestCase):
    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_full_workflow__YamlFileToInstance__Works(self):
        # Arrange
        @dataclass
        class ModelConfig:
            hidden_size: int
            dropout: float = 0.1

        @dataclass
        class TrainerConfig:
            model: ModelConfig
            epochs: int

        rc.register("model", ModelConfig)
        rc.register("trainer", TrainerConfig)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  hidden_size: 256
  dropout: 0.2
epochs: 10
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - Method 1: One-liner
            trainer = rc.instantiate(Path("/configs/trainer.yaml"), cli_overrides=False)

            # Assert
            self.assertIsInstance(trainer, TrainerConfig)
            self.assertIsInstance(trainer.model, ModelConfig)
            self.assertEqual(trainer.model.hidden_size, 256)
            self.assertEqual(trainer.model.dropout, 0.2)
            self.assertEqual(trainer.epochs, 10)

            # Act - Method 2: Validate first (dry-run), then instantiate
            result = rc.validate(Path("/configs/trainer.yaml"))

            # Assert
            self.assertTrue(result.valid)

            # Act
            trainer2 = rc.instantiate(Path("/configs/trainer.yaml"), cli_overrides=False)

            # Assert
            self.assertEqual(trainer2.epochs, 10)


class InstantiateWithOverridesTests(TestCase):
    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_instantiate__WithDictOverrides__AppliesOverrides(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act
            result = rc.instantiate(
                Path("/configs/model.yaml"), overrides={"size": 512}, cli_overrides=False
            )

            # Assert
            self.assertEqual(result.size, 512)

    def test_instantiate__WithCliOverridesFalse__IgnoresSysArgv(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act - sys.argv may contain test runner args, but they should be ignored
            result = rc.instantiate(Path("/configs/model.yaml"), cli_overrides=False)

            # Assert - should use config value, not any CLI args
            self.assertEqual(result.size, 256)

    def test_instantiate__WithNestedOverride__AppliesNestedValue(self):
        # Arrange
        @dataclass
        class ModelConfig:
            hidden_size: int

        @dataclass
        class TrainerConfig:
            model: ModelConfig
            epochs: int

        rc.register("model", ModelConfig)
        rc.register("trainer", TrainerConfig)

        fs = MockFileSystem("/configs")
        fs.add_file(
            "/configs/trainer.yaml",
            "_target_: trainer\nmodel:\n  _target_: model\n  hidden_size: 256\nepochs: 10\n",
        )

        with mock_filesystem(fs):
            # Act
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                overrides={"model.hidden_size": 1024},
                cli_overrides=False,
            )

            # Assert
            self.assertEqual(result.model.hidden_size, 1024)
            self.assertEqual(result.epochs, 10)

    def test_instantiate__WithInvalidPath__RaisesInvalidOverridePathError(self):
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act & Assert
            with self.assertRaises(InvalidOverridePathError):
                rc.instantiate(
                    Path("/configs/model.yaml"),
                    overrides={"nonexistent": 123},
                    cli_overrides=False,
                )

    def test_instantiate__WithTypeCoercion__ConvertsStringValue(self):
        # Arrange
        @dataclass
        class Model:
            lr: float

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\n")

        with mock_filesystem(fs):
            # Act - pass string value that should be coerced to float
            result = rc.instantiate(
                Path("/configs/model.yaml"),
                overrides={"lr": "0.01"},
                cli_overrides=False,
            )

            # Assert
            self.assertEqual(result.lr, 0.01)
            self.assertIsInstance(result.lr, float)


class ApiCliOverridesTests(TestCase):
    """Tests for CLI overrides in the API to improve coverage."""

    def setUp(self):
        # Clear the store before each test
        rc._store.clear()
        clear_cache()

    def test_instantiate__WithCliOverrides__AppliesOverrides(self):
        """Test instantiate with cli_overrides=True reads from sys.argv."""
        import sys
        from unittest.mock import patch

        @dataclass
        class Model:
            lr: float
            epochs: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\nepochs: 10\n")

        with mock_filesystem(fs):
            # Mock sys.argv to include overrides
            with patch.object(sys, "argv", ["script.py", "lr=0.001", "epochs=100"]):
                # Act
                result = rc.instantiate(Path("/configs/model.yaml"), cli_overrides=True)

                # Assert - CLI overrides should be applied
                self.assertEqual(result.lr, 0.001)
                self.assertEqual(result.epochs, 100)

    def test_instantiate__WithCliOverridesDisabled__IgnoresArgv(self):
        """Test instantiate with cli_overrides=False ignores sys.argv."""
        import sys
        from unittest.mock import patch

        @dataclass
        class Model:
            lr: float

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\n")

        with mock_filesystem(fs):
            # Mock sys.argv with overrides
            with patch.object(sys, "argv", ["script.py", "lr=999"]):
                # Act - cli_overrides=False should ignore sys.argv
                result = rc.instantiate(Path("/configs/model.yaml"), cli_overrides=False)

                # Assert - original value should be used
                self.assertEqual(result.lr, 0.1)


class PartialInstantiationTests(TestCase):
    """Tests for partial instantiation with inner_path parameter."""

    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_instantiate__InnerPath__ReturnsSubConfig(self):
        """Test basic partial instantiation returns nested object."""

        @dataclass
        class Encoder:
            hidden_size: int

        @dataclass
        class Model:
            encoder: Encoder
            name: str

        @dataclass
        class Trainer:
            model: Model
            epochs: int

        rc.register("encoder", Encoder)
        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  encoder:
    _target_: encoder
    hidden_size: 256
  name: gpt
epochs: 10
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate only the model section
            result = rc.instantiate(
                Path("/configs/trainer.yaml"), inner_path="model", cli_overrides=False
            )

            # Assert
            self.assertIsInstance(result, Model)
            self.assertIsInstance(result.encoder, Encoder)
            self.assertEqual(result.encoder.hidden_size, 256)
            self.assertEqual(result.name, "gpt")

    def test_instantiate__InnerPathNested__ReturnsDeepConfig(self):
        """Test partial instantiation with nested path like 'model.encoder'."""

        @dataclass
        class Encoder:
            layers: int

        @dataclass
        class Model:
            encoder: Encoder

        @dataclass
        class Trainer:
            model: Model

        rc.register("encoder", Encoder)
        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  encoder:
    _target_: encoder
    layers: 6
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate only the encoder
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model.encoder",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Encoder)
            self.assertEqual(result.layers, 6)

    def test_instantiate__InnerPathWithListIndex__ReturnsElement(self):
        """Test partial instantiation with list index path."""

        @dataclass
        class Callback:
            name: str

        @dataclass
        class Trainer:
            callbacks: list

        rc.register("callback", Callback)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
callbacks:
  - _target_: callback
    name: first
  - _target_: callback
    name: second
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate first callback
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="callbacks[1]",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Callback)
            self.assertEqual(result.name, "second")

    def test_instantiate__InnerPathWithInterpolation__ResolvesFromFullConfig(self):
        """Test interpolations resolve from full config before extraction."""

        @dataclass
        class Model:
            lr: float

        @dataclass
        class Trainer:
            defaults: dict
            model: Model

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
defaults:
  learning_rate: 0.01
model:
  _target_: model
  lr: ${/defaults.learning_rate}
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate only the model
            result = rc.instantiate(
                Path("/configs/trainer.yaml"), inner_path="model", cli_overrides=False
            )

            # Assert - interpolation should have resolved from full config
            self.assertIsInstance(result, Model)
            self.assertEqual(result.lr, 0.01)

    def test_instantiate__InnerPathWithOverrides__AppliesOverridesFirst(self):
        """Test overrides are applied to full config before extraction."""

        @dataclass
        class Model:
            size: int

        @dataclass
        class Trainer:
            model: Model

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  size: 256
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - override the model size, then extract model
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                overrides={"model.size": 512},
                cli_overrides=False,
            )

            # Assert
            self.assertEqual(result.size, 512)

    def test_instantiate__InvalidInnerPath__RaisesInvalidInnerPathError(self):
        """Test that invalid inner_path raises InvalidInnerPathError."""

        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            with self.assertRaises(rc.InvalidInnerPathError):
                rc.instantiate(
                    Path("/configs/model.yaml"),
                    inner_path="nonexistent",
                    cli_overrides=False,
                )

    def test_instantiate__InnerPathToScalar__RaisesInvalidInnerPathError(self):
        """Test that path to non-dict raises InvalidInnerPathError."""

        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            with self.assertRaises(rc.InvalidInnerPathError):
                rc.instantiate(
                    Path("/configs/model.yaml"), inner_path="size", cli_overrides=False
                )

    def test_instantiate__InnerPathNone__FullInstantiation(self):
        """Test that inner_path=None gives normal full instantiation."""

        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act - inner_path=None (default)
            result = rc.instantiate(
                Path("/configs/model.yaml"), inner_path=None, cli_overrides=False
            )

            # Assert - full instantiation
            self.assertIsInstance(result, Model)
            self.assertEqual(result.size, 256)

    def test_instantiate__InnerPathWithExpectedType__ReturnsTypedResult(self):
        """Test that expected_type works with inner_path."""

        @dataclass
        class Encoder:
            dim: int

        @dataclass
        class Model:
            encoder: Encoder

        rc.register("encoder", Encoder)
        rc.register("model", Model)

        yaml_content = """
_target_: model
encoder:
  _target_: encoder
  dim: 512
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - use expected_type with inner_path
            result = rc.instantiate(
                Path("/configs/model.yaml"),
                Encoder,
                inner_path="encoder",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Encoder)
            self.assertEqual(result.dim, 512)

    def test_instantiate__InnerPathWithExternalInstance__InstantiatesTarget(self):
        """Test _instance_ refs to targets outside partial scope work."""

        @dataclass
        class Cache:
            size: int

        @dataclass
        class Service:
            cache: Cache

        @dataclass
        class App:
            shared_cache: Cache
            service: Service

        rc.register("cache", Cache)
        rc.register("service", Service)
        rc.register("app", App)

        yaml_content = """
_target_: app
shared_cache:
  _target_: cache
  size: 100
service:
  _target_: service
  cache:
    _instance_: /shared_cache
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/app.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate only the service, which has _instance_ to external
            result = rc.instantiate(
                Path("/configs/app.yaml"), inner_path="service", cli_overrides=False
            )

            # Assert
            self.assertIsInstance(result, Service)
            self.assertIsInstance(result.cache, Cache)
            self.assertEqual(result.cache.size, 100)


class ValidateWithInnerPathTests(TestCase):
    """Tests for rc.validate() with inner_path parameter."""

    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_validate__InnerPathToValidSection__ReturnsValidResult(self):
        """Test that inner_path validates only the specified section."""
        # Arrange
        @dataclass
        class Model:
            size: int

        @dataclass
        class Trainer:
            model: Model
            epochs: int

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  size: 256
epochs: 10
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert
            self.assertTrue(result.valid)
            self.assertEqual(len(result.errors), 0)

    def test_validate__InnerPathWithOverrides__AppliesOverridesBeforeExtraction(self):
        """Test that overrides are applied before inner_path extraction."""
        # Arrange
        @dataclass
        class Model:
            size: int

        @dataclass
        class Trainer:
            model: Model

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  size: 256
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - override model.size, then validate only model section
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                overrides={"model.size": 512},
                cli_overrides=False,
            )

            # Assert - validation should pass (no type errors)
            self.assertTrue(result.valid)

    def test_validate__InnerPathToInvalidSection__ReturnsInvalidResult(self):
        """Test validation errors for invalid nested config."""
        # Arrange
        @dataclass
        class Model:
            size: int  # Expects int

        @dataclass
        class Trainer:
            model: Model

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  size: "not_an_int"
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert - should have type error
            self.assertFalse(result.valid)
            self.assertGreater(len(result.errors), 0)

    def test_validate__InnerPathNotFound__RaisesInvalidInnerPathError(self):
        """Test that non-existent inner_path raises error."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act & Assert
            with self.assertRaises(rc.InvalidInnerPathError):
                rc.validate(
                    Path("/configs/model.yaml"),
                    inner_path="nonexistent",
                    cli_overrides=False,
                )

    def test_validate__InnerPathToNonDict__RaisesInvalidInnerPathError(self):
        """Test that inner_path pointing to scalar raises error."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act & Assert
            with self.assertRaises(rc.InvalidInnerPathError):
                rc.validate(
                    Path("/configs/model.yaml"),
                    inner_path="size",
                    cli_overrides=False,
                )

    def test_validate__InnerPathWithRequiredInSection__ChecksRequiredInSection(self):
        """Test that _required_ markers in section are validated."""
        # Arrange
        @dataclass
        class Model:
            api_key: str

        @dataclass
        class Trainer:
            model: Model

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  api_key: _required_
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - validate model section with unsatisfied _required_
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert - should fail due to _required_
            self.assertFalse(result.valid)
            self.assertGreater(len(result.errors), 0)

    def test_validate__InnerPathWithRequiredOutsideSection__IgnoresOutsideRequired(self):
        """Test that _required_ markers outside inner_path are ignored."""
        # Arrange
        @dataclass
        class Model:
            size: int

        @dataclass
        class Trainer:
            model: Model
            api_key: str

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  size: 256
api_key: _required_
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - validate only model section, api_key is outside
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert - should pass because _required_ is outside section
            self.assertTrue(result.valid)


class GetProvenanceWithOverridesTests(TestCase):
    """Tests for rc.get_provenance() with overrides and cli_overrides parameters."""

    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_get_provenance__WithOverrides__ReflectsOverriddenValues(self):
        """Test that provenance shows overridden values."""
        # Arrange
        @dataclass
        class Model:
            lr: float

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\n")

        with mock_filesystem(fs):
            # Act
            prov = rc.get_provenance(
                Path("/configs/model.yaml"),
                overrides={"lr": 0.01},
                cli_overrides=False,
            )

            # Assert - provenance should show overridden value
            entry = prov.get("lr")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.value, 0.01)

    def test_get_provenance__CliOverridesFalse__IgnoresCliArgs(self):
        """Test that CLI overrides are ignored when disabled."""
        import sys
        from unittest.mock import patch as mock_patch

        # Arrange
        @dataclass
        class Model:
            lr: float

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\n")

        with mock_filesystem(fs):
            # Mock sys.argv with overrides
            with mock_patch.object(sys, "argv", ["script.py", "lr=999"]):
                # Act
                prov = rc.get_provenance(
                    Path("/configs/model.yaml"),
                    cli_overrides=False,
                )

                # Assert - original value should be used
                entry = prov.get("lr")
                self.assertIsNotNone(entry)
                self.assertEqual(entry.value, 0.1)

    def test_get_provenance__WithInnerPathAndOverrides__CombinesBoth(self):
        """Test using both inner_path and overrides together."""
        # Arrange
        @dataclass
        class Model:
            size: int

        @dataclass
        class Trainer:
            model: Model

        rc.register("model", Model)
        rc.register("trainer", Trainer)

        yaml_content = """
_target_: trainer
model:
  _target_: model
  size: 256
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - use both inner_path and overrides
            # inner_path controls lazy loading, but provenance still has full paths
            prov = rc.get_provenance(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                overrides={"model.size": 512},
                cli_overrides=False,
            )

            # Assert - provenance should show overridden value
            entry = prov.get("model.size")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.value, 512)

    def test_get_provenance__InvalidOverridePath__RaisesInvalidOverridePathError(self):
        """Test that invalid override paths raise appropriate error."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        fs = MockFileSystem("/configs")
        fs.add_file("/configs/model.yaml", "_target_: model\nsize: 256\n")

        with mock_filesystem(fs):
            # Act & Assert
            with self.assertRaises(InvalidOverridePathError):
                rc.get_provenance(
                    Path("/configs/model.yaml"),
                    overrides={"nonexistent": 123},
                    cli_overrides=False,
                )


class PartialInstantiationWithoutRootTargetTests(TestCase):
    """Tests for partial instantiation when root _target_ is missing."""

    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_instantiate__InnerPathNoRootTarget__InnerHasTarget__Works(self):
        """inner_path to section with _target_ works without root _target_."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Config without root _target_
        yaml_content = """
model:
  _target_: model
  size: 256
data:
  path: /data
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate only the model section
            result = rc.instantiate(
                Path("/configs/trainer.yaml"), inner_path="model", cli_overrides=False
            )

            # Assert
            self.assertIsInstance(result, Model)
            self.assertEqual(result.size, 256)

    def test_instantiate__InnerPathNoRootTarget__NestedSectionHasTarget__Works(self):
        """inner_path to nested section with explicit _target_ works."""
        # Arrange
        @dataclass
        class Database:
            port: int

        @dataclass
        class Model:
            database: Database

        rc.register("model", Model)
        rc.register("database", Database)

        # Config without root _target_, model has _target_, database has _target_
        yaml_content = """
model:
  _target_: model
  database:
    _target_: database
    port: 5432
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate database section
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model.database",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Database)
            self.assertEqual(result.port, 5432)

    def test_instantiate__InnerPathNoRootTarget__InnerNoTarget__RaisesAmbiguousTargetError(
        self,
    ):
        """inner_path to section without _target_ and no parent raises AmbiguousTargetError."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Config without root _target_, data section also has no _target_
        yaml_content = """
model:
  _target_: model
  size: 256
data:
  path: /data
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act & Assert - data has no _target_ and no parent to infer from
            with self.assertRaises(rc.AmbiguousTargetError):
                rc.instantiate(
                    Path("/configs/trainer.yaml"),
                    inner_path="data",
                    cli_overrides=False,
                )

    def test_instantiate__InnerPathNoRootTarget__EmptySection__RaisesAmbiguousTargetError(
        self,
    ):
        """inner_path to empty dict raises AmbiguousTargetError."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Config with empty section
        yaml_content = """
model:
  _target_: model
  size: 256
empty_section: {}
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act & Assert
            with self.assertRaises(rc.AmbiguousTargetError):
                rc.instantiate(
                    Path("/configs/trainer.yaml"),
                    inner_path="empty_section",
                    cli_overrides=False,
                )

    def test_instantiate__NoInnerPathNoRootTarget__RaisesAmbiguousTargetError(self):
        """Without inner_path, missing root _target_ raises AmbiguousTargetError."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Config without root _target_
        yaml_content = """
model:
  _target_: model
  size: 256
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act & Assert - no inner_path means root needs _target_
            with self.assertRaises(rc.AmbiguousTargetError):
                rc.instantiate(
                    Path("/configs/trainer.yaml"),
                    cli_overrides=False,
                )

    def test_validate__InnerPathNoRootTarget__InnerHasTarget__Works(self):
        """validate() with inner_path to section with _target_ works."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        # Config without root _target_
        yaml_content = """
model:
  _target_: model
  size: 256
data:
  path: /data
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert
            self.assertTrue(result.valid)

    def test_validate__InnerPathNoRootTarget__NestedSectionHasTarget__Works(self):
        """validate() with inner_path to nested section with _target_ works."""
        # Arrange
        @dataclass
        class Database:
            port: int

        @dataclass
        class Model:
            database: Database

        rc.register("model", Model)
        rc.register("database", Database)

        yaml_content = """
model:
  _target_: model
  database:
    _target_: database
    port: 5432
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model.database",
                cli_overrides=False,
            )

            # Assert
            self.assertTrue(result.valid)

    def test_validate__InnerPathNoRootTarget__InnerNoTarget__ReturnsInvalid(self):
        """validate() returns invalid for section without _target_ and no parent."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        yaml_content = """
model:
  _target_: model
  size: 256
data:
  path: /data
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="data",
                cli_overrides=False,
            )

            # Assert - validation should fail (no _target_ to validate)
            self.assertFalse(result.valid)

    def test_instantiate__InnerPathNoRootTarget__WithInterpolation__Works(self):
        """Config without root _target_ with interpolations resolved from full config."""
        # Arrange
        @dataclass
        class Model:
            size: int
            actual_size: int

        rc.register("model", Model)

        yaml_content = """
defaults:
  hidden_size: 512
model:
  _target_: model
  size: 256
  actual_size: ${/defaults.hidden_size}
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert - interpolation should resolve from full config
            self.assertIsInstance(result, Model)
            self.assertEqual(result.size, 256)
            self.assertEqual(result.actual_size, 512)

    def test_instantiate__InnerPathNoRootTarget__WithOverrides__Works(self):
        """Config without root _target_ with overrides applied to inner section."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        yaml_content = """
model:
  _target_: model
  size: 256
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                overrides={"model.size": 512},
                cli_overrides=False,
            )

            # Assert
            self.assertEqual(result.size, 512)

    def test_getProvenance__InnerPathNoRootTarget__Works(self):
        """get_provenance() with inner_path works without root _target_."""
        # Arrange
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        yaml_content = """
model:
  _target_: model
  size: 256
data:
  path: /data
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - get provenance for model section only
            prov = rc.get_provenance(
                Path("/configs/trainer.yaml"),
                inner_path="model",
                cli_overrides=False,
            )

            # Assert - should have provenance for model section
            self.assertIsNotNone(prov.get("model.size"))
            entry = prov.get("model.size")
            self.assertEqual(entry.value, 256)

    def test_getProvenance__NoInnerPathNoRootTarget__Works(self):
        """get_provenance() without inner_path works even without root _target_."""
        # Arrange - provenance doesn't require instantiation, just composition
        @dataclass
        class Model:
            size: int

        rc.register("model", Model)

        yaml_content = """
model:
  _target_: model
  size: 256
data:
  path: /data
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - get provenance for full config (no instantiation)
            prov = rc.get_provenance(
                Path("/configs/trainer.yaml"),
                cli_overrides=False,
            )

            # Assert - should have provenance for all values
            self.assertIsNotNone(prov.get("model.size"))
            self.assertIsNotNone(prov.get("data.path"))


class TypeInferenceFromParentApiTests(TestCase):
    """Tests for type inference from parent's type hints at API level."""

    def setUp(self):
        rc._store.clear()
        clear_cache()

    def test_instantiate__InnerPathNoTarget__TypeInferredFromParent__Works(self):
        """inner_path to section without _target_ works when type inferred from parent."""
        # Arrange
        @dataclass
        class Database:
            port: int

        @dataclass
        class Model:
            database: Database  # Concrete type hint

        rc.register("model", Model)
        rc.register("database", Database)

        # Config without _target_ on database
        yaml_content = """
model:
  _target_: model
  database:
    port: 5432
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - instantiate database section (type inferred from Model.database)
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model.database",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Database)
            self.assertEqual(result.port, 5432)

    def test_validate__InnerPathNoTarget__TypeInferredFromParent__Works(self):
        """validate() with inner_path works when type inferred from parent."""
        # Arrange
        @dataclass
        class Database:
            port: int

        @dataclass
        class Model:
            database: Database

        rc.register("model", Model)
        rc.register("database", Database)

        yaml_content = """
model:
  _target_: model
  database:
    port: 5432
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act
            result = rc.validate(
                Path("/configs/trainer.yaml"),
                inner_path="model.database",
                cli_overrides=False,
            )

            # Assert
            self.assertTrue(result.valid)

    def test_instantiate__InnerPathNoTarget__DeeplyNested__Works(self):
        """Type inference works for deeply nested paths."""
        # Arrange
        @dataclass
        class Cache:
            size: int

        @dataclass
        class Database:
            cache: Cache

        @dataclass
        class Model:
            database: Database

        rc.register("model", Model)
        rc.register("database", Database)
        rc.register("cache", Cache)

        yaml_content = """
model:
  _target_: model
  database:
    _target_: database
    cache:
      size: 100
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - type inference from Database.cache
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model.database.cache",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Cache)
            self.assertEqual(result.size, 100)

    def test_instantiate__InnerPathNoTarget__ParentNoTarget__RaisesError(self):
        """Cannot infer type if parent has no _target_."""
        # Arrange
        @dataclass
        class Database:
            port: int

        rc.register("database", Database)

        yaml_content = """
model:
  database:
    port: 5432
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act & Assert - model has no _target_, can't infer database type
            with self.assertRaises(rc.AmbiguousTargetError):
                rc.instantiate(
                    Path("/configs/trainer.yaml"),
                    inner_path="model.database",
                    cli_overrides=False,
                )

    def test_instantiate__InnerPathNoTarget__AutoRegisters__Works(self):
        """Type inference auto-registers the class if not registered."""
        # Arrange
        @dataclass
        class Database:
            port: int

        @dataclass
        class Model:
            database: Database

        rc.register("model", Model)
        # Note: Database is NOT registered

        yaml_content = """
model:
  _target_: model
  database:
    port: 5432
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - should auto-register Database
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model.database",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Database)
            self.assertEqual(result.port, 5432)

    def test_instantiate__ListIndex__TypeInferredFromListHint__Works(self):
        """inner_path to list element infers type from list[X] hint."""
        # Arrange
        @dataclass
        class Callback:
            name: str

        @dataclass
        class Trainer:
            callbacks: list[Callback]

        rc.register("trainer", Trainer)
        rc.register("callback", Callback)

        yaml_content = """
trainer:
  _target_: trainer
  callbacks:
    - name: first
    - name: second
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - type inference from list[Callback]
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="trainer.callbacks[0]",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Callback)
            self.assertEqual(result.name, "first")

    def test_instantiate__ListIndexSecondElement__TypeInferred__Works(self):
        """inner_path to second list element also infers type correctly."""
        # Arrange
        @dataclass
        class Callback:
            name: str

        @dataclass
        class Trainer:
            callbacks: list[Callback]

        rc.register("trainer", Trainer)
        rc.register("callback", Callback)

        yaml_content = """
trainer:
  _target_: trainer
  callbacks:
    - name: first
    - name: second
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - type inference for callbacks[1]
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="trainer.callbacks[1]",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Callback)
            self.assertEqual(result.name, "second")

    def test_instantiate__ListIndexDeeplyNested__TypeInferred__Works(self):
        """inner_path to deeply nested list element infers type correctly."""
        # Arrange
        @dataclass
        class Layer:
            size: int

        @dataclass
        class Encoder:
            layers: list[Layer]

        @dataclass
        class Model:
            encoder: Encoder

        rc.register("model", Model)
        rc.register("encoder", Encoder)
        rc.register("layer", Layer)

        yaml_content = """
model:
  _target_: model
  encoder:
    _target_: encoder
    layers:
      - size: 256
      - size: 512
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - deeply nested list element
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="model.encoder.layers[0]",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Layer)
            self.assertEqual(result.size, 256)

    def test_instantiate__ListIndexAutoRegisters__Works(self):
        """List element type inference auto-registers the class if not registered."""
        # Arrange
        @dataclass
        class Callback:
            name: str

        @dataclass
        class Trainer:
            callbacks: list[Callback]

        rc.register("trainer", Trainer)
        # Note: Callback is NOT registered

        yaml_content = """
trainer:
  _target_: trainer
  callbacks:
    - name: first
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act - should auto-register Callback
            result = rc.instantiate(
                Path("/configs/trainer.yaml"),
                inner_path="trainer.callbacks[0]",
                cli_overrides=False,
            )

            # Assert
            self.assertIsInstance(result, Callback)
            self.assertEqual(result.name, "first")

    def test_instantiate__ListIndexUnparameterizedList__RaisesError(self):
        """Cannot infer type from unparameterized list."""
        # Arrange
        @dataclass
        class Trainer:
            callbacks: list  # No type parameter

        rc.register("trainer", Trainer)

        yaml_content = """
trainer:
  _target_: trainer
  callbacks:
    - name: first
"""
        fs = MockFileSystem("/configs")
        fs.add_file("/configs/trainer.yaml", yaml_content)

        with mock_filesystem(fs):
            # Act & Assert - unparameterized list, can't infer type
            with self.assertRaises(rc.AmbiguousTargetError):
                rc.instantiate(
                    Path("/configs/trainer.yaml"),
                    inner_path="trainer.callbacks[0]",
                    cli_overrides=False,
                )


@dataclass
class _HostModel:
    lr: float


class ApiCliOverridesDefaultTests(TestCase):
    """Tests for the default CLI override behaviour when embedded in a host program.

    A host program (web app, worker, test runner) owns sys.argv. With default
    arguments, loading a config should neither consume nor reject its arguments.
    """

    HOST_ARGV = ["manage.py", "migrate", "verbosity=2"]

    def setUp(self):
        rc._store.clear()
        clear_cache()
        rc.register("model", _HostModel)
        self._fs = MockFileSystem("/configs")
        self._fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\n")

    def test_instantiate__DefaultCliOverridesWithHostArgv__IgnoresArgv(self):
        """Test that instantiate() ignores host program arguments by default."""
        # Arrange
        with mock_filesystem(self._fs), patch.object(sys, "argv", list(self.HOST_ARGV)):
            # Act
            result = rc.instantiate(Path("/configs/model.yaml"))

        # Assert
        self.assertEqual(result.lr, 0.1)

    def test_validate__DefaultCliOverridesWithHostArgv__IgnoresArgv(self):
        """Test that validate() ignores host program arguments by default."""
        # Arrange
        with mock_filesystem(self._fs), patch.object(sys, "argv", list(self.HOST_ARGV)):
            # Act
            result = rc.validate(Path("/configs/model.yaml"))

        # Assert
        self.assertTrue(result.valid)

    def test_toDict__DefaultCliOverridesWithHostArgv__IgnoresArgv(self):
        """Test that to_dict() ignores host program arguments by default."""
        # Arrange
        with mock_filesystem(self._fs), patch.object(sys, "argv", list(self.HOST_ARGV)):
            # Act
            result = rc.to_dict(Path("/configs/model.yaml"))

        # Assert
        self.assertEqual(result["lr"], 0.1)

    def test_getProvenance__DefaultCliOverridesWithHostArgv__IgnoresArgv(self):
        """Test that get_provenance() ignores host program arguments by default."""
        # Arrange
        with mock_filesystem(self._fs), patch.object(sys, "argv", list(self.HOST_ARGV)):
            # Act
            provenance = rc.get_provenance(Path("/configs/model.yaml"))

        # Assert
        self.assertEqual(provenance["lr"].value, 0.1)

    def test_instantiateMultirun__DefaultCliOverridesWithHostArgv__IgnoresArgv(self):
        """Test that instantiate_multirun() ignores host program arguments by default."""
        # Arrange
        with mock_filesystem(self._fs), patch.object(sys, "argv", list(self.HOST_ARGV)):
            # Act
            results = list(rc.instantiate_multirun(Path("/configs/model.yaml"), sweep={"lr": [0.2]}))

        # Assert
        self.assertEqual(results[0].instance.lr, 0.2)

    def test_instantiateMultirun__DefaultCliOverridesWithHostExperimentName__IgnoresArgv(self):
        """Test that a host's ``-e <name>`` flag without '=' is skipped by multirun parsing."""
        # Arrange
        host_argv = ["worker.py", "-e", "staging"]
        with mock_filesystem(self._fs), patch.object(sys, "argv", host_argv):
            # Act
            results = list(rc.instantiate_multirun(Path("/configs/model.yaml"), sweep={"lr": [0.2]}))

        # Assert
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].instance.lr, 0.2)

    def test_instantiateMultirun__DefaultCliOverridesWithHostExperimentKeyValue__IgnoresArgv(self):
        """Test that a host's ``-e KEY=VALUE`` flag is not read as a multirun experiment."""
        # Arrange
        host_argv = ["worker.py", "-e", "lr=0.9"]
        with mock_filesystem(self._fs), patch.object(sys, "argv", host_argv):
            # Act
            results = list(
                rc.instantiate_multirun(Path("/configs/model.yaml"), experiments=[{"lr": 0.2}])
            )

        # Assert
        self.assertEqual([result.instance.lr for result in results], [0.2])

    def test_instantiate__ExplicitCliOverridesWithValidArg__AppliesOverride(self):
        """Test that explicitly enabled CLI overrides still apply."""
        # Arrange
        with mock_filesystem(self._fs), patch.object(sys, "argv", ["train.py", "lr=0.5"]):
            # Act
            result = rc.instantiate(Path("/configs/model.yaml"), cli_overrides=True)

        # Assert
        self.assertEqual(result.lr, 0.5)


class SetCliOverridesTests(TestCase):
    """Tests for the process-wide CLI override policy."""

    def setUp(self):
        rc._store.clear()
        clear_cache()
        rc.register("model", _HostModel)
        self._fs = MockFileSystem("/configs")
        self._fs.add_file("/configs/model.yaml", "_target_: model\nlr: 0.1\n")

    def tearDown(self):
        rc.set_cli_overrides(False)

    def test_cliOverridesEnabled__Default__ReturnsFalse(self):
        """Test that CLI overrides are off unless enabled."""
        # Act & Assert
        self.assertFalse(rc.cli_overrides_enabled())

    def test_instantiate__CliOverridesEnabledProcessWide__AppliesArgv(self):
        """Test that set_cli_overrides(True) makes calls read sys.argv by default."""
        # Arrange
        rc.set_cli_overrides(True)

        with mock_filesystem(self._fs), patch.object(sys, "argv", ["train.py", "lr=0.5"]):
            # Act
            result = rc.instantiate(Path("/configs/model.yaml"))

        # Assert
        self.assertTrue(rc.cli_overrides_enabled())
        self.assertEqual(result.lr, 0.5)

    def test_instantiate__PerCallFalseWithProcessWideTrue__IgnoresArgv(self):
        """Test that a per-call cli_overrides=False takes precedence."""
        # Arrange
        rc.set_cli_overrides(True)

        with mock_filesystem(self._fs), patch.object(sys, "argv", ["train.py", "lr=0.5"]):
            # Act
            result = rc.instantiate(Path("/configs/model.yaml"), cli_overrides=False)

        # Assert
        self.assertEqual(result.lr, 0.1)


@dataclass
class _ServerSection:
    port: int


@dataclass
class _ServiceConfig:
    server: _ServerSection
    retries: int
    lr: float = 0.1


class TypedConfigPipelineTests(TestCase):
    """Tests for string coercion and validation inside the public pipelines."""

    def setUp(self):
        rc._store.clear()
        clear_cache()
        rc.register("service", _ServiceConfig)
        rc.register("server_section", _ServerSection)
        self._fs = MockFileSystem("/configs")

    def test_instantiate__InnerPathWithUnconvertibleValueOutside__IgnoresOutsideValue(self):
        """Test that only values inside inner_path can fail coercion."""
        # Arrange
        self._fs.add_file(
            "/configs/service.yaml",
            "_target_: service\nserver:\n  _target_: server_section\n  port: '8080'\nretries: many\n",
        )

        with mock_filesystem(self._fs):
            # Act
            server = rc.instantiate(Path("/configs/service.yaml"), inner_path="server")

        # Assert
        self.assertEqual(server.port, 8080)

    def test_instantiate__UnconvertibleValue__RaisesValueCoercionError(self):
        """Test that an unconvertible value raises with its path."""
        # Arrange
        self._fs.add_file(
            "/configs/service.yaml",
            "_target_: service\nserver:\n  port: '8080'\nretries: many\n",
        )

        with mock_filesystem(self._fs):
            # Act & Assert
            with self.assertRaises(rc.ValueCoercionError) as ctx:
                rc.instantiate(Path("/configs/service.yaml"))

        self.assertEqual(ctx.exception.config_path, "retries")

    def test_validate__UnconvertibleValue__ReportsSingleCoercionError(self):
        """Test that validate() reports a failed conversion once, not twice."""
        # Arrange
        self._fs.add_file(
            "/configs/service.yaml",
            "_target_: service\nserver:\n  port: 80\nretries: many\n",
        )

        with mock_filesystem(self._fs):
            # Act
            result = rc.validate(Path("/configs/service.yaml"))

        # Assert
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], rc.ValueCoercionError)

    def test_validate__InterpolationOnUnsatisfiedRequired__ReportsRequiredValue(self):
        """Test that an interpolation depending on a _required_ value is not raised."""
        # Arrange
        self._fs.add_file(
            "/configs/service.yaml",
            "_target_: service\nserver:\n  port: 80\nretries: _required_\nlr: ${/retries + 1}\n",
        )

        with mock_filesystem(self._fs):
            # Act
            result = rc.validate(Path("/configs/service.yaml"))

        # Assert
        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], rc.RequiredValueError)
