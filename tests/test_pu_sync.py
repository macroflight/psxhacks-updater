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


_COMMIT_PAYLOAD = {
    "sha": "deadbeef12345678",
    "commit": {
        "author": {"name": "Mats Kronberg", "email": "m@example.com",
                   "date": "2026-10-11T12:00:00Z"},
        "committer": {"name": "Mats Kronberg", "date": "2026-10-11T12:05:00Z"},
        "message": "router: fix thing\n\nLonger explanation here.",
    },
    # The single-commit endpoint also returns these; get_commit() drops them.
    "files": [{"filename": "x.py"}],
}


class TestGetCommit(unittest.TestCase):
    """get_commit() parses the single-commit endpoint like list_commits()."""

    def test_parses_and_drops_file_stats(self):
        with mock.patch.object(pu_github, "get_json", return_value=_COMMIT_PAYLOAD):
            commit = pu_sync.get_commit("main")
        self.assertEqual(commit["sha"], "deadbeef12345678")
        self.assertEqual(commit["summary"], "router: fix thing")
        self.assertEqual(commit["author_date"], "2026-10-11T12:00:00Z")
        self.assertNotIn("files", commit)


class TestSyncDownloads(unittest.TestCase):
    """sync()/sync_to_commit() download by exact SHA and record commit info."""

    def _fake_download(self, tmp, expected_sha):
        def fake_download(url, dest_path):
            self.assertIn(f"/archive/{expected_sha}.zip", url)
            tree = pathlib.Path(tmp) / "fake_zip_root" / "psxhacks-x"
            tree.mkdir(parents=True)
            (tree / "marker.txt").write_text("content", encoding="utf-8")
            with zipfile.ZipFile(dest_path, "w") as zf:
                zf.write(tree / "marker.txt", "psxhacks-x/marker.txt")
        return fake_download

    def test_sync_downloads_resolved_sha_not_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "psxhacks"
            with mock.patch.object(pu_github, "get_json", return_value=_COMMIT_PAYLOAD), \
                 mock.patch.object(pu_github, "download_to",
                                   side_effect=self._fake_download(tmp, "deadbeef12345678")):
                result = pu_sync.sync(target, "main")
            self.assertEqual(result.commit, "deadbeef12345678")
            manifest = pu_manifest.load(target)
            self.assertEqual(manifest["source_commit"], "deadbeef12345678")
            info = manifest["source_commit_info"]
            self.assertEqual(info["sha"], "deadbeef12345678")
            self.assertEqual(info["author_name"], "Mats Kronberg")
            self.assertIn("Longer explanation here.", info["message"])

    def test_sync_to_commit_uses_given_info_without_lookup(self):
        info = {"sha": "deadbeef", "summary": "from history page"}
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "psxhacks"
            with mock.patch.object(pu_github, "get_json") as mock_get_json, \
                 mock.patch.object(pu_github, "download_to",
                                   side_effect=self._fake_download(tmp, "deadbeef")):
                result = pu_sync.sync_to_commit(target, "main", "deadbeef", commit_info=info)
            mock_get_json.assert_not_called()
            self.assertEqual(result.commit, "deadbeef")
            self.assertEqual(result.branch, "main")
            self.assertTrue((target / "marker.txt").is_file())
            manifest = pu_manifest.load(target)
            self.assertEqual(manifest["source_commit"], "deadbeef")
            self.assertEqual(manifest["branch"], "main")
            self.assertEqual(manifest["source_commit_info"], info)

    def test_sync_to_commit_info_lookup_failure_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "psxhacks"
            with mock.patch.object(pu_github, "get_json",
                                   side_effect=pu_github.GitHubError("boom")), \
                 mock.patch.object(pu_github, "download_to",
                                   side_effect=self._fake_download(tmp, "deadbeef")):
                pu_sync.sync_to_commit(target, "main", "deadbeef")
            manifest = pu_manifest.load(target)
            self.assertEqual(manifest["source_commit"], "deadbeef")
            self.assertIsNone(manifest["source_commit_info"])


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
