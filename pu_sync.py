"""Download a psxhacks branch/commit ZIP and atomically swap it into place.

No git anywhere: GitHub serves any ref (branch name or commit SHA) as a
plain ZIP over HTTPS, which makes syncing to a branch tip immune to
upstream force-pushes by construction -- it is always a full, fresh
snapshot, never a merge or rebase against local history. Syncing to a
specific commit (sync_to_commit()) is exactly the same mechanism, just
pinned to an exact SHA instead of "whatever a branch currently points at".
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
_COMMIT_URL = f"https://api.github.com/repos/{_REPO}/commits/{{ref}}"
_COMMITS_LIST_URL = f"https://api.github.com/repos/{_REPO}/commits"
_BRANCHES_URL = f"https://api.github.com/repos/{_REPO}/branches?per_page=100"
_ZIP_URL_FOR_COMMIT = f"https://github.com/{_REPO}/archive/{{sha}}.zip"

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
    """Outcome of a successful sync()/sync_to_commit() call."""

    commit: str
    branch: str
    cleanup_warning: str = None  # set if the old directory could not be removed


def list_branches():
    """Return the public repo's branch names, or [] on any GitHub error.

    Capped at 100 (a single page) -- this is a hobby-scale repo with well
    under that many branches; pagination can be added if that changes.
    Callers should fall back to a hardcoded minimal list on an empty
    result, rather than leaving the branch picker empty.
    """
    try:
        data = pu_github.get_json(_BRANCHES_URL)
    except pu_github.GitHubError:
        return []
    return [entry["name"] for entry in data if "name" in entry]


def list_commits(branch, per_page=100):
    """Return up to per_page recent commits on branch, newest first.

    Each entry: sha, short_sha, author_name, author_date, committer_name,
    committer_date, message (full), summary (first line only). Uses
    GitHub's commit-list endpoint, which never includes per-commit
    file-change stats (those only appear on the single-commit endpoint) --
    so there's nothing to deliberately strip here. per_page is capped at
    100 by the GitHub API; older history needs pagination, not
    implemented. Raises pu_github.GitHubError on failure (unlike
    list_branches(), since an empty commit list has no safe fallback --
    callers should show the error rather than silently showing nothing).
    """
    url = f"{_COMMITS_LIST_URL}?sha={branch}&per_page={per_page}"
    return [_parse_commit(entry) for entry in pu_github.get_json(url)]


def get_commit(ref):
    """Return the commit ref (a branch name or SHA) points at, or raise.

    Same dict shape as each list_commits() entry. The single-commit
    endpoint also returns file-change stats; they're deliberately dropped
    here, same as list_commits() never has them. Raises
    pu_github.GitHubError on failure.
    """
    return _parse_commit(pu_github.get_json(_COMMIT_URL.format(ref=ref)))


def _parse_commit(entry):
    """Extract the fields this tool uses from a GitHub API commit object."""
    sha = entry["sha"]
    info = entry.get("commit", {})
    author = info.get("author") or {}
    committer = info.get("committer") or {}
    message = info.get("message") or ""
    return {
        "sha": sha,
        "short_sha": sha[:8],
        "author_name": author.get("name", "?"),
        "author_email": author.get("email", ""),
        "author_date": author.get("date", ""),
        "committer_name": committer.get("name", "?"),
        "committer_date": committer.get("date", ""),
        "message": message,
        "summary": message.splitlines()[0] if message else "",
    }


def check_for_update(branch, known_commit):
    """Return the latest commit SHA for branch, or None if it matches known_commit.

    A cheap, download-free check used to skip a full re-sync when nothing
    has changed upstream. On any GitHub error, returns the sentinel
    "unknown" rather than raising -- callers should treat that as "assume
    changed, fall through to the full sync" (see pu_github's own
    rate-limit note), never as an error.
    """
    try:
        data = pu_github.get_json(_COMMIT_URL.format(ref=branch))
        latest = data["sha"]
    except (pu_github.GitHubError, KeyError, TypeError):
        return "unknown"
    if latest == known_commit:
        return None
    return latest


def _extract_and_swap(branch, commit, commit_info, target_dir):
    """Download commit's ZIP, extract it, build+save its manifest, swap it in.

    Shared by sync() and sync_to_commit() -- the only difference between
    them is how they resolved commit (and its commit_info metadata, or
    None if unavailable) before calling this. Always downloads by exact
    SHA, never by branch name, so the recorded source_commit is guaranteed
    to be what's actually on disk even if the branch moves mid-sync. See
    _swap_in() for the atomic-replace step's own documentation.
    """
    zip_url = _ZIP_URL_FOR_COMMIT.format(sha=commit)
    target_dir = pathlib.Path(target_dir)
    with tempfile.TemporaryDirectory(dir=target_dir.parent) as work_dir:
        work_dir = pathlib.Path(work_dir)
        zip_path = work_dir / "psxhacks.zip"
        pu_github.download_to(zip_url, zip_path)

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
        new_tree = top_level[0]

        manifest = pu_manifest.build(
            new_tree, branch=branch, source_commit=commit,
            source_commit_info=commit_info)
        pu_manifest.save(new_tree, manifest)
        cleanup_warning = _swap_in(new_tree, target_dir)

    return SyncResult(commit=commit, branch=branch, cleanup_warning=cleanup_warning)


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
    try:
        commit_info = get_commit(branch)
    except (pu_github.GitHubError, KeyError, TypeError) as exc:
        raise SyncError(f"Could not determine latest commit for {branch}: {exc}") from exc
    return _extract_and_swap(branch, commit_info["sha"], commit_info, target_dir)


def sync_to_commit(target_dir, branch, commit_sha, commit_info=None):
    """Sync target_dir to the exact commit_sha (an upgrade or a downgrade).

    branch is only recorded in the resulting manifest (so the branch
    dropdown/status check still has something sensible to compare
    against next time -- which will then correctly show "update
    available" again, since commit_sha need not be branch's current
    tip); it plays no role in resolving what to download, since
    commit_sha already fully identifies it. commit_info (a list_commits()
    entry, e.g. from the history page) is recorded in the manifest for
    display; if not given, it's looked up, but a failed lookup isn't fatal
    -- the manifest then just has the SHA. May raise
    SyncError/TargetInUseError/SwapFailedRecoverableError.
    """
    if commit_info is None:
        try:
            commit_info = get_commit(commit_sha)
        except (pu_github.GitHubError, KeyError, TypeError):
            commit_info = None
    return _extract_and_swap(branch, commit_sha, commit_info, target_dir)
