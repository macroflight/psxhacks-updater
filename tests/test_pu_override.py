"""Tests for pu_override.py."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pu_override  # noqa: E402  pylint: disable=wrong-import-position


class TestFindVariableLine(unittest.TestCase):
    """find_variable_line() against active/commented/absent states."""

    def test_active_line(self):
        lines = ['$SimBase = "C:\\fs"\n', '$PsxhacksPython = "C:\\old\\python.exe"\n', "\n"]
        self.assertEqual(pu_override.find_variable_line(lines, "PsxhacksPython"), 1)

    def test_commented_out_no_space(self):
        lines = ["# comment\n", '#$PsxhacksPython = "C:\\venv\\Scripts\\python.exe"\n']
        self.assertEqual(pu_override.find_variable_line(lines, "PsxhacksPython"), 1)

    def test_commented_out_with_space(self):
        lines = ['# $PsxhacksPython = "C:\\venv\\Scripts\\python.exe"\n']
        self.assertEqual(pu_override.find_variable_line(lines, "PsxhacksPython"), 0)

    def test_absent(self):
        lines = ['$SimBase = "C:\\fs"\n', '$AerowinxDir = "C:\\PSX"\n']
        self.assertIsNone(pu_override.find_variable_line(lines, "PsxhacksPython"))

    def test_does_not_match_a_different_variable_with_shared_prefix(self):
        lines = ['$PsxhacksPythonExtra = "something"\n']
        self.assertIsNone(pu_override.find_variable_line(lines, "PsxhacksPython"))


class TestSetVariable(unittest.TestCase):
    """set_variable()'s in-place rewrite, preserving everything else."""

    def _write(self, tmp, content):
        path = pathlib.Path(tmp) / "psxhacks-start-override.ps1"
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return path

    def test_rewrites_active_line_preserving_rest_of_file_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = (
                '$SimBase = "C:\\fs"\n'
                '$PsxhacksPython = "C:\\old\\Scripts\\python.exe"\n'
                '$AerowinxDir = "C:\\PSX"\n'
            )
            path = self._write(tmp, original)
            new_path = 'C:\\fs\\python\\psxhacks-venv-2026-01-01\\Scripts\\python.exe'

            self.assertTrue(pu_override.set_variable(path, "PsxhacksPython", new_path))

            result = path.read_text(encoding="utf-8")
            expected = (
                '$SimBase = "C:\\fs"\n'
                f'$PsxhacksPython = "{new_path}"\n'
                '$AerowinxDir = "C:\\PSX"\n'
            )
            self.assertEqual(result, expected)

    def test_uncomments_a_commented_out_line_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = (
                '$SimBase = "C:\\fs"\r\n'
                '#$PsxhacksPython = "$SimBase\\python\\psxhacks-venv-YYYY-MM-DD\\Scripts\\python.exe"\r\n'
                '$AerowinxDir = "C:\\PSX"\r\n'
            )
            path = self._write(tmp, original)
            new_path = 'C:\\fs\\python\\psxhacks-venv-2026-01-01\\Scripts\\python.exe'

            self.assertTrue(pu_override.set_variable(path, "PsxhacksPython", new_path))

            raw = path.read_bytes()
            self.assertEqual(raw.count(b"\r\n"), 3)
            with open(path, "r", encoding="utf-8", newline="") as handle:
                result = handle.read()
            expected = (
                '$SimBase = "C:\\fs"\r\n'
                f'$PsxhacksPython = "{new_path}"\r\n'
                '$AerowinxDir = "C:\\PSX"\r\n'
            )
            self.assertEqual(result, expected)

    def test_handles_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = '#$PsxhacksPython = "..."\n'
            path = self._write(tmp, original)
            new_path = 'C:\\Program Files\\psxhacks\\venv\\Scripts\\python.exe'

            self.assertTrue(pu_override.set_variable(path, "PsxhacksPython", new_path))
            self.assertIn(f'"{new_path}"', path.read_text(encoding="utf-8"))

    def test_returns_false_and_does_not_modify_file_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = '$SimBase = "C:\\fs"\n$AerowinxDir = "C:\\PSX"\n'
            path = self._write(tmp, original)

            self.assertFalse(pu_override.set_variable(path, "PsxhacksPython", "whatever"))
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_format_variable_line(self):
        self.assertEqual(
            pu_override.format_variable_line("PsxhacksPython", 'C:\\venv\\python.exe'),
            '$PsxhacksPython = "C:\\venv\\python.exe"')


class TestGetVariableValue(unittest.TestCase):
    """get_variable_value() reading back a currently-active value."""

    def _write(self, tmp, content):
        path = pathlib.Path(tmp) / "psxhacks-start-override.ps1"
        path.write_text(content, encoding="utf-8")
        return path

    def test_active_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '$PsxhacksPython = "C:\\venv\\Scripts\\python.exe"\n')
            self.assertEqual(
                pu_override.get_variable_value(path, "PsxhacksPython"),
                "C:\\venv\\Scripts\\python.exe")

    def test_commented_out_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '#$PsxhacksPython = "C:\\venv\\Scripts\\python.exe"\n')
            self.assertIsNone(pu_override.get_variable_value(path, "PsxhacksPython"))

    def test_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '$SimBase = "C:\\fs"\n')
            self.assertIsNone(pu_override.get_variable_value(path, "PsxhacksPython"))

    def test_missing_file_returns_none(self):
        self.assertIsNone(
            pu_override.get_variable_value("/nonexistent/override.ps1", "PsxhacksPython"))


if __name__ == "__main__":
    unittest.main()
