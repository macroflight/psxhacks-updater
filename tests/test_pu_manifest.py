"""Tests for pu_manifest.py."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pu_manifest  # noqa: E402  pylint: disable=wrong-import-position


class TestManifest(unittest.TestCase):
    """build()/load()/save()/diff() round-trip and drift detection."""

    def _make_tree(self, tmp_path):
        tree = pathlib.Path(tmp_path) / "psxhacks"
        tree.mkdir()
        (tree / "requirements.txt").write_text("aiohttp>=3.9\n", encoding="utf-8")
        sub = tree / "start_scripts"
        sub.mkdir()
        (sub / "common.ps1").write_text("# common\n", encoding="utf-8")
        return tree

    def test_build_excludes_pycache_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            pycache = tree / "__pycache__"
            pycache.mkdir()
            (pycache / "foo.pyc").write_bytes(b"junk")

            manifest = pu_manifest.build(tree, branch="main", source_commit="abc123")
            self.assertEqual(manifest["branch"], "main")
            self.assertEqual(manifest["source_commit"], "abc123")
            self.assertEqual(
                set(manifest["files"].keys()),
                {"requirements.txt", "start_scripts/common.ps1"})

            pu_manifest.save(tree, manifest)
            self.assertNotIn(pu_manifest.MANIFEST_FILENAME, manifest["files"])

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            self.assertIsNone(pu_manifest.load(tree))

    def test_load_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            (tree / pu_manifest.MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
            self.assertIsNone(pu_manifest.load(tree))

    def test_round_trip_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            manifest = pu_manifest.build(tree, branch="main", source_commit="abc123")
            pu_manifest.save(tree, manifest)
            loaded = pu_manifest.load(tree)
            self.assertEqual(loaded["source_commit"], "abc123")
            self.assertEqual(loaded["files"], manifest["files"])

    def test_diff_clean_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            manifest = pu_manifest.build(tree)
            self.assertEqual(pu_manifest.diff(tree, manifest), [])

    def test_diff_detects_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            manifest = pu_manifest.build(tree)
            (tree / "requirements.txt").write_text("edited by hand\n", encoding="utf-8")
            self.assertEqual(
                pu_manifest.diff(tree, manifest), ["requirements.txt (modified)"])

    def test_diff_detects_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            manifest = pu_manifest.build(tree)
            (tree / "requirements.txt").unlink()
            self.assertEqual(
                pu_manifest.diff(tree, manifest), ["requirements.txt (missing)"])

    def test_diff_detects_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            manifest = pu_manifest.build(tree)
            (tree / "new_local_file.txt").write_text("hand-added\n", encoding="utf-8")
            self.assertEqual(
                pu_manifest.diff(tree, manifest), ["new_local_file.txt (added)"])

    def test_diff_ignores_pycache_and_manifest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._make_tree(tmp)
            manifest = pu_manifest.build(tree)
            pu_manifest.save(tree, manifest)
            pycache = tree / "__pycache__"
            pycache.mkdir()
            (pycache / "foo.pyc").write_bytes(b"junk")
            self.assertEqual(pu_manifest.diff(tree, manifest), [])


if __name__ == "__main__":
    unittest.main()
