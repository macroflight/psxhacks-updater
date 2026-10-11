"""Build/load/diff the .psxhacks-manifest.json drift-detection manifest.

Replaces git status entirely for detecting local drift in a psxhacks
checkout synced by this tool (there is no .git directory at all -- see
pu_sync.py). The manifest is a straightforward SHA256-per-file snapshot,
written into the synced tree itself right after a successful sync, so it
always travels with the exact tree it describes.

__pycache__ directories and the manifest file itself are excluded from
both build() and diff() -- load-bearing, since running any addon script
creates __pycache__ the moment Python imports it, which would otherwise
register as false "drift" immediately after a clean sync.
"""
import datetime
import hashlib
import json
import pathlib

MANIFEST_FILENAME = ".psxhacks-manifest.json"
SCHEMA_VERSION = 1

_HASH_CHUNK_SIZE = 1024 * 1024


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(tree_dir):
    """Yield (relative_posix_path, absolute_path) for every tracked file.

    Skips __pycache__ directories (at any depth) and the manifest file
    itself, which is never part of what a real GitHub sync would contain.
    """
    tree_dir = pathlib.Path(tree_dir)
    for path in tree_dir.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.relative_to(tree_dir).parts:
            continue
        if path.name == MANIFEST_FILENAME and path.parent == tree_dir:
            continue
        yield path.relative_to(tree_dir).as_posix(), path


def build(tree_dir, branch=None, source_commit=None):
    """Return a fresh manifest dict for every tracked file under tree_dir."""
    files = {rel: _sha256_of(abs_path) for rel, abs_path in _iter_files(tree_dir)}
    return {
        "schema_version": SCHEMA_VERSION,
        "branch": branch,
        "source_commit": source_commit,
        "synced_at_utc": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds"),
        "files": files,
    }


def save(tree_dir, manifest):
    """Write manifest into tree_dir/MANIFEST_FILENAME."""
    manifest_path = pathlib.Path(tree_dir) / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def load(target_dir):
    """Return the manifest dict stored in target_dir, or None if absent/invalid.

    A missing or unreadable manifest is not an error -- it just means this
    checkout isn't (yet) managed by this tool (e.g. a plain git clone, or a
    pre-updater legacy setup), which callers must treat as a distinct case
    from "managed but drifted".
    """
    manifest_path = pathlib.Path(target_dir) / MANIFEST_FILENAME
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "files" not in data:
        return None
    return data


def diff(target_dir, manifest):
    """Return a list of "<path> (missing|modified|added)" strings, or [] if clean."""
    target_dir = pathlib.Path(target_dir)
    drifted = []
    seen = set()
    for rel, expected_hash in manifest.get("files", {}).items():
        seen.add(rel)
        abs_path = target_dir / rel
        if not abs_path.is_file():
            drifted.append(f"{rel} (missing)")
            continue
        if _sha256_of(abs_path) != expected_hash:
            drifted.append(f"{rel} (modified)")
    for rel, _abs_path in _iter_files(target_dir):
        if rel not in seen:
            drifted.append(f"{rel} (added)")
    return drifted
