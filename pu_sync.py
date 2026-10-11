"""Download a psxhacks branch ZIP and atomically swap it into place.

No git anywhere: GitHub serves any branch as a plain ZIP over HTTPS
(.../archive/refs/heads/<branch>.zip), which makes this immune to upstream
force-pushes by construction -- it is always a full, fresh snapshot, never
a merge or rebase against local history.
"""
import dataclasses
import os
import pathlib
import shutil
import tempfile
import zipfile

import pu_github
import pu_manifest

_REPO = "macroflight/psxhacks"
_COMMITS_URL = f"https://api.github.com/repos/{_REPO}/commits/{{branch}}"
_ZIP_URL = f"https://github.com/{_REPO}/archive/refs/heads/{{branch}}.zip"

_OLD_SUFFIX = ".old"


class SyncError(Exception):
    """Base class for all errors raised by this module."""


class TargetInUseError(SyncError):
    """Raised when the live directory could not be moved aside.

    Nothing has been destroyed -- the existing checkout is untouched.
    """


class SwapFailedRecoverableError(SyncError):
    """Raised when the live directory was moved aside but the new one
    could not be moved into its place.

    Recoverable: old_dir still holds the previous checkout intact.
    """

    def __init__(self, message, old_dir):
        super().__init__(message)
        self.old_dir = old_dir


@dataclasses.dataclass
class SyncResult:
    """Outcome of a successful sync() call."""

    commit: str
    branch: str
    cleanup_warning: str = None  # set if the old directory could not be removed


def check_for_update(branch, known_commit):
    """Return the latest commit SHA for branch, or None if it matches known_commit.

    A cheap, download-free check used to skip a full re-sync when nothing
    has changed upstream. On any GitHub error, returns the sentinel
    "unknown" rather than raising -- callers should treat that as "assume
    changed, fall through to the full sync" (see pu_github's own
    rate-limit note), never as an error.
    """
    try:
        data = pu_github.get_json(_COMMITS_URL.format(branch=branch))
        latest = data["sha"]
    except (pu_github.GitHubError, KeyError, TypeError):
        return "unknown"
    if latest == known_commit:
        return None
    return latest


def _download_and_extract(branch, work_dir):
    """Download branch's ZIP into work_dir and extract it.

    Returns (new_tree_dir, commit_sha). GitHub's archive always wraps its
    content in exactly one top-level folder ("psxhacks-<branch>/", neither
    real branch name -- main, public-testing -- contains a slash).
    """
    try:
        commit = pu_github.get_json(_COMMITS_URL.format(branch=branch))["sha"]
    except (pu_github.GitHubError, KeyError, TypeError) as exc:
        raise SyncError(f"Could not determine latest commit for {branch}: {exc}") from exc

    zip_path = work_dir / "psxhacks.zip"
    pu_github.download_to(_ZIP_URL.format(branch=branch), zip_path)

    extract_dir = work_dir / "extracted"
    extract_dir.mkdir()
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise SyncError(f"Downloaded file is not a valid ZIP archive: {exc}") from exc

    top_level = list(extract_dir.iterdir())
    if len(top_level) != 1 or not top_level[0].is_dir():
        raise SyncError(
            f"Expected exactly one top-level folder in the archive, found: "
            f"{[p.name for p in top_level]}")
    return top_level[0], commit


def _swap_in(new_tree, target_dir):
    """Atomically replace target_dir with new_tree.

    Order, matching the documented recovery story at each step:
      1. (caller has already built new_tree fully, including its manifest,
         before this is called -- nothing here can fail "before touching
         the live directory".)
      2. Rename target_dir -> target_dir + ".old". If this fails (typically
         "file in use" -- PSX or an addon still has a handle open inside
         it), raise TargetInUseError. Nothing destroyed yet.
      3. Rename new_tree -> target_dir. If THIS fails after step 2 already
         succeeded, raise SwapFailedRecoverableError naming the .old
         directory that still holds the previous checkout intact.
      4. Only once step 3 succeeds, delete the .old directory. A failure
         here is not fatal -- the new version is already active -- so it is
         reported back via SyncResult.cleanup_warning, not raised.
    """
    old_dir = target_dir.with_name(target_dir.name + _OLD_SUFFIX)
    if old_dir.exists():
        # Leftover from a previous failed run that got as far as step 4
        # failing; safe to remove since step 3 already succeeded that time.
        shutil.rmtree(old_dir, ignore_errors=True)

    if target_dir.exists():
        try:
            os.rename(target_dir, old_dir)
        except OSError as exc:
            raise TargetInUseError(
                f"Could not move the current {target_dir.name} folder aside: {exc}. "
                f"Close PSX and any psxhacks addon windows, then try again."
            ) from exc

    try:
        os.rename(new_tree, target_dir)
    except OSError as exc:
        raise SwapFailedRecoverableError(
            f"Could not move the newly-synced folder into place: {exc}. "
            f"{old_dir.name} still has your previous checkout intact -- "
            f"rename it back to {target_dir.name} to restore it.",
            old_dir=old_dir,
        ) from exc

    cleanup_warning = None
    if old_dir.exists():
        try:
            shutil.rmtree(old_dir)
        except OSError as exc:
            cleanup_warning = (
                f"The new version is active, but {old_dir.name} could not be "
                f"fully removed ({exc}) -- delete it manually later.")
    return cleanup_warning


def sync(target_dir, branch):
    """Sync target_dir to branch's current head, swapping it in atomically.

    Always performs the download+swap -- callers decide when that's
    warranted (missing directory, a newer commit upstream, or local drift)
    using check_for_update()/pu_manifest.diff() themselves, and confirm
    with the user first when the action is destructive; this function
    doesn't need to know why it was called. May raise
    SyncError/TargetInUseError/SwapFailedRecoverableError.
    """
    target_dir = pathlib.Path(target_dir)
    with tempfile.TemporaryDirectory(dir=target_dir.parent) as work_dir:
        work_dir = pathlib.Path(work_dir)
        new_tree, commit = _download_and_extract(branch, work_dir)
        manifest = pu_manifest.build(new_tree, branch=branch, source_commit=commit)
        pu_manifest.save(new_tree, manifest)
        cleanup_warning = _swap_in(new_tree, target_dir)

    return SyncResult(commit=commit, branch=branch, cleanup_warning=cleanup_warning)
