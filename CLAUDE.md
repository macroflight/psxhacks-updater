# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`psxhacks-updater` is a standalone Windows GUI tool (PyInstaller,
`console=False`) that sets up and updates a local checkout of the separate
[psxhacks](https://github.com/macroflight/psxhacks) repo for non-technical
end users, with no git client and no GitHub authentication required. See
`README.md` for the user-facing description.

## Architecture

- `psxhacks_updater.py` -- entry point and the `Controller` class, which
  drives the GUI: computes directory/update status (on a background
  thread) and reacts to the branch dropdown and the Install/Update/
  Reinstall/History buttons (see `pu_gui.py`). Status is recomputed on
  every branch change and after every completed action; nothing happens
  automatically beyond the self-update check and the initial branch-list
  fetch at startup.
- `pu_manifest.py` -- builds/loads/diffs `.psxhacks-manifest.json`, the
  SHA256-per-file manifest written into the managed `psxhacks` checkout
  after every successful sync. This (not git) is how drift is detected.
  Records which branch a sync came from, but `source_commit` need not be
  that branch's current tip -- syncing to an arbitrary historical commit
  (see History below) still records the branch it was browsed from, so
  the next status check correctly reports "update available" again.
  Also stores `source_commit_info` (that commit's message/author/date, a
  `pu_sync.get_commit()` dict) for the status page's "Installed version"
  pane; it's optional -- manifests from <= 0.1.2 lack it, and the
  controller then fetches it by SHA instead. The main repo's PowerShell
  preflight only reads `files`, so extra top-level fields are safe.
- `pu_sync.py` -- `list_branches()`/`list_commits()` (GitHub metadata
  listings -- the commit list deliberately excludes per-commit file-change
  stats, since the list endpoint never returns them), `get_commit()`
  (one commit's metadata, same dict shape), `check_for_update()`
  (cheap commit-SHA check, used to decide whether the Update button should
  be enabled), `sync()` (branch tip) and `sync_to_commit()` (an exact SHA,
  upgrade or downgrade) -- both download a ZIP of an exact commit SHA
  (never a branch-name ZIP, so `source_commit` can't race a push), extract it, and
  atomically swap it in for the live checkout directory via the shared
  `_extract_and_swap()` helper. Always does the full thing; the controller
  decides when that's warranted, not this module.
- `pu_selfupdate.py` -- checks this tool's own GitHub Releases for a newer
  version, downloads it, and bootstraps replacing the running EXE
  (`--finish-update <old_exe_path>`).
- `pu_github.py` -- tiny `urllib`-based GitHub REST helper shared by
  `pu_sync.py` and `pu_selfupdate.py`. Verifies HTTPS via `truststore`
  (Windows' own CryptoAPI), not `ssl.create_default_context()`: the
  latter fails on fresh Windows installs whose root store hasn't yet
  been populated on demand -- don't switch back.
- `pu_gui.py` -- tkinter multi-page wizard shell: the status page (branch
  dropdown, status/progress/log, Install/Update/Reinstall/History
  buttons) and the history page (a `Treeview` of commits plus a detail
  pane and a "Switch to this commit" button). Structured for more pages
  to be added later (a planned guided master/slave sim setup flow), not
  as a single fixed-purpose window. Its thread-bridging methods
  (`set_status`/`log`/`ask_yes_no`/etc.) are safe to call from either the
  Tk main thread (dropdown/button event handlers) or the background
  worker thread the controller runs status checks and syncs on.
- `psxhacks_version.py` / `release.py` -- vendored from the main `psxhacks`
  repo (the former verbatim, the latter trimmed to this repo's single
  artifact). Keep in sync by hand if the main repo's versions change in a
  way that matters here.

Removed for now: a Python-venv check + `setup_python_venv.ps1` wizard
handoff (`pu_venvcheck.py`) and the generic override-file-line editor it
used (`pu_override.py`) -- pulled because the console wizard it launched
couldn't actually be interacted with in practice. If this comes back, it
needs a different approach to the console handoff, not just re-adding the
old modules verbatim (check git history for what they looked like). The
matching companion edits in the main `psxhacks` repo
(`start_scripts/setup_python_venv.ps1`'s `VENV_PYTHON=...` marker line)
should be reverted alongside this, since nothing calls that script anymore.

## Conventions

- Target Python 3.13 (what CI builds the EXE with; `make` uses
  `python3.13`, overridable with `make PYTHON=...`).

- No git dependency anywhere in the shipped tool -- only plain HTTPS to
  GitHub's REST API and ZIP archive endpoints.
- Branch names are fetched live from GitHub (`pu_sync.list_branches()`),
  not hardcoded -- `main` and `testing` are the only two considered
  officially supported (`RECOMMENDED_BRANCHES` in `psxhacks_updater.py`);
  selecting anything else shows a warning via `pu_gui.show_warning()` but
  is never blocked.
- An existing directory that isn't manifest-managed by this tool is never
  offered as something to replace -- the user is told to rename or remove
  it themselves. Every actual sync (install, update, reinstall, or
  switching to an arbitrary commit) only ever happens from a button click,
  and always asks for confirmation first via `pu_gui`, even when nothing
  destructive is at risk (e.g. a plain "nothing installed yet" install) --
  a button being enabled at all already means the controller decided
  there's something to do; the confirmation is about *when*, not
  *whether*.
- `common.ps1`/`functions.ps1` in the main `psxhacks` repo have a small,
  deliberate hook for this tool (the manifest preflight check) -- see that
  repo's own `CLAUDE.md` and git history for the exact edit.

## Testing

```
make                                                    # Python 3.13 venv in ~/.venv-test-psxhacks-updater/, then all tests
python3 -m unittest discover tests                      # everything, no venv
python3 -m unittest tests.test_pu_sync                  # one module
python3 -m unittest tests.test_pu_sync.TestListBranches.test_returns_names
```

Tests never hit the network: they `mock.patch.object` the `pu_github`
helpers (`get_json`, `download_to`, ...), so new network-touching code
should go through `pu_github` to stay mockable.

The tkinter GUI layer itself is not unit-tested (no display in CI); see
`README.md`'s manual testing checklist for what that layer needs.

## Building and releasing

- The version lives only in `psxhacks-updater.version` (bundled into the
  EXE as PyInstaller data; read back via `psxhacks_version.get_version()`,
  which uses `sys._MEIPASS` when frozen). Bump it with `./release.py`
  (`--minor`/`--major`), which never commits, tags, or pushes.
- CI (`.github/workflows/build.yml`, Windows runner) builds
  `psxhacks-updater.spec` and creates a GitHub Release only when a push to
  `main` or `testing` changes the version file (or on manual dispatch).
  Tags are `psxhacks-updater-v<version>` on `main` and
  `psxhacks-updater-v<version>-testing` (a prerelease) on `testing`;
  `pu_selfupdate.py` parses that tag prefix and uses `releases/latest`, so
  it only ever sees non-prerelease `main` builds.
- The only third-party runtime dependencies are `packaging` and
  `truststore` (both also listed as PyInstaller hidden imports in the
  spec); everything else is stdlib.
