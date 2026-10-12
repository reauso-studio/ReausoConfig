"""Integration tests for ReausoConfig embedded as a library in a host program.

A host program (web app, worker, test runner) owns sys.argv. These tests simulate
config loading inside such a program, e.g. at import of a Django settings module
while ``python manage.py migrate --help verbosity=2`` is running.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import rconfig as rc
from rconfig.help import FlatHelpIntegration


# Path to embedding config files directory
CONFIG_DIR = Path(__file__).parent / "config_files" / "embedding"


@dataclass
class EmbeddedApp:
    """Application config loaded by a host program."""

    name: str
    port: int


class EmbeddedLibraryIntegrationTests(TestCase):
    """Tests for loading config without interfering with the host program."""

    def setUp(self) -> None:
        self._original_argv = sys.argv.copy()
        rc._store._known_targets.clear()
        rc.register("embedded_app", EmbeddedApp)
        rc.set_help_integration(FlatHelpIntegration())
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("RCT_APP_NAME", None)

    def tearDown(self) -> None:
        self._env_patch.stop()
        sys.argv = self._original_argv
        rc.set_help_integration(FlatHelpIntegration())

    def test_instantiate__HostArgvWithHelpAndKeyValue__LeavesArgvAndProcessAlone(self) -> None:
        """Test that the host's --help and key=value arguments are not touched by default."""
        # Arrange
        host_argv = ["manage.py", "migrate", "--help", "verbosity=2"]
        sys.argv = list(host_argv)

        # Act
        result = rc.instantiate(CONFIG_DIR / "app.yaml")

        # Assert
        self.assertEqual(result.port, 8000)
        self.assertEqual(sys.argv, host_argv)

    def test_instantiate__HostArgvWithShortHelp__LeavesArgvAndProcessAlone(self) -> None:
        """Test that the host's -h flag is not touched by default."""
        # Arrange
        host_argv = ["worker.py", "-h"]
        sys.argv = list(host_argv)

        # Act
        rc.instantiate(CONFIG_DIR / "app.yaml")

        # Assert
        self.assertEqual(sys.argv, host_argv)

    def test_instantiate__CliOverridesDisabledWithHostHelp__LeavesArgvAlone(self) -> None:
        """Test that cli_overrides=False leaves --help and key=value arguments untouched."""
        # Arrange
        host_argv = ["manage.py", "migrate", "--help", "verbosity=2"]
        sys.argv = list(host_argv)

        # Act
        result = rc.instantiate(CONFIG_DIR / "app.yaml", cli_overrides=False)

        # Assert
        self.assertEqual(result.port, 8000)
        self.assertEqual(sys.argv, host_argv)

    def test_instantiate__CliOverridesEnabledWithValidOverride__AppliesOverride(self) -> None:
        """Test that explicitly enabled CLI overrides still apply."""
        # Arrange
        sys.argv = ["train.py", "port=9000"]

        # Act
        result = rc.instantiate(CONFIG_DIR / "app.yaml", cli_overrides=True)

        # Assert
        self.assertEqual(result.port, 9000)
