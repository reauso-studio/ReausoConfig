"""Unit tests for ConfigCoercer."""

from dataclasses import dataclass
from typing import Any
from unittest import TestCase

from rconfig.coercion import ConfigCoercer
from rconfig.errors import TypeMismatchError, ValueCoercionError
from rconfig.target import TargetRegistry


@dataclass
class Server:
    port: int
    debug: bool = False


@dataclass
class App:
    server: Server
    name: str
    ports: list[int]
    limits: dict[str, int]
    extra: Any = None
    raw: dict | None = None


class ConfigCoercerTests(TestCase):
    """Tests for coercing string values in a config tree."""

    def setUp(self) -> None:
        self.store = TargetRegistry()
        self.store.clear()
        self.store.register("app", App)
        self.coercer = ConfigCoercer(self.store)

    def _config(self, **fields: Any) -> dict[str, Any]:
        """Build an app config with defaults for all fields."""
        config = {
            "_target_": "app",
            "server": {"port": 80},
            "name": "app",
            "ports": [80],
            "limits": {"cpu": 1},
        }
        config.update(fields)
        return config

    def test_coerced__InferredNestedTargetWithoutRegistration__CoercesField(self):
        """Test that nested classes are found from the parent's type hint."""
        # Arrange
        config = self._config(server={"port": "9000", "debug": "yes"})

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(result.config["server"], {"port": 9000, "debug": True})
        self.assertNotIn("server", self.store.known_targets)

    def test_coerced__TypedListAndDictItems__CoercesEachItem(self):
        """Test list[int] items and dict[str, int] values."""
        # Arrange
        config = self._config(ports=["80", 443], limits={"cpu": "2"})

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(result.config["ports"], [80, 443])
        self.assertEqual(result.config["limits"], {"cpu": 2})

    def test_coerced__StrAnyAndUntypedDict__LeavesStringsUnchanged(self):
        """Test that str, Any and untyped dict values are never converted."""
        # Arrange
        config = self._config(name="123", extra="false", raw={"flag": "false"})

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(result.config["name"], "123")
        self.assertEqual(result.config["extra"], "false")
        self.assertEqual(result.config["raw"], {"flag": "false"})

    def test_coerced__ConvertedValues__ReportsPathsAndKeepsInputUnchanged(self):
        """Test that converted paths are reported and the input is not mutated."""
        # Arrange
        config = self._config(server={"port": "9000"}, ports=["1", "2"])

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(dict(result.coerced_paths), {"server.port": 9000, "ports[0]": 1, "ports[1]": 2})
        self.assertEqual(config["server"]["port"], "9000")

    def test_coerced__InvalidValueFromInterpolation__ReportsErrorWithExpression(self):
        """Test that errors name the field, the value and the unresolved expression."""
        # Arrange
        config = self._config(server={"port": "eighty"})
        unresolved = self._config(server={"port": "${env:APP_PORT ?: 80}"})

        # Act
        result = self.coercer.coerced(config, unresolved)

        # Assert
        self.assertEqual(len(result.errors), 1)
        error = result.errors[0]
        self.assertIsInstance(error, ValueCoercionError)
        self.assertIsInstance(error, TypeMismatchError)
        self.assertEqual(error.field, "port")
        self.assertEqual(error.config_path, "server.port")
        self.assertEqual(error.env_vars, ("APP_PORT",))
        self.assertIn("APP_PORT", str(error))

    def test_coerced__InvalidListItem__ReportsIndexedField(self):
        """Test that list item errors carry the item index."""
        # Arrange
        config = self._config(ports=["80", "x"])

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(result.errors[0].field, "ports[1]")

    def test_coerced__UnregisteredRootTarget__ReturnsConfigUnchanged(self):
        """Test that configs without a known target are left alone."""
        # Arrange
        config = {"_target_": "unknown", "port": "80"}

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(result.config, config)
        self.assertEqual(result.errors, ())

    def test_coerced__InstanceReference__IsNotDescended(self):
        """Test that _instance_ nodes are left for instantiation."""
        # Arrange
        config = self._config(server={"_instance_": "/shared/server"})

        # Act
        result = self.coercer.coerced(config)

        # Assert
        self.assertEqual(result.config["server"], {"_instance_": "/shared/server"})
