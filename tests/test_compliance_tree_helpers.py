"""Behavior of the compliance scanner's PATH and process-directory helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_compliance_tree as scanner  # resolved through the path set above


class SafeSearchPathTests(unittest.TestCase):
    """A relative PATH entry resolves against a working directory the candidate can control."""

    def test_relative_entries_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as candidate, tempfile.TemporaryDirectory() as outside:
            path_value = os.pathsep.join(["bin", f'"{outside}"', "", outside])
            with mock.patch.dict(os.environ, {"PATH": path_value}):
                entries = scanner._safe_search_path(Path(candidate)).split(os.pathsep)
        resolved_outside = str(Path(outside).resolve())
        self.assertEqual(entries, [resolved_outside, resolved_outside])

    def test_entries_inside_the_candidate_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as candidate:
            inside = Path(candidate) / "bin"
            inside.mkdir()
            with mock.patch.dict(os.environ, {"PATH": str(inside)}):
                self.assertEqual(scanner._safe_search_path(Path(candidate)), "")


class SafeExecutionDirectoryTests(unittest.TestCase):
    """An unset TEMP no longer selects the current directory."""

    def test_unset_temp_uses_the_system_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as candidate:
            environment = {key: value for key, value in os.environ.items() if key != "TEMP"}
            with mock.patch.dict(os.environ, environment, clear=True):
                directory = scanner._safe_execution_directory(Path(candidate), sys.executable)
        self.assertEqual(directory, Path(tempfile.gettempdir()).resolve())


if __name__ == "__main__":
    unittest.main()
