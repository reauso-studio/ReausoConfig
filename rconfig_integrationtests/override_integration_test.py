"""Integration tests for CLI override functionality.

These tests verify the override system works end-to-end using real YAML config files.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.case import TestCase
from unittest.mock import patch

import rconfig as rc
from rconfig import InvalidOverridePathError


# Test dataclasses
@dataclass
class ModelConfig:
    hidden_size: int
    dropout: float = 0.1


@dataclass
class TrainerConfig:
    model: ModelConfig
    epochs: int
    learning_rate: float = 0.001


# Path to config files directory
CONFIG_DIR = Path(__file__).parent / "config_files"


class OverrideIntegrationTests(TestCase):
    def setUp(self):
        rc._store._known_targets.clear()
        rc.register("model", ModelConfig)
        rc.register("trainer", TrainerConfig)

    def test_instantiate__OverrideTopLevelValue__ModifiesInstance(self):
        config_path = CONFIG_DIR / "trainer_config.yaml"

        trainer = rc.instantiate(
            config_path,
            overrides={"epochs": 50},
            cli_overrides=False,
        )

        self.assertEqual(trainer.epochs, 50)
        # Other values unchanged
        self.assertEqual(trainer.model.hidden_size, 256)

    def test_instantiate__OverrideNestedValue__ModifiesNestedInstance(self):
        config_path = CONFIG_DIR / "trainer_config.yaml"

        trainer = rc.instantiate(
            config_path,
            overrides={"model.hidden_size": 1024},
            cli_overrides=False,
        )

        self.assertEqual(trainer.model.hidden_size, 1024)
        # Other values unchanged
        self.assertEqual(trainer.epochs, 10)
        self.assertEqual(trainer.model.dropout, 0.2)

    def test_instantiate__OverrideMultipleValues__ModifiesAllValues(self):
        config_path = CONFIG_DIR / "trainer_config.yaml"

        trainer = rc.instantiate(
            config_path,
            overrides={
                "epochs": 100,
                "model.hidden_size": 512,
                "model.dropout": 0.5,
            },
            cli_overrides=False,
        )

        self.assertEqual(trainer.epochs, 100)
        self.assertEqual(trainer.model.hidden_size, 512)
        self.assertEqual(trainer.model.dropout, 0.5)

    def test_instantiate__OverrideWithStringValue__CoercesToCorrectType(self):
        config_path = CONFIG_DIR / "trainer_config.yaml"

        trainer = rc.instantiate(
            config_path,
            overrides={"learning_rate": "0.01"},
            cli_overrides=False,
        )

        self.assertEqual(trainer.learning_rate, 0.01)
        self.assertIsInstance(trainer.learning_rate, float)

    def test_instantiate__InvalidOverridePath__RaisesError(self):
        config_path = CONFIG_DIR / "trainer_config.yaml"

        with self.assertRaises(InvalidOverridePathError):
            rc.instantiate(
                config_path,
                overrides={"model.nonexistent": 123},
                cli_overrides=False,
            )

    def test_instantiate__OverrideWithImplicitTarget__Works(self):
        config_path = CONFIG_DIR / "trainer_implicit_config.yaml"

        trainer = rc.instantiate(
            config_path,
            overrides={"model.hidden_size": 2048},
            cli_overrides=False,
        )

        self.assertEqual(trainer.model.hidden_size, 2048)
        self.assertEqual(trainer.epochs, 20)

    def test_workflow__ValidateThenOverrideInstantiate__Works(self):
        config_path = CONFIG_DIR / "trainer_config.yaml"

        # Step 1: Validate (dry-run)
        result = rc.validate(config_path)
        self.assertTrue(result.valid)

        # Step 2: Instantiate with overrides
        trainer = rc.instantiate(
            config_path,
            overrides={"epochs": 200},
            cli_overrides=False,
        )

        # Verify override was applied
        self.assertEqual(trainer.epochs, 200)


@dataclass
class OptionalModelConfig:
    hidden_size: int
    seed: int | None = None


class OptionalFieldOverrideIntegrationTests(TestCase):
    """Tests for CLI overrides on ``X | None`` fields."""

    def setUp(self):
        rc._store._known_targets.clear()
        rc.register("optional_model", OptionalModelConfig)

    def test_instantiate__CliOverrideOnOptionalIntField__CoercesToInt(self):
        """Test that a CLI override on an ``int | None`` field is coerced to int."""
        # Arrange
        config_path = CONFIG_DIR / "optional_field_config.yaml"

        # Act
        with patch.object(sys, "argv", ["train.py", "seed=42"]):
            model = rc.instantiate(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(model.seed, 42)
