"""Tiny GitHub REST/download helper shared by pu_sync.py and pu_selfupdate.py.

Deliberately just urllib + the stdlib ssl module -- no requests/certifi, so
there is nothing beyond PyInstaller's own built-in analysis to bundle.
ssl.create_default_context() validates HTTPS against the Windows
certificate store automatically.
"""
import json
import shutil
import ssl
import urllib.error
import urllib.request

# GitHub's REST API requires a User-Agent header on every request, or it
# rejects the call outright.
_USER_AGENT = "psxhacks-updater"
_TIMEOUT_S = 30

_SSL_CONTEXT = ssl.create_default_context()


class GitHubError(Exception):
    """Raised when a GitHub request fails (network, HTTP status, bad JSON)."""


def _request(url):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_SSL_CONTEXT)
    except (urllib.error.URLError, OSError) as exc:
        raise GitHubError(f"Could not reach {url}: {exc}") from exc


def get_json(url):
    """GET url and return the parsed JSON body, or raise GitHubError."""
    with _request(url) as response:
        try:
            return json.load(response)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GitHubError(f"Could not parse JSON from {url}: {exc}") from exc


def download_to(url, dest_path):
    """Stream url's response body into dest_path, or raise GitHubError."""
    with _request(url) as response:
        try:
            with open(dest_path, "wb") as dest_file:
                shutil.copyfileobj(response, dest_file)
        except OSError as exc:
            raise GitHubError(f"Could not write {dest_path}: {exc}") from exc
