"""Integration tests for behaviour relied on when embedding ReausoConfig in an application.

These verify properties an embedding application depends on: env values are
re-read on every load, nested dataclasses need no registration, raising resolvers
fail loudly, and registrations are idempotent.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import rconfig as rc
from rconfig.errors import ResolverExecutionError


# Path to config files directories
CONFIG_DIR = Path(__file__).parent / "config_files"
EMBEDDING_DIR = CONFIG_DIR / "embedding"


@dataclass
class EmbeddedApp:
    """Application config with an env-sourced name."""

    name: str
    port: int


@dataclass
class ClaimsDatabase:
    """Nested config class that is intentionally never registered."""

    host: str
    port: int


@dataclass
class ClaimsApp:
    """Root config class whose nested section is inferred from the type hint."""

    database: ClaimsDatabase


@dataclass
class ClaimsResolver:
    """Config class whose value comes from a resolver."""

    value: int


def _raising_resolver() -> int:
    """Resolver that always fails."""
    raise RuntimeError("secret backend unavailable")


class EmbeddingClaimsIntegrationTests(TestCase):
    """Tests for properties an embedding application relies on."""

    def setUp(self) -> None:
        rc._store._known_targets.clear()
        rc.register("embedded_app", EmbeddedApp)
        rc.register("claims_app", ClaimsApp)
        rc.register("claims_resolver", ClaimsResolver)
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        try:
            rc.unregister_resolver("rct_boom")
        except KeyError:
            pass

    def test_instantiate__EnvChangedBetweenLoads__UsesNewValue(self) -> None:
        """Test that the composition cache never serves a stale env value (N1)."""
        # Arrange
        config_path = EMBEDDING_DIR / "app.yaml"
        os.environ["RCT_APP_NAME"] = "first"
        first = rc.instantiate(config_path, cli_overrides=False)
        os.environ["RCT_APP_NAME"] = "second"

        # Act
        second = rc.instantiate(config_path, cli_overrides=False)

        # Assert
        self.assertEqual(first.name, "first")
        self.assertEqual(second.name, "second")

    def test_instantiate__UnregisteredNestedDataclassWithoutTarget__InfersFromTypeHint(self) -> None:
        """Test that a nested dataclass needs neither register() nor _target_ (N2)."""
        # Act
        result = rc.instantiate(EMBEDDING_DIR / "inferred_nested.yaml", cli_overrides=False)

        # Assert
        self.assertIsInstance(result.database, ClaimsDatabase)
        self.assertEqual(result.database.host, "localhost")
        self.assertEqual(result.database.port, 5432)

    def test_instantiate__RaisingResolverWithElvisFallback__RaisesResolverExecutionError(self) -> None:
        """Test that ?: does not swallow a failing resolver (N3)."""
        # Arrange
        rc.register_resolver("rct_boom", func=_raising_resolver)

        # Act & Assert
        with self.assertRaises(ResolverExecutionError) as ctx:
            rc.instantiate(EMBEDDING_DIR / "raising_resolver.yaml", cli_overrides=False)

        self.assertIsInstance(ctx.exception.original_error, RuntimeError)

    def test_register__SameTargetTwice__IsIdempotent(self) -> None:
        """Test that re-registering a target (e.g. on module reload) is harmless (N4)."""
        # Arrange
        rc.register("embedded_app", EmbeddedApp)

        # Act
        rc.register("embedded_app", EmbeddedApp)

        # Assert
        self.assertIs(rc.known_targets()["embedded_app"].target_class, EmbeddedApp)

    def test_registerResolver__SameNameTwice__LastRegistrationWins(self) -> None:
        """Test that re-registering a resolver replaces it without error (N4)."""
        # Arrange
        rc.register_resolver("rct_boom", func=_raising_resolver)

        # Act
        rc.register_resolver("rct_boom", func=lambda: 7)

        # Assert
        result = rc.instantiate(EMBEDDING_DIR / "raising_resolver.yaml", cli_overrides=False)
        self.assertEqual(result.value, 7)
