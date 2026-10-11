# psxhacks-updater

A single self-contained Windows GUI tool that sets up and updates a local
[psxhacks](https://github.com/macroflight/psxhacks) checkout, with no git
client and no GitHub authentication required.

## Usage

1. Place the EXE in the directory where psxhacks should live (it ends up in
   a `psxhacks` subfolder next to it).
2. Run it. Pick a branch from the dropdown (`main` or `testing`).
3. It checks whether an update is available for that branch and enables an
   **Install**/**Update** button only when there's actually something to
   do. Changing the branch re-checks against the newly-selected one.
4. Clicking the button asks for confirmation, then applies it.

## What it does

- **First-time setup and every later update** go through the same tool and
  the same button -- there's no separate installer.
- **If an existing, unmanaged folder is found** (not something this tool
  set up -- e.g. a plain git clone, or something else entirely) at the
  target location, it tells you and asks you to rename or remove it first,
  rather than silently offering to replace it.
- **No git required.** It downloads the chosen branch as a plain ZIP from
  GitHub over HTTPS and swaps it into place atomically. This makes it
  immune to upstream force-pushes by construction -- it never merges or
  rebases against local history, it just replaces the whole tree with a
  fresh snapshot every time.
- **Detects local drift.** After every sync it writes a manifest (a hash of
  every file). If you've hand-edited a file inside the checkout, or only
  partially updated it some other way, the tool (and a small check wired
  into `psxhacks`' own `start_scripts/common.ps1`) will notice, show you
  what changed, and ask before discarding it.
- **Checks your Python environment** automatically after every successful
  install/update, against the checkout's current `requirements.txt`, and
  can hand off to the existing `start_scripts/setup_python_venv.ps1` wizard
  to fix it, updating your override file automatically afterward.
- **Updates itself** when a newer release is published, before doing
  anything else.

## Why a separate repo

Decoupled from the main `psxhacks` repo's own release cadence; keeps this
tool's build artifacts out of that repo's history.

## Building

See `psxhacks-updater.spec` (PyInstaller) and
`.github/workflows/build.yml` for how release builds are produced
automatically on a version bump (see `release.py`).

## Development

```
python3 -m unittest discover tests
```

The tkinter GUI layer itself isn't unit-tested (no display in CI) -- the
rest of the logic (manifest diffing, the atomic swap and its failure
points, version comparison, override-file editing, requirement checking)
is. The GUI layer needs manual testing on a real Windows machine:

1. Fresh run, nothing installed yet -- branch dropdown shows `main`/
   `testing`, status says not installed, button says "Install" and is
   enabled.
2. Click Install, confirm -- syncs, then runs the venv check
   automatically, then re-checks status (should now show "up to date").
3. Run again on the same, now-clean checkout -- button stays disabled
   until something changes upstream.
4. Switch the branch dropdown -- re-checks against the new branch; if its
   latest commit differs from what's installed, the button re-enables.
5. Hand-edit a file inside the synced `psxhacks` folder, then re-run --
   status shows the drifted file(s), button says "Update" and is enabled;
   confirming discards the edit and re-syncs.
6. Point it at a folder that already exists but was never synced by this
   tool (e.g. a plain git clone) -- it reports that and does *not* offer
   to replace it; the button stays disabled.
7. Open a file inside the target folder (e.g. in Notepad) and click
   Update -- confirm a clear "close open files" message, not a raw
   exception, and that nothing was left half-replaced.
8. Force an invalid/missing Python venv, let an update complete -- confirm
   the GUI message, the console setup wizard opening with its prompts
   still interactive, and the override file's `$PsxhacksPython` line being
   rewritten correctly afterward.
9. Publish a newer test release of this tool itself, run the current EXE
   -- confirm it downloads the new one, hands off, and relaunches with the
   old EXE file actually replaced on disk.
10. Run a `start_*.ps1` in the main repo against a drifted checkout --
    confirm `Show-ErrorAndExit` lists the right files; confirm a
    `stop_*.ps1` is *not* blocked by the same drift.
