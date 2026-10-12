"""Unit tests for help integration with instantiate() function."""

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock

import rconfig as rc
from rconfig.help import FlatHelpIntegration, HelpIntegration
from rconfig.composition import Provenance


# Test dataclass for instantiate tests
@dataclass
class SimpleConfig:
    key: str = "default"


class InstantiateHelpTests(TestCase):
    """Tests for help handling in rc.instantiate(, cli_overrides=True)."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self._original_argv = sys.argv.copy()
        self._original_integration = rc.current_help_integration()
        # Register the test target
        rc._store._known_targets.clear()
        rc.register("simple_config", SimpleConfig)

    def tearDown(self) -> None:
        """Restore original state."""
        sys.argv = self._original_argv
        rc.set_help_integration(FlatHelpIntegration())

    def _create_temp_config(self, content: str | None = None) -> Path:
        """Create a temporary config file."""
        if content is None:
            content = "_target_: simple_config\nkey: value\n"
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        )
        temp_file.write(content)
        temp_file.close()
        return Path(temp_file.name)

    # === Help Flag Detection Tests ===

    def test_instantiate__HelpFlagPresent__CallsIntegration(self):
        """Test that help integration is called when --help is in sys.argv."""
        # Arrange
        config_path = self._create_temp_config("_target_: simple_config\nmodel:\n  lr: 0.001\n")
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_instantiate__ShortHelpFlag__CallsIntegration(self):
        """Test that help integration is called when -h is in sys.argv."""
        # Arrange
        config_path = self._create_temp_config("_target_: simple_config\nmodel:\n  lr: 0.001\n")
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "-h"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)

    def test_instantiate__NoHelpFlag__DoesNotCallIntegration(self):
        """Test that help integration is not called without --help."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append("called")
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py"]

        # Act
        result = rc.instantiate(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)

    def test_instantiate__HelpWithCliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is not triggered when cli_overrides=False."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append("called")
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        result = rc.instantiate(config_path, cli_overrides=False)

        # Assert - integration should NOT be called when cli_overrides=False
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)


class SysArgvManipulationTests(TestCase):
    """Tests for sys.argv handling in help system."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self._original_argv = sys.argv.copy()
        self._original_integration = rc.current_help_integration()
        # Register the test target
        rc._store._known_targets.clear()
        rc.register("simple_config", SimpleConfig)

    def tearDown(self) -> None:
        """Restore original state."""
        sys.argv = self._original_argv
        rc.set_help_integration(FlatHelpIntegration())

    def _create_temp_config(self, content: str | None = None) -> Path:
        """Create a temporary config file."""
        if content is None:
            content = "_target_: simple_config\nkey: value\n"
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        )
        temp_file.write(content)
        temp_file.close()
        return Path(temp_file.name)

    def test_consumeHelpFlag__HelpInArgv__RemovesHelp(self):
        """Test that --help is removed from sys.argv when consume_help_flag=True."""
        # Arrange
        config_path = self._create_temp_config()
        argv_during_integrate = []

        class TestIntegration(HelpIntegration):
            def __init__(self):
                super().__init__(consume_help_flag=True)

            def integrate(self, provenance, config_path):
                argv_during_integrate.extend(sys.argv)
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert - --help should have been removed
        self.assertNotIn("--help", argv_during_integrate)

    def test_consumeHelpFlag__ShortHelpInArgv__RemovesShortHelp(self):
        """Test that -h is removed from sys.argv when consume_help_flag=True."""
        # Arrange
        config_path = self._create_temp_config()
        argv_during_integrate = []

        class TestIntegration(HelpIntegration):
            def __init__(self):
                super().__init__(consume_help_flag=True)

            def integrate(self, provenance, config_path):
                argv_during_integrate.extend(sys.argv)
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "-h"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert - -h should have been removed
        self.assertNotIn("-h", argv_during_integrate)

    def test_consumeHelpFlag__MultipleHelpFlags__RemovesAll(self):
        """Test that multiple --help flags are all removed."""
        # Arrange
        config_path = self._create_temp_config()
        argv_during_integrate = []

        class TestIntegration(HelpIntegration):
            def __init__(self):
                super().__init__(consume_help_flag=True)

            def integrate(self, provenance, config_path):
                argv_during_integrate.extend(sys.argv)
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help", "-h", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert - all help flags should have been removed
        self.assertNotIn("--help", argv_during_integrate)
        self.assertNotIn("-h", argv_during_integrate)

    def test_consumeHelpFlag__HelpWithOtherArgs__OnlyRemovesHelp(self):
        """Test that other args are preserved when removing --help."""
        # Arrange
        config_path = self._create_temp_config()
        argv_during_integrate = []

        class TestIntegration(HelpIntegration):
            def __init__(self):
                super().__init__(consume_help_flag=True)

            def integrate(self, provenance, config_path):
                argv_during_integrate.extend(sys.argv)
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--verbose", "--help", "key=override"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert - --help removed but other args preserved
        self.assertNotIn("--help", argv_during_integrate)
        self.assertIn("script.py", argv_during_integrate)
        self.assertIn("--verbose", argv_during_integrate)
        self.assertIn("key=override", argv_during_integrate)

    def test_consumeHelpFlagFalse__HelpInArgv__PreservesHelp(self):
        """Test that --help is preserved when consume_help_flag=False."""
        # Arrange
        config_path = self._create_temp_config()
        argv_during_integrate = []

        class TestIntegration(HelpIntegration):
            def __init__(self):
                super().__init__(consume_help_flag=False)

            def integrate(self, provenance, config_path):
                argv_during_integrate.extend(sys.argv)
                sys.exit(0)  # Exit to prevent further processing

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.instantiate(config_path, cli_overrides=True)

        # Assert - --help should still be in argv when integrate was called
        self.assertIn("--help", argv_during_integrate)
