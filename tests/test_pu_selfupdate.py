"""Tests for pu_selfupdate.py."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pu_github  # noqa: E402  pylint: disable=wrong-import-position
import pu_selfupdate  # noqa: E402  pylint: disable=wrong-import-position


class TestVersionComparison(unittest.TestCase):
    """_parse_tag_version()/is_newer() against sample tag shapes."""

    def test_newer_release_tag(self):
        self.assertTrue(pu_selfupdate.is_newer("psxhacks-updater-v1.2.3", "1.2.2"))

    def test_older_release_tag(self):
        self.assertFalse(pu_selfupdate.is_newer("psxhacks-updater-v1.2.3", "1.2.4"))

    def test_equal_release_tag_is_not_newer(self):
        self.assertFalse(pu_selfupdate.is_newer("psxhacks-updater-v1.2.3", "1.2.3"))

    def test_testing_prerelease_suffix_is_stripped(self):
        self.assertTrue(pu_selfupdate.is_newer("psxhacks-updater-v1.3.0-testing", "1.2.9"))

    def test_wrong_prefix_is_never_newer(self):
        self.assertFalse(pu_selfupdate.is_newer("some-other-tool-v9.9.9", "1.0.0"))

    def test_missing_tag_is_never_newer(self):
        self.assertFalse(pu_selfupdate.is_newer(None, "1.0.0"))

    def test_unparseable_local_version_is_never_newer(self):
        self.assertFalse(pu_selfupdate.is_newer("psxhacks-updater-v1.2.3", "unknown"))


class TestCheckAndApply(unittest.TestCase):
    """check_and_apply()'s decision to download+handoff, or not."""

    def test_up_to_date_does_nothing(self):
        with mock.patch.object(pu_selfupdate.psxhacks_version, "get_version",
                                return_value="99.0.0"), \
             mock.patch.object(pu_github, "get_json",
                                return_value={"tag_name": "psxhacks-updater-v1.0.0"}):
            self.assertFalse(pu_selfupdate.check_and_apply("C:/tools/psxhacks-updater.exe"))

    def test_github_error_does_nothing(self):
        with mock.patch.object(pu_github, "get_json",
                                side_effect=pu_github.GitHubError("boom")):
            self.assertFalse(pu_selfupdate.check_and_apply("C:/tools/psxhacks-updater.exe"))

    def test_no_exe_asset_does_nothing(self):
        with mock.patch.object(pu_selfupdate.psxhacks_version, "get_version",
                                return_value="1.0.0"), \
             mock.patch.object(pu_github, "get_json", return_value={
                 "tag_name": "psxhacks-updater-v2.0.0", "assets": [{"name": "readme.txt"}]}):
            self.assertFalse(pu_selfupdate.check_and_apply("C:/tools/psxhacks-updater.exe"))

    def test_newer_release_downloads_and_hands_off(self):
        release = {
            "tag_name": "psxhacks-updater-v2.0.0",
            "assets": [{"name": "psxhacks-updater.exe",
                        "browser_download_url": "https://example/psxhacks-updater.exe"}],
        }
        with mock.patch.object(pu_selfupdate.psxhacks_version, "get_version",
                                return_value="1.0.0"), \
             mock.patch.object(pu_github, "get_json", return_value=release), \
             mock.patch.object(pu_github, "download_to") as mock_download, \
             mock.patch.object(pu_selfupdate.subprocess, "Popen") as mock_popen:
            result = pu_selfupdate.check_and_apply("C:/tools/psxhacks-updater.exe")

        self.assertTrue(result)
        mock_download.assert_called_once()
        downloaded_to = mock_download.call_args[0][1]
        self.assertTrue(downloaded_to.endswith(".new.exe"))
        mock_popen.assert_called_once()
        popen_args = mock_popen.call_args[0][0]
        self.assertEqual(popen_args[1], "--finish-update")
        self.assertEqual(popen_args[2], "C:/tools/psxhacks-updater.exe")


class TestFinishUpdate(unittest.TestCase):
    """finish_update()'s retry-until-unlocked bootstrap."""

    def test_succeeds_immediately_when_old_file_already_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = pathlib.Path(tmp) / "psxhacks-updater.new.exe"
            current.write_text("new", encoding="utf-8")
            old = pathlib.Path(tmp) / "psxhacks-updater.exe"

            with mock.patch.object(pu_selfupdate.subprocess, "Popen") as mock_popen:
                result = pu_selfupdate.finish_update(
                    str(old), current_exe_path=str(current), sleep=lambda _s: None)

            self.assertTrue(result)
            self.assertTrue(old.exists())
            self.assertEqual(old.read_text(encoding="utf-8"), "new")
            mock_popen.assert_called_once_with([str(old)])

    def test_retries_until_lock_released_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = pathlib.Path(tmp) / "psxhacks-updater.new.exe"
            current.write_text("new", encoding="utf-8")
            old = pathlib.Path(tmp) / "psxhacks-updater.exe"
            old.write_text("old", encoding="utf-8")

            real_replace = pu_selfupdate.os.replace
            attempts = []

            def flaky_replace(src, dst):
                attempts.append(1)
                if len(attempts) < 3:
                    raise PermissionError("still in use")
                real_replace(src, dst)

            sleeps = []
            with mock.patch.object(pu_selfupdate.os, "replace", side_effect=flaky_replace), \
                 mock.patch.object(pu_selfupdate.subprocess, "Popen"):
                result = pu_selfupdate.finish_update(
                    str(old), current_exe_path=str(current),
                    sleep=sleeps.append, max_attempts=10)

            self.assertTrue(result)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(len(sleeps), 2)

    def test_gives_up_after_max_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = pathlib.Path(tmp) / "psxhacks-updater.new.exe"
            old = pathlib.Path(tmp) / "psxhacks-updater.exe"

            with mock.patch.object(pu_selfupdate.os, "replace",
                                    side_effect=PermissionError("nope")), \
                 mock.patch.object(pu_selfupdate.subprocess, "Popen") as mock_popen:
                result = pu_selfupdate.finish_update(
                    str(old), current_exe_path=str(current),
                    sleep=lambda _s: None, max_attempts=5)

            self.assertFalse(result)
            mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
