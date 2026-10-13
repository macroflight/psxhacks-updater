# psxhacks-updater

A single self-contained Windows GUI tool that sets up and updates a local
[psxhacks](https://github.com/macroflight/psxhacks) checkout, with no git
client and no GitHub authentication required.

## Usage

1. Place the EXE in the directory where psxhacks should live (it ends up in
   a `psxhacks` subfolder next to it).
2. Run it. Pick a branch from the dropdown (populated from GitHub's real
   branch list; `main` and `testing` are the two officially supported
   ones -- picking anything else shows a warning, but doesn't block you).
3. It checks whether an update is available for that branch and enables an
   **Install**/**Update** button only when there's actually something to
   do, plus an always-available **Reinstall** button for forcing a full
   fresh sync regardless. Changing the branch re-checks against the
   newly-selected one; **Check for updates** re-checks on demand (e.g.
   when the tool has been left open for a while), as does returning from
   the History page. The **Installed version** box shows exactly which
   commit you have (commit ID, message, author, date).
4. **History...** opens a page listing that branch's recent commits (date,
   author, message) and lets you switch straight to any one of them --
   an upgrade or a downgrade, your choice.
5. Every action asks for confirmation before doing anything.

## What it does

- **First-time setup and every later update** go through the same tool and
  the same buttons -- there's no separate installer.
- **If an existing, unmanaged folder is found** (not something this tool
  set up -- e.g. a plain git clone, or something else entirely) at the
  target location, it tells you and asks you to rename or remove it first,
  rather than silently offering to replace it.
- **No git required.** It downloads the chosen branch or commit as a plain
  ZIP from GitHub over HTTPS and swaps it into place atomically. This
  makes it immune to upstream force-pushes by construction -- it never
  merges or rebases against local history, it just replaces the whole
  tree with a fresh snapshot every time.
- **Detects local drift.** After every sync it writes a manifest (a hash of
  every file). If you've hand-edited a file inside the checkout, or only
  partially updated it some other way, the tool (and a small check wired
  into `psxhacks`' own `start_scripts/common.ps1`) will notice, show you
  what changed, and ask before discarding it.
- **Updates itself** when a newer release is published, before doing
  anything else.

Not currently included: any check of your Python environment (there was a
venv-setup-wizard handoff feature here, but it couldn't be interacted with
in practice and was pulled pending a redesign).

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
points, version comparison, branch/commit listing) is. The GUI layer needs
manual testing on a real Windows machine:

1. Fresh run, nothing installed yet -- branch dropdown is populated from
   GitHub, status says not installed, button says "Install" and is
   enabled; Reinstall is disabled (nothing to reinstall yet).
2. Click Install, confirm -- syncs, then re-checks status (should now show
   "up to date"); Reinstall and History become enabled.
3. Run again on the same, now-clean checkout -- Update stays disabled
   until something changes upstream; Reinstall stays enabled regardless.
   Leave it open, push a commit upstream, click **Check for updates** --
   status should switch to "Update available (installed X, latest Y)".
4. Switch the branch dropdown to something other than main/testing --
   confirm the warning dialog appears, and that the status check still
   proceeds afterward.
5. Hand-edit a file inside the synced `psxhacks` folder, then re-run --
   status shows the drifted file(s), button says "Update" and is enabled;
   confirming discards the edit and re-syncs.
6. Point it at a folder that already exists but was never synced by this
   tool (e.g. a plain git clone) -- it reports that and does *not* offer
   to replace it; Update/Reinstall/History all stay disabled.
7. Open a file inside the target folder (e.g. in Notepad) and click
   Update -- confirm a clear "close open files" message, not a raw
   exception, and that nothing was left half-replaced.
8. After an install, confirm the "Installed version" box shows the
   commit ID, author, date and message without scrolling at the default
   window size, with a scrollbar for longer messages. Run against a checkout synced by
   0.1.2 (no commit details in its manifest) -- the box should still fill
   in (fetched from GitHub), or say details are unavailable when offline.
9. Click History -- confirm the commit list loads (date/author/summary per
   row) and selecting a row shows its full message in the detail pane
   with no file-change list. Pick an older commit and switch to it --
   confirm it installs, and that re-checking status now shows an update
   is available again (since you're intentionally behind the branch tip).
10. Publish a newer test release of this tool itself, run the current EXE
   -- confirm it downloads the new one, hands off, and relaunches with the
   old EXE file actually replaced on disk.
11. Run a `start_*.ps1` in the main repo against a drifted checkout --
    confirm `Show-ErrorAndExit` lists the right files; confirm a
    `stop_*.ps1` is *not* blocked by the same drift.
