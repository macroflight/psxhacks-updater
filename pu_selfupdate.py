"""Self-update: check this tool's own GitHub Releases, replace, relaunch.

Checked on every launch against this tool's own separate repo
(macroflight/psxhacks-updater), independent of the psxhacks sync/manifest
logic in pu_sync.py.
"""
import os
import subprocess
import sys
import time

from packaging.version import InvalidVersion, Version

import pu_github
import psxhacks_version

_REPO = "macroflight/psxhacks-updater"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_TAG_PREFIX = "psxhacks-updater-v"

_FINISH_UPDATE_MAX_ATTEMPTS = 40
_FINISH_UPDATE_RETRY_DELAY_S = 0.25


def _parse_tag_version(tag_name):
    """Return a packaging.version.Version for a release tag, or None.

    Tags look like "psxhacks-updater-v1.2.3" or, for a prerelease off the
    testing branch (mirroring the main repo's own tagging convention),
    "psxhacks-updater-v1.2.3-testing".
    """
    if not tag_name or not tag_name.startswith(_TAG_PREFIX):
        return None
    raw = tag_name[len(_TAG_PREFIX):]
    raw = raw.removesuffix("-testing")
    try:
        return Version(raw)
    except InvalidVersion:
        return None


def is_newer(remote_tag, local_version_str):
    """Return True if remote_tag's version is strictly newer than local_version_str."""
    remote_version = _parse_tag_version(remote_tag)
    if remote_version is None:
        return False
    try:
        local_version = Version(local_version_str)
    except InvalidVersion:
        # Can't parse our own version -- never claim "newer" off bad local data.
        return False
    return remote_version > local_version


def _find_exe_asset_url(release):
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def check_and_apply(current_exe_path):
    """Check for a newer release and, if found, download it and hand off.

    Returns True if a newer version was downloaded and a relaunch was
    started -- the caller must exit immediately without doing anything
    else. Returns False if there is nothing to do (up to date, or any
    network/parsing problem -- treated as "nothing to do", never as a
    fatal error, since this check must never block normal operation).
    """
    local_version = psxhacks_version.get_version("psxhacks-updater", __file__)
    try:
        release = pu_github.get_json(_LATEST_RELEASE_URL)
    except pu_github.GitHubError:
        return False

    tag_name = release.get("tag_name")
    if not is_newer(tag_name, local_version):
        return False

    asset_url = _find_exe_asset_url(release)
    if asset_url is None:
        return False

    current_exe_path = str(current_exe_path)
    new_exe_path = current_exe_path + ".new.exe"
    try:
        pu_github.download_to(asset_url, new_exe_path)
    except pu_github.GitHubError:
        return False

    subprocess.Popen([new_exe_path, "--finish-update", current_exe_path])  # pylint: disable=consider-using-with
    return True


def finish_update(old_exe_path, original_args=None, current_exe_path=None,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                   max_attempts=_FINISH_UPDATE_MAX_ATTEMPTS,
                   retry_delay_s=_FINISH_UPDATE_RETRY_DELAY_S, sleep=time.sleep):
    """Replace old_exe_path with the currently-running exe, then relaunch it.

    Windows blocks deleting or overwriting a running EXE's file in place,
    but permits *renaming* it -- so this (the newly-downloaded EXE) can
    move itself onto the old EXE's path as soon as the old process has
    actually exited and released its file lock. A short retry loop
    catching PermissionError/OSError is simpler and more self-correcting
    than tracking the old process's PID: it just keeps trying until the
    lock is gone, with no risk of a stale/reused PID.

    Returns True on success (a relaunch of old_exe_path, now holding this
    exe's own bytes, was started). Returns False if the old file's lock
    was never released -- the caller should tell the user to close the
    old updater window and re-run.
    """
    current_exe_path = current_exe_path or sys.executable
    for attempt in range(max_attempts):
        try:
            os.replace(current_exe_path, old_exe_path)
            break
        except OSError:
            if attempt == max_attempts - 1:
                return False
            sleep(retry_delay_s)
    subprocess.Popen([str(old_exe_path), *(original_args or [])])  # pylint: disable=consider-using-with
    return True
