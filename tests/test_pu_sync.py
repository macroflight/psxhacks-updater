"""Tests for pu_sync.py."""
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pu_github  # noqa: E402  pylint: disable=wrong-import-position
import pu_manifest  # noqa: E402  pylint: disable=wrong-import-position
import pu_sync  # noqa: E402  pylint: disable=wrong-import-position


class TestListBranches(unittest.TestCase):
    """list_branches()'s error-tolerant branch-name listing."""

    def test_returns_names(self):
        payload = [{"name": "main"}, {"name": "testing"}, {"name": "frankensim"}]
        with mock.patch.object(pu_github, "get_json", return_value=payload):
            self.assertEqual(
                pu_sync.list_branches(), ["main", "testing", "frankensim"])

    def test_github_error_returns_empty_list(self):
        with mock.patch.object(
                pu_github, "get_json", side_effect=pu_github.GitHubError("boom")):
            self.assertEqual(pu_sync.list_branches(), [])


class TestListCommits(unittest.TestCase):
    """list_commits()'s metadata extraction (no file-change stats)."""

    def test_extracts_expected_fields(self):
        payload = [{
            "sha": "abcdef1234567890",
            "commit": {
                "author": {"name": "Mats Kronberg", "email": "m@example.com",
                           "date": "2026-10-11T12:00:00Z"},
                "committer": {"name": "Mats Kronberg", "date": "2026-10-11T12:05:00Z"},
                "message": "router: fix thing\n\nLonger explanation here.",
            },
        }]
        with mock.patch.object(pu_github, "get_json", return_value=payload):
            commits = pu_sync.list_commits("main")
        self.assertEqual(len(commits), 1)
        entry = commits[0]
        self.assertEqual(entry["sha"], "abcdef1234567890")
        self.assertEqual(entry["short_sha"], "abcdef12")
        self.assertEqual(entry["author_name"], "Mats Kronberg")
        self.assertEqual(entry["author_date"], "2026-10-11T12:00:00Z")
        self.assertEqual(entry["summary"], "router: fix thing")
        self.assertIn("Longer explanation here.", entry["message"])
        # No file-change data requested or present anywhere in the output.
        self.assertNotIn("files", entry)

    def test_missing_author_info_does_not_crash(self):
        payload = [{"sha": "abc", "commit": {"message": "x"}}]
        with mock.patch.object(pu_github, "get_json", return_value=payload):
            commits = pu_sync.list_commits("main")
        self.assertEqual(commits[0]["author_name"], "?")

    def test_github_error_propagates(self):
        with mock.patch.object(
                pu_github, "get_json", side_effect=pu_github.GitHubError("boom")):
            with self.assertRaises(pu_github.GitHubError):
                pu_sync.list_commits("main")


class TestSyncToCommit(unittest.TestCase):
    """sync_to_commit() uses the commit-specific archive URL, no lookup needed."""

    def test_downloads_commit_archive_and_records_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "psxhacks"

            def fake_download(url, dest_path):
                self.assertIn("/archive/deadbeef.zip", url)
                extract_root = pathlib.Path(tmp) / "fake_zip_root"
                tree = extract_root / "psxhacks-main"
                tree.mkdir(parents=True)
                (tree / "marker.txt").write_text("content", encoding="utf-8")
                with zipfile.ZipFile(dest_path, "w") as zf:
                    zf.write(tree / "marker.txt", "psxhacks-main/marker.txt")

            with mock.patch.object(pu_github, "download_to", side_effect=fake_download):
                result = pu_sync.sync_to_commit(target, "main", "deadbeef")

            self.assertEqual(result.commit, "deadbeef")
            self.assertEqual(result.branch, "main")
            self.assertTrue((target / "marker.txt").is_file())
            manifest = pu_manifest.load(target)
            self.assertEqual(manifest["source_commit"], "deadbeef")
            self.assertEqual(manifest["branch"], "main")


class TestCheckForUpdate(unittest.TestCase):
    """check_for_update()'s commit-SHA short-circuit."""

    def test_same_commit_returns_none(self):
        with mock.patch.object(pu_github, "get_json", return_value={"sha": "abc123"}):
            self.assertIsNone(pu_sync.check_for_update("main", "abc123"))

    def test_different_commit_returns_new_sha(self):
        with mock.patch.object(pu_github, "get_json", return_value={"sha": "def456"}):
            self.assertEqual(pu_sync.check_for_update("main", "abc123"), "def456")

    def test_github_error_returns_unknown_sentinel(self):
        with mock.patch.object(
                pu_github, "get_json", side_effect=pu_github.GitHubError("boom")):
            self.assertEqual(pu_sync.check_for_update("main", "abc123"), "unknown")


class TestSwapIn(unittest.TestCase):
    """_swap_in()'s atomic rename sequence and its three failure points."""

    def _tree(self, tmp, name):
        path = pathlib.Path(tmp) / name
        path.mkdir()
        (path / "marker.txt").write_text(name, encoding="utf-8")
        return path

    def test_fresh_install_no_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_tree = self._tree(tmp, "new")
            target = pathlib.Path(tmp) / "psxhacks"
            warning = pu_sync._swap_in(new_tree, target)  # pylint: disable=protected-access
            self.assertIsNone(warning)
            self.assertTrue(target.is_dir())
            self.assertEqual((target / "marker.txt").read_text(encoding="utf-8"), "new")

    def test_normal_swap_replaces_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_tree = self._tree(tmp, "psxhacks")
            new_tree = self._tree(tmp, "new")
            target = old_tree
            warning = pu_sync._swap_in(new_tree, target)  # pylint: disable=protected-access
            self.assertIsNone(warning)
            self.assertEqual((target / "marker.txt").read_text(encoding="utf-8"), "new")
            self.assertFalse((target.with_name(target.name + ".old")).exists())

    def test_target_in_use_leaves_everything_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_tree = self._tree(tmp, "psxhacks")
            new_tree = self._tree(tmp, "new")
            target = old_tree
            with mock.patch("os.rename", side_effect=OSError("file in use")):
                with self.assertRaises(pu_sync.TargetInUseError):
                    pu_sync._swap_in(new_tree, target)  # pylint: disable=protected-access
            # Nothing destroyed: both trees still present, target unchanged.
            self.assertTrue(target.is_dir())
            self.assertEqual((target / "marker.txt").read_text(encoding="utf-8"), "psxhacks")
            self.assertTrue(new_tree.is_dir())

    def test_swap_failure_after_old_moved_aside_is_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_tree = self._tree(tmp, "psxhacks")
            new_tree = self._tree(tmp, "new")
            target = old_tree

            real_rename = pu_sync.os.rename
            calls = []

            def flaky_rename(src, dst):
                calls.append((str(src), str(dst)))
                if len(calls) == 1:
                    real_rename(src, dst)  # step 2 (move old aside) succeeds
                    return
                raise OSError("disk full")  # step 3 (move new into place) fails

            with mock.patch("os.rename", side_effect=flaky_rename):
                with self.assertRaises(pu_sync.SwapFailedRecoverableError) as ctx:
                    pu_sync._swap_in(new_tree, target)  # pylint: disable=protected-access

            old_dir = target.with_name(target.name + ".old")
            self.assertEqual(ctx.exception.old_dir, old_dir)
            self.assertTrue(old_dir.is_dir())
            self.assertEqual((old_dir / "marker.txt").read_text(encoding="utf-8"), "psxhacks")

    def test_cleanup_failure_is_a_warning_not_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_tree = self._tree(tmp, "psxhacks")
            new_tree = self._tree(tmp, "new")
            target = old_tree

            with mock.patch("shutil.rmtree", side_effect=OSError("still locked")):
                warning = pu_sync._swap_in(new_tree, target)  # pylint: disable=protected-access

            self.assertIsNotNone(warning)
            self.assertIn("could not be fully removed", warning)
            # The swap itself still succeeded despite the cleanup failure.
            self.assertEqual((target / "marker.txt").read_text(encoding="utf-8"), "new")


if __name__ == "__main__":
    unittest.main()
