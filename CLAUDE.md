# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What this is

`psxhacks-updater` is a standalone Windows GUI tool (PyInstaller,
`console=False`) that sets up and updates a local checkout of the separate
[psxhacks](https://github.com/macroflight/psxhacks) repo for non-technical
end users, with no git client and no GitHub authentication required. See
`README.md` for the user-facing description.

## Architecture

- `psxhacks_updater.py` -- entry point and the `Controller` class, which
  drives the GUI: computes directory/update status (on a background
  thread) and reacts to the branch dropdown and Install/Update button
  (see `pu_gui.py`). Status is recomputed on every branch change and after
  every completed action; nothing happens automatically beyond the
  self-update check and (after a successful install/update) the venv
  check.
- `pu_manifest.py` -- builds/loads/diffs `.psxhacks-manifest.json`, the
  SHA256-per-file manifest written into the managed `psxhacks` checkout
  after every successful sync. This (not git) is how drift is detected.
- `pu_sync.py` -- `check_for_update()` (cheap commit-SHA check, used to
  decide whether the button should be enabled) and `sync()` (downloads a
  branch ZIP from GitHub, extracts it, and atomically swaps it in for the
  live checkout directory -- always does the full thing; the controller
  decides when that's warranted, not this module).
- `pu_selfupdate.py` -- checks this tool's own GitHub Releases for a newer
  version, downloads it, and bootstraps replacing the running EXE
  (`--finish-update <old_exe_path>`).
- `pu_venvcheck.py` -- validates the configured Python venv against the
  checkout's `requirements.txt`, and can hand off to the main repo's
  `start_scripts/setup_python_venv.ps1` wizard.
- `pu_override.py` -- generic editor for a single `$VarName = ...` line in
  the user's `psxhacks-start-override.ps1`, preserving everything else in
  the file untouched. Deliberately generic (not hardcoded to one variable
  name) -- a planned future wizard for managing the whole override file
  builds on this.
- `pu_github.py` -- tiny `urllib`-based GitHub REST helper shared by
  `pu_sync.py` and `pu_selfupdate.py`.
- `pu_gui.py` -- tkinter multi-page wizard shell: v1's one page has a
  branch dropdown, status/progress/log, and the Install/Update button.
  Structured for more pages to be added later (a planned guided
  master/slave sim setup flow), not as a single fixed-purpose window. Its
  thread-bridging methods (`set_status`/`log`/`ask_yes_no`/etc.) are safe
  to call from either the Tk main thread (dropdown/button event handlers)
  or the background worker thread the controller runs status checks and
  syncs on.
- `psxhacks_version.py` / `release.py` -- vendored from the main `psxhacks`
  repo (the former verbatim, the latter trimmed to this repo's single
  artifact). Keep in sync by hand if the main repo's versions change in a
  way that matters here.

## Conventions

- No git dependency anywhere in the shipped tool -- only plain HTTPS to
  GitHub's REST API and ZIP archive endpoints.
- An existing directory that isn't manifest-managed by this tool is never
  offered as something to replace -- the user is told to rename or remove
  it themselves. Every actual sync (install, update, or discarding local
  drift) only ever happens from the Update/Install button, and always
  asks for confirmation first via `pu_gui`, even when nothing destructive
  is at risk (e.g. a plain "nothing installed yet" install) -- the button
  being enabled at all already means the controller decided there's
  something to do; the confirmation is about *when*, not *whether*.
- `common.ps1`/`functions.ps1` and `setup_python_venv.ps1` in the main
  `psxhacks` repo have small, deliberate hooks for this tool (a manifest
  preflight check, and one `VENV_PYTHON=...` output line respectively) --
  see that repo's own `CLAUDE.md` and git history for the exact edits.

## Testing

```
python3 -m unittest discover tests
```

The tkinter GUI layer itself is not unit-tested (no display in CI); see
`README.md`'s manual testing checklist for what that layer needs.
