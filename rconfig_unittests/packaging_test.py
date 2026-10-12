"""Tests for package metadata shipped with rconfig."""

from pathlib import Path
from unittest import TestCase

import rconfig


class PackagingTests(TestCase):
    """Tests for files that must ship inside the rconfig package."""

    def test_package__PyTypedMarker__Exists(self):
        """Test that the PEP 561 py.typed marker exists in the package."""
        # Arrange
        package_dir = Path(rconfig.__file__).parent

        # Act
        marker_exists = (package_dir / "py.typed").is_file()

        # Assert
        self.assertTrue(marker_exists)
