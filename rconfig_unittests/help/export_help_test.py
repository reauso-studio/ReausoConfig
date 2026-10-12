"""Unit tests for help integration with export functions."""

import sys
import tempfile
from pathlib import Path
from unittest import TestCase

import rconfig as rc
from rconfig.help import FlatHelpIntegration, HelpIntegration
from rconfig.composition import Provenance


class ExportHelpTestBase(TestCase):
    """Base class for export help tests."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self._original_argv = sys.argv.copy()
        self._original_integration = rc.current_help_integration()

    def tearDown(self) -> None:
        """Restore original state."""
        sys.argv = self._original_argv
        rc.set_help_integration(FlatHelpIntegration())

    def _create_temp_config(self, content: str | None = None) -> Path:
        """Create a temporary config file."""
        if content is None:
            content = "key: value\nmodel:\n  lr: 0.001\n"
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        )
        temp_file.write(content)
        temp_file.close()
        return Path(temp_file.name)


class ToDictHelpTests(ExportHelpTestBase):
    """Tests for help integration with to_dict()."""

    def test_toDict__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in to_dict."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.to_dict(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_toDict__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
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
        result = rc.to_dict(config_path, cli_overrides=False)

        # Assert - integration should NOT be called when cli_overrides=False
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)


class ToYamlHelpTests(ExportHelpTestBase):
    """Tests for help integration with to_yaml()."""

    def test_toYaml__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in to_yaml."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.to_yaml(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_toYaml__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
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
        result = rc.to_yaml(config_path, cli_overrides=False)

        # Assert
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)


class ToJsonHelpTests(ExportHelpTestBase):
    """Tests for help integration with to_json()."""

    def test_toJson__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in to_json."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.to_json(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_toJson__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
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
        result = rc.to_json(config_path, cli_overrides=False)

        # Assert
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)


class ToTomlHelpTests(ExportHelpTestBase):
    """Tests for help integration with to_toml()."""

    def test_toToml__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in to_toml."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.to_toml(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_toToml__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
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
        result = rc.to_toml(config_path, cli_overrides=False)

        # Assert
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)


class ExportFunctionHelpTests(ExportHelpTestBase):
    """Tests for help integration with export()."""

    def test_export__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in export."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.export(config_path, rc.DictExporter(), cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_export__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
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
        result = rc.export(config_path, rc.DictExporter(), cli_overrides=False)

        # Assert
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)


class ToFileHelpTests(ExportHelpTestBase):
    """Tests for help integration with to_file()."""

    def test_toFile__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in to_file."""
        # Arrange
        config_path = self._create_temp_config()
        output_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        )
        output_file.close()
        output_path = Path(output_file.name)
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.to_file(config_path, output_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_toFile__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
        # Arrange
        config_path = self._create_temp_config()
        output_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        )
        output_file.close()
        output_path = Path(output_file.name)
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append("called")
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        rc.to_file(config_path, output_path, cli_overrides=False)

        # Assert
        self.assertEqual(len(call_log), 0)


class ToFilesHelpTests(ExportHelpTestBase):
    """Tests for help integration with to_files()."""

    def test_toFiles__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in to_files."""
        # Arrange
        config_path = self._create_temp_config()
        output_dir = tempfile.mkdtemp()
        output_root = Path(output_dir) / "config.yaml"
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.to_files(config_path, output_root, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_toFiles__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
        # Arrange
        config_path = self._create_temp_config()
        output_dir = tempfile.mkdtemp()
        output_root = Path(output_dir) / "config.yaml"
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append("called")
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        rc.to_files(config_path, output_root, cli_overrides=False)

        # Assert
        self.assertEqual(len(call_log), 0)


class ValidateHelpTests(ExportHelpTestBase):
    """Tests for help integration with validate()."""

    def test_validate__HelpFlagPresent__CallsIntegration(self):
        """Test that --help triggers help integration in validate."""
        # Arrange
        config_path = self._create_temp_config()
        call_log = []

        class TestIntegration(HelpIntegration):
            def integrate(self, provenance, config_path):
                call_log.append((provenance, config_path))
                sys.exit(0)

        rc.set_help_integration(TestIntegration())
        sys.argv = ["script.py", "--help"]

        # Act
        with self.assertRaises(SystemExit):
            rc.validate(config_path, cli_overrides=True)

        # Assert
        self.assertEqual(len(call_log), 1)
        self.assertIsInstance(call_log[0][0], Provenance)

    def test_validate__CliOverridesFalse__DoesNotCallIntegration(self):
        """Test that help is NOT triggered when cli_overrides=False."""
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
        result = rc.validate(config_path, cli_overrides=False)

        # Assert - integration should NOT be called when cli_overrides=False
        self.assertEqual(len(call_log), 0)
        self.assertIsNotNone(result)
