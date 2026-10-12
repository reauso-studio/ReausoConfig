"""Comprehensive integration tests for all error types.

These tests verify that all error types in rconfig/errors.py are properly
raised with correct messages and context when processing faulty config files.
"""

from dataclasses import dataclass
from pathlib import Path
from unittest.case import TestCase

import rconfig as rc
from rconfig.errors import (
    AmbiguousTargetError,
    CircularInstanceError,
    CircularRefError,
    ConfigFileError,
    InstanceResolutionError,
    InstantiationError,
    InvalidOverridePathError,
    InvalidOverrideSyntaxError,
    MergeError,
    MissingFieldError,
    RefAtRootError,
    RefInstanceConflictError,
    RefResolutionError,
    TargetNotFoundError,
    TargetTypeMismatchError,
    TypeInferenceError,
    TypeMismatchError,
)


# =============================================================================
# Dataclass definitions for error testing
# =============================================================================


@dataclass
class Logger:
    """Logging configuration."""

    level: str
    output_dir: str


@dataclass
class Optimizer:
    """Optimizer configuration."""

    type: str
    learning_rate: float
    weight_decay: float
    betas: list[float]


@dataclass
class Scheduler:
    """Learning rate scheduler configuration."""

    type: str
    warmup_epochs: int
    min_lr: float


@dataclass
class Augmentation:
    """Data augmentation configuration."""

    random_crop: bool = True
    horizontal_flip: bool = True


@dataclass
class Dataset:
    """Dataset configuration."""

    name: str
    root: str
    batch_size: int
    num_workers: int
    augmentation: Augmentation


@dataclass
class ModelConfig:
    """Base class for all model configurations.

    Contains shared fields that all models need: optimizer and scheduler.
    """

    optimizer: Optimizer
    scheduler: Scheduler


@dataclass
class ResNet(ModelConfig):
    """ResNet model configuration."""

    layers: int
    pretrained: bool


@dataclass
class VGG(ModelConfig):
    """VGG model configuration."""

    depth: int
    batch_norm: bool


@dataclass
class TrainingConfig:
    """Training loop configuration."""

    epochs: int
    save_every: int
    log: Logger


@dataclass
class EvalConfig:
    """Evaluation configuration."""

    metrics: list[str]
    log: Logger
    data: Dataset


@dataclass
class TrainerAppBase:
    """Base class for trainer applications.

    Contains shared fields for all trainer configurations.
    """

    logger: Logger
    dataset: Dataset
    training: TrainingConfig
    evaluation: EvalConfig


@dataclass
class TrainerApp(TrainerAppBase):
    """Main trainer application with ResNet model."""

    model: ResNet


@dataclass
class TrainerAppVGG(TrainerAppBase):
    """Main trainer application with VGG model."""

    model: VGG


@dataclass
class TrainerAppPolymorphic(TrainerAppBase):
    """Trainer application with polymorphic model field.

    Used for testing abstract type scenarios where the model
    can be any ModelConfig subclass and requires explicit _target_.
    """

    model: ModelConfig  # Abstract base - requires explicit _target_


# Path to error config files
ERROR_CONFIG_DIR = Path(__file__).parent / "config_files" / "error_cases"
ML_CONFIG_DIR = Path(__file__).parent / "config_files" / "ml_training"


class ErrorIntegrationTestBase(TestCase):
    """Base class with common setup for error integration tests."""

    def setUp(self):
        """Clear store before each test."""
        rc._store._known_targets.clear()
        self._register_test_classes()

    def tearDown(self):
        """Clear cache after each test."""
        rc.clear_cache()

    def _register_test_classes(self):
        """Register all test dataclasses."""
        # Register base infrastructure
        rc.register("logger", Logger)
        rc.register("optimizer", Optimizer)
        rc.register("scheduler", Scheduler)
        rc.register("dataset", Dataset)
        rc.register("augmentation", Augmentation)
        rc.register("trainingconfig", TrainingConfig)
        rc.register("evalconfig", EvalConfig)
        # Register models
        rc.register("resnet", ResNet)
        rc.register("vgg", VGG)
        # Register apps
        rc.register("trainer_app", TrainerApp)
        rc.register("trainer_app_vgg", TrainerAppVGG)
        rc.register("trainer_app_polymorphic", TrainerAppPolymorphic)


# =============================================================================
# ConfigFileError Tests
# =============================================================================


class ConfigFileErrorTests(ErrorIntegrationTestBase):
    """Tests for ConfigFileError scenarios."""

    def test_instantiate__NonexistentFile__RaisesConfigFileError(self):
        """Loading non-existent file raises ConfigFileError."""
        config_path = ERROR_CONFIG_DIR / "file_errors" / "does_not_exist.yaml"

        with self.assertRaises(ConfigFileError) as ctx:
            rc.instantiate(config_path, cli_overrides=False)

        self.assertIn("does_not_exist.yaml", str(ctx.exception))

    def test_validate__InvalidYamlSyntax__ReturnsMissingFieldsOrParseErrors(self):
        """Malformed YAML may be partially parsed, resulting in validation errors."""
        config_path = ERROR_CONFIG_DIR / "file_errors" / "invalid_yaml.yaml"

        # The YAML parser is lenient - it may parse partial content
        # This results in validation errors rather than ConfigFileError
        result = rc.validate(config_path)

        # Invalid YAML leads to incomplete/invalid config
        self.assertFalse(result.valid)

    def test_validate__EmptyFile__ReturnsAmbiguousTargetError(self):
        """Empty config file results in AmbiguousTargetError for missing root _target_."""
        config_path = ERROR_CONFIG_DIR / "file_errors" / "empty_file.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        # Empty file means no _target_ specified at root
        self.assertIsInstance(result.errors[0], AmbiguousTargetError)
        self.assertEqual(result.errors[0].field, "(root)")

    def test_compose__RefToNonexistentFile__RaisesRefResolutionError(self):
        """_ref_ pointing to missing file raises RefResolutionError during composition."""
        config_path = ERROR_CONFIG_DIR / "file_errors" / "ref_to_nonexistent.yaml"

        # RefResolutionError is raised during composition, not validation
        with self.assertRaises(RefResolutionError) as ctx:
            rc.validate(config_path)

        self.assertIn("does_not_exist.yaml", str(ctx.exception))


# =============================================================================
# TargetNotFoundError Tests
# =============================================================================


class TargetNotFoundErrorTests(ErrorIntegrationTestBase):
    """Tests for TargetNotFoundError scenarios."""

    def test_validate__UnknownTarget__ReturnsTargetNotFoundError(self):
        """Unregistered _target_ returns TargetNotFoundError."""
        config_path = ERROR_CONFIG_DIR / "target_errors" / "unknown_target.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)
        self.assertEqual(result.errors[0].target, "completely_unknown_target")

    def test_validate__UnknownNestedTarget__ReturnsTargetNotFoundErrorWithPath(self):
        """Unregistered nested _target_ returns error with correct path."""
        config_path = ERROR_CONFIG_DIR / "target_errors" / "unknown_nested_target.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TargetNotFoundError)
        self.assertEqual(result.errors[0].target, "unknown_optimizer_type")
        self.assertIn("optimizer", result.errors[0].config_path)

    def test_instantiate__UnknownTarget__RaisesTargetNotFoundError(self):
        """Instantiation with unknown target raises error."""
        config_path = ERROR_CONFIG_DIR / "target_errors" / "unknown_target.yaml"

        with self.assertRaises(TargetNotFoundError) as ctx:
            rc.instantiate(config_path, cli_overrides=False)

        self.assertEqual(ctx.exception.target, "completely_unknown_target")


# =============================================================================
# MissingFieldError Tests
# =============================================================================


class MissingFieldErrorTests(ErrorIntegrationTestBase):
    """Tests for MissingFieldError scenarios."""

    def test_validate__MissingRequiredField__ReturnsMissingFieldError(self):
        """Missing required field returns MissingFieldError."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "missing_required_field.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], MissingFieldError)
        self.assertEqual(result.errors[0].field, "layers")

    def test_validate__MissingMultipleFields__ReturnsAllErrors(self):
        """Multiple missing fields returns multiple errors."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "multiple_missing_fields.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertTrue(len(result.errors) >= 2)
        # Should have errors for both 'layers' and 'pretrained'
        missing_fields = {e.field for e in result.errors if isinstance(e, MissingFieldError)}
        self.assertIn("layers", missing_fields)
        self.assertIn("pretrained", missing_fields)

    def test_validate__MissingNestedField__ReturnsErrorWithPath(self):
        """Missing field in nested config includes correct path."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "nested_missing_field.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, MissingFieldError)
        # Path should indicate nested location
        self.assertIn("optimizer", error.config_path)

    def test_instantiate__MissingField__RaisesMissingFieldError(self):
        """Instantiation with missing field raises error."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "missing_required_field.yaml"

        with self.assertRaises(MissingFieldError) as ctx:
            rc.instantiate(config_path, cli_overrides=False)

        self.assertEqual(ctx.exception.field, "layers")


# =============================================================================
# TypeMismatchError Tests
# =============================================================================


class TypeMismatchErrorTests(ErrorIntegrationTestBase):
    """Tests for TypeMismatchError scenarios."""

    def test_validate__WrongFieldType_StringForInt__ReturnsTypeMismatchError(self):
        """String value for int field returns TypeMismatchError."""
        # Use a dict config to ensure the string is properly passed
        config = {
            "_target_": "resnet",
            "layers": "fifty",  # String instead of int
            "pretrained": False,
            "optimizer": {
                "_target_": "optimizer",
                "type": "adam",
                "learning_rate": 0.01,
                "weight_decay": 0.0001,
                "betas": [0.9, 0.999],
            },
            "scheduler": {
                "_target_": "scheduler",
                "type": "cosine",
                "warmup_epochs": 5,
                "min_lr": 0.00001,
            },
        }

        result = rc._validator.validate(config)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TypeMismatchError)
        self.assertEqual(result.errors[0].field, "layers")
        # expected can be a type or string representation
        self.assertIn("int", str(result.errors[0].expected).lower())

    def test_validate__WrongFieldType_IntForList__ReturnsTypeMismatchError(self):
        """Int value for list field returns TypeMismatchError."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "wrong_list_type.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TypeMismatchError)
        self.assertEqual(result.errors[0].field, "metrics")

    def test_validate__WrongFieldType_NestedConfig__ReturnsErrorWithPath(self):
        """Wrong type in nested config includes correct path."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "nested_wrong_type.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TypeMismatchError)
        # Path should indicate nested location
        self.assertIn("optimizer", error.config_path)

    def test_instantiate__WrongType__RaisesTypeMismatchError(self):
        """Instantiation with wrong type raises error."""
        # Use a dict config to ensure the string is properly passed
        config = {
            "_target_": "resnet",
            "layers": "fifty",  # String instead of int
            "pretrained": False,
            "optimizer": {
                "_target_": "optimizer",
                "type": "adam",
                "learning_rate": 0.01,
                "weight_decay": 0.0001,
                "betas": [0.9, 0.999],
            },
            "scheduler": {
                "_target_": "scheduler",
                "type": "cosine",
                "warmup_epochs": 5,
                "min_lr": 0.00001,
            },
        }

        with self.assertRaises(TypeMismatchError) as ctx:
            # Use the internal instantiator for dict configs
            rc._instantiator.instantiate(config)

        self.assertEqual(ctx.exception.field, "layers")


# =============================================================================
# AmbiguousTargetError Tests
# =============================================================================


class AmbiguousTargetErrorTests(ErrorIntegrationTestBase):
    """Tests for AmbiguousTargetError scenarios."""

    def test_validate__PolymorphicTypeNoTarget__ReturnsAmbiguousTargetError(self):
        """Polymorphic type hint without _target_ returns AmbiguousTargetError."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "abstract_type_no_target.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], AmbiguousTargetError)
        # ModelConfig has registered subclasses (resnet, vgg), so it's ambiguous
        self.assertEqual(result.errors[0].field, "model")

    def test_validate__PolymorphicInNestedConfig__ReturnsErrorWithPath(self):
        """Polymorphic type in nested config includes correct path."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "abstract_type_no_target.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, AmbiguousTargetError)
        self.assertIn("model", error.config_path)

    def test_instantiate__PolymorphicType__RaisesAmbiguousTargetError(self):
        """Instantiation with polymorphic type requires explicit _target_."""
        config_path = ERROR_CONFIG_DIR / "validation_errors" / "abstract_type_no_target.yaml"

        with self.assertRaises(AmbiguousTargetError) as ctx:
            rc.instantiate(config_path, cli_overrides=False)

        # Error should be about the model field
        self.assertEqual(ctx.exception.field, "model")


# =============================================================================
# TargetTypeMismatchError Tests
# =============================================================================


class TargetTypeMismatchErrorTests(ErrorIntegrationTestBase):
    """Tests for TargetTypeMismatchError scenarios."""

    def test_validate__WrongTargetClass__ReturnsTargetTypeMismatchError(self):
        """_target_ class doesn't match expected type returns error."""
        config_path = ERROR_CONFIG_DIR / "target_errors" / "wrong_target_type.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        self.assertIsInstance(result.errors[0], TargetTypeMismatchError)
        self.assertEqual(result.errors[0].target, "vgg")
        self.assertEqual(result.errors[0].expected_type, ResNet)

    def test_validate__SiblingClass__ReturnsTargetTypeMismatchError(self):
        """Sibling class (same parent, wrong type) returns error."""
        # TrainerApp expects ResNet, but we provide VGG (both are ModelConfig subclasses)
        config_path = ERROR_CONFIG_DIR / "target_errors" / "wrong_target_type.yaml"

        result = rc.validate(config_path)

        self.assertFalse(result.valid)
        error = result.errors[0]
        self.assertIsInstance(error, TargetTypeMismatchError)
        # VGG is sibling to ResNet (both inherit from ModelConfig)
        self.assertEqual(error.target_class, VGG)

    def test_instantiate__WrongTargetType__RaisesTargetTypeMismatchError(self):
        """Instantiation with wrong target type raises error."""
        config_path = ERROR_CONFIG_DIR / "target_errors" / "wrong_target_type.yaml"

        with self.assertRaises(TargetTypeMismatchError) as ctx:
            rc.instantiate(config_path, cli_overrides=False)

        self.assertEqual(ctx.exception.target, "vgg")


# =============================================================================
# TypeInferenceError Tests
# =============================================================================


class TypeInferenceErrorTests(ErrorIntegrationTestBase):
    """Tests for TypeInferenceError scenarios."""

    def test_validate__ImplicitNestedMissingField__ReturnsTypeInferenceError(self):
        """Implicit nested config missing field wrapped in TypeInferenceError."""
        # Create config with implicit type inference that fails validation
        config = {
            "_target_": "resnet",
            "layers": 50,
            "pretrained": False,
            "optimizer": {
                # Implicit inference will select Optimizer
                # But missing required fields
                "type": "adam",
                # Missing: learning_rate, weight_decay, betas
            },
            "scheduler": {
                "_target_": "scheduler",
                "type": "cosine",
                "warmup_epochs": 5,
                "min_lr": 0.00001,
            },
        }

        result = rc._validator.validate(config)

        self.assertFalse(result.valid)
        # Should get TypeInferenceError wrapping the MissingFieldError
        type_inference_errors = [e for e in result.errors if isinstance(e, TypeInferenceError)]
        self.assertTrue(len(type_inference_errors) >= 1)

    def test_validate__ImplicitNestedWrongType__ReturnsTypeInferenceError(self):
        """Implicit nested config with wrong type wrapped in error."""
        config = {
            "_target_": "resnet",
            "layers": 50,
            "pretrained": False,
            "optimizer": {
                # Implicit inference will select Optimizer
                "type": "adam",
                "learning_rate": "not_a_float",  # Wrong type!
                "weight_decay": 0.0001,
                "betas": [0.9, 0.999],
            },
            "scheduler": {
                "_target_": "scheduler",
                "type": "cosine",
                "warmup_epochs": 5,
                "min_lr": 0.00001,
            },
        }

        result = rc._validator.validate(config)

        self.assertFalse(result.valid)
        # Should get TypeInferenceError wrapping the TypeMismatchError
        type_inference_errors = [e for e in result.errors if isinstance(e, TypeInferenceError)]
        self.assertTrue(len(type_inference_errors) >= 1)


# =============================================================================
# InstantiationError Tests
# =============================================================================


@dataclass
class FailingConstructor:
    """A class that always fails during construction."""

    value: int

    def __post_init__(self):
        raise ValueError("Constructor failed intentionally!")


class InstantiationErrorTests(ErrorIntegrationTestBase):
    """Tests for InstantiationError scenarios."""

    def setUp(self):
        super().setUp()
        rc.register("failing_constructor", FailingConstructor)

    def test_instantiate__ConstructorRaises__RaisesInstantiationError(self):
        """Constructor that raises exception wrapped in InstantiationError."""
        config = {
            "_target_": "failing_constructor",
            "value": 42,
        }

        with self.assertRaises(InstantiationError) as ctx:
            # Use the internal instantiator for dict configs
            rc._instantiator.instantiate(config)

        self.assertIn("failing_constructor", ctx.exception.target)
        self.assertIn("Constructor failed intentionally", ctx.exception.reason)


# =============================================================================
# CircularRefError Tests
# =============================================================================


class CircularRefErrorTests(ErrorIntegrationTestBase):
    """Tests for CircularRefError scenarios."""

    def test_compose__DirectCircularRef__RaisesCircularRefError(self):
        """A -> B -> A circular reference raises error."""
        config_path = ERROR_CONFIG_DIR / "composition_errors" / "circular_ref_a.yaml"

        with self.assertRaises(CircularRefError) as ctx:
            rc.validate(config_path)

        # Chain should contain both files
        chain_str = str(ctx.exception)
        self.assertIn("circular_ref_a.yaml", chain_str)
        self.assertIn("circular_ref_b.yaml", chain_str)

    def test_compose__SelfReference__RaisesCircularRefError(self):
        """File referencing itself raises error."""
        config_path = ERROR_CONFIG_DIR / "composition_errors" / "self_reference.yaml"

        with self.assertRaises(CircularRefError) as ctx:
            rc.validate(config_path)

        # Chain should contain the self-referencing file
        chain_str = str(ctx.exception)
        self.assertIn("self_reference.yaml", chain_str)


# =============================================================================
# RefResolutionError Tests
# =============================================================================


class RefResolutionErrorTests(ErrorIntegrationTestBase):
    """Tests for RefResolutionError scenarios."""

    def test_compose__RefToNonexistentFile__RaisesRefResolutionError(self):
        """_ref_ to non-existent file raises error."""
        config_path = ERROR_CONFIG_DIR / "file_errors" / "ref_to_nonexistent.yaml"

        with self.assertRaises(RefResolutionError) as ctx:
            rc.validate(config_path)

        # The ref_to_nonexistent.yaml file references ./does_not_exist.yaml
        self.assertIn("does_not_exist.yaml", str(ctx.exception))


# =============================================================================
# RefAtRootError Tests
# =============================================================================


class RefAtRootErrorTests(ErrorIntegrationTestBase):
    """Tests for RefAtRootError scenarios."""

    def test_compose__RefAtRootLevel__RaisesRefAtRootError(self):
        """_ref_ at root level of config raises error."""
        config_path = ERROR_CONFIG_DIR / "composition_errors" / "ref_at_root.yaml"

        with self.assertRaises(RefAtRootError) as ctx:
            rc.validate(config_path)

        self.assertIn("ref_at_root.yaml", ctx.exception.file_path)


# =============================================================================
# RefInstanceConflictError Tests
# =============================================================================


class RefInstanceConflictErrorTests(ErrorIntegrationTestBase):
    """Tests for RefInstanceConflictError scenarios."""

    def test_compose__BothRefAndInstance__RaisesRefInstanceConflictError(self):
        """Both _ref_ and _instance_ in same block raises error."""
        config_path = ERROR_CONFIG_DIR / "composition_errors" / "ref_instance_conflict.yaml"

        with self.assertRaises(RefInstanceConflictError) as ctx:
            rc.validate(config_path)

        # Error should mention the conflict
        self.assertIn("_ref_", str(ctx.exception))
        self.assertIn("_instance_", str(ctx.exception))


# =============================================================================
# InstanceResolutionError Tests
# =============================================================================


class InstanceResolutionErrorTests(ErrorIntegrationTestBase):
    """Tests for InstanceResolutionError scenarios."""

    def test_compose__InstancePathNotFound__RaisesInstanceResolutionError(self):
        """_instance_ path doesn't exist raises error."""
        config_path = ERROR_CONFIG_DIR / "composition_errors" / "instance_not_found.yaml"

        with self.assertRaises(InstanceResolutionError) as ctx:
            rc.validate(config_path)

        self.assertIn("nonexistent_logger", ctx.exception.instance_path)


# =============================================================================
# CircularInstanceError Tests
# =============================================================================


class CircularInstanceErrorTests(ErrorIntegrationTestBase):
    """Tests for CircularInstanceError scenarios."""

    def test_compose__CircularInstance__RaisesCircularInstanceError(self):
        """Circular _instance_ dependency raises error."""
        config_path = ERROR_CONFIG_DIR / "composition_errors" / "circular_instance_a.yaml"

        with self.assertRaises(CircularInstanceError) as ctx:
            rc.validate(config_path)

        # Chain should be present
        self.assertTrue(len(ctx.exception.chain) >= 2)


# =============================================================================
# InvalidOverridePathError Tests
# =============================================================================


class InvalidOverridePathErrorTests(ErrorIntegrationTestBase):
    """Tests for InvalidOverridePathError scenarios."""

    def test_instantiate__OverrideNonexistentPath__RaisesInvalidOverridePathError(self):
        """Override targeting non-existent path raises error."""
        config_path = ERROR_CONFIG_DIR / "override_errors" / "valid_config_for_override.yaml"

        with self.assertRaises(InvalidOverridePathError) as ctx:
            rc.instantiate(
                config_path,
                overrides={"nonexistent.path.here": 42},
                cli_overrides=False,
            )

        self.assertIn("nonexistent", str(ctx.exception))

    def test_instantiate__OverrideIndexOutOfRange__RaisesInvalidOverridePathError(self):
        """Override with list index out of range raises error."""
        config_path = ERROR_CONFIG_DIR / "override_errors" / "valid_config_for_override.yaml"

        with self.assertRaises(InvalidOverridePathError) as ctx:
            rc.instantiate(
                config_path,
                overrides={"optimizer.betas[100]": 0.5},
                cli_overrides=False,
            )

        self.assertIn("100", str(ctx.exception))


# =============================================================================
# InvalidOverrideSyntaxError Tests
# =============================================================================


class InvalidOverrideSyntaxErrorTests(ErrorIntegrationTestBase):
    """Tests for InvalidOverrideSyntaxError scenarios."""

    def test_parse__MalformedKey__RaisesInvalidOverrideSyntaxError(self):
        """Malformed override key raises error."""
        from rconfig.override import parse_override_key

        # Test with malformed key that has invalid bracket syntax
        with self.assertRaises(InvalidOverrideSyntaxError):
            parse_override_key("malformed[.override")

    def test_parse__UnclosedBracket__RaisesInvalidOverrideSyntaxError(self):
        """Unclosed bracket in override raises error."""
        from rconfig.override import parse_override_key

        with self.assertRaises(InvalidOverrideSyntaxError):
            parse_override_key("optimizer.betas[0")
