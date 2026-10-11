"""Tests for pu_venvcheck.py."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pu_venvcheck  # noqa: E402  pylint: disable=wrong-import-position


class TestIsValidVenv(unittest.TestCase):
    """is_valid_venv() mirroring common.ps1's own checks exactly."""

    def test_not_set(self):
        self.assertEqual(pu_venvcheck.is_valid_venv(None), (False, "not set"))
        self.assertEqual(pu_venvcheck.is_valid_venv(""), (False, "not set"))

    def test_not_found(self):
        valid, reason = pu_venvcheck.is_valid_venv("C:/nonexistent/python.exe")
        self.assertFalse(valid)
        self.assertIn("not found", reason)

    def test_not_an_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "python.bat"
            fake.write_text("echo hi", encoding="utf-8")
            valid, reason = pu_venvcheck.is_valid_venv(str(fake))
            self.assertFalse(valid)
            self.assertIn("not an .exe file", reason)

    def test_no_sibling_activate(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "python.exe"
            fake.write_text("", encoding="utf-8")
            valid, reason = pu_venvcheck.is_valid_venv(str(fake))
            self.assertFalse(valid)
            self.assertIn("no 'activate' next to it", reason)

    def test_wrong_python_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "python.exe"
            fake.write_text("", encoding="utf-8")
            (pathlib.Path(tmp) / "activate").write_text("", encoding="utf-8")
            fake_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python 3.11.5\n", stderr="")
            with mock.patch.object(pu_venvcheck.subprocess, "run", return_value=fake_result):
                valid, reason = pu_venvcheck.is_valid_venv(str(fake))
            self.assertFalse(valid)
            self.assertIn("not Python 3.13.x", reason)

    def test_valid_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "python.exe"
            fake.write_text("", encoding="utf-8")
            (pathlib.Path(tmp) / "activate").write_text("", encoding="utf-8")
            fake_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python 3.13.3\n", stderr="")
            with mock.patch.object(pu_venvcheck.subprocess, "run", return_value=fake_result):
                valid, reason = pu_venvcheck.is_valid_venv(str(fake))
            self.assertTrue(valid)
            self.assertIsNone(reason)


class TestCheckRequirements(unittest.TestCase):
    """check_requirements() against a fake pip list + fake requirements.txt."""

    def _write_requirements(self, tmp, text):
        path = pathlib.Path(tmp) / "requirements.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def _mock_pip_list(self, packages):
        payload = json.dumps([{"name": name, "version": version}
                               for name, version in packages.items()])
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=payload, stderr="")

    def test_exact_match_all_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            req_path = self._write_requirements(tmp, "aiohttp>=3.9\nnumpy>=1.26\n")
            fake_result = self._mock_pip_list({"aiohttp": "3.10.0", "numpy": "1.26.4"})
            with mock.patch.object(pu_venvcheck.subprocess, "run", return_value=fake_result):
                unmet = pu_venvcheck.check_requirements("python.exe", req_path)
            self.assertEqual(unmet, [])

    def test_missing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            req_path = self._write_requirements(tmp, "aiohttp>=3.9\n")
            fake_result = self._mock_pip_list({})
            with mock.patch.object(pu_venvcheck.subprocess, "run", return_value=fake_result):
                unmet = pu_venvcheck.check_requirements("python.exe", req_path)
            self.assertEqual(unmet, ["aiohttp (missing)"])

    def test_version_too_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            req_path = self._write_requirements(tmp, "aiohttp>=3.9\n")
            fake_result = self._mock_pip_list({"aiohttp": "3.8.0"})
            with mock.patch.object(pu_venvcheck.subprocess, "run", return_value=fake_result):
                unmet = pu_venvcheck.check_requirements("python.exe", req_path)
            self.assertEqual(len(unmet), 1)
            self.assertIn("aiohttp", unmet[0])
            self.assertIn("3.8.0", unmet[0])

    def test_comments_and_blank_lines_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            req_path = self._write_requirements(
                tmp, "# a comment\n\naiohttp>=3.9\n\n# another\n")
            fake_result = self._mock_pip_list({"aiohttp": "3.10.0"})
            with mock.patch.object(pu_venvcheck.subprocess, "run", return_value=fake_result):
                unmet = pu_venvcheck.check_requirements("python.exe", req_path)
            self.assertEqual(unmet, [])

    def test_pip_failure_assumes_all_unmet(self):
        with tempfile.TemporaryDirectory() as tmp:
            req_path = self._write_requirements(tmp, "aiohttp>=3.9\nnumpy>=1.26\n")
            with mock.patch.object(
                    pu_venvcheck.subprocess, "run",
                    side_effect=subprocess.SubprocessError("boom")):
                unmet = pu_venvcheck.check_requirements("python.exe", req_path)
            self.assertEqual(len(unmet), 2)


class TestRunSetupWizard(unittest.TestCase):
    """run_setup_wizard()'s marker-line scraping."""

    def test_captures_marker_line_among_other_output(self):
        class FakeProc:  # pylint: disable=too-few-public-methods
            stdout = iter([
                "Some wizard output\n",
                "More output\n",
                "VENV_PYTHON=C:\\fs\\python\\psxhacks-venv-2026-01-01\\Scripts\\python.exe\n",
                "Press Enter to close\n",
            ])

            def wait(self):
                return 0

        with mock.patch.object(pu_venvcheck.subprocess, "Popen", return_value=FakeProc()):
            result = pu_venvcheck.run_setup_wizard("setup_python_venv.ps1")
        self.assertEqual(
            result, "C:\\fs\\python\\psxhacks-venv-2026-01-01\\Scripts\\python.exe")

    def test_no_marker_line_returns_none(self):
        class FakeProc:  # pylint: disable=too-few-public-methods
            stdout = iter(["Some output\n", "No marker here\n"])

            def wait(self):
                return 1

        with mock.patch.object(pu_venvcheck.subprocess, "Popen", return_value=FakeProc()):
            result = pu_venvcheck.run_setup_wizard("setup_python_venv.ps1")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
