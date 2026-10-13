# psxhacks-updater changelog

## 0.1.2

- Removed the Python venv check, its `setup_python_venv.ps1` wizard
  handoff, and the override-file editor it used -- the console wizard it
  launched couldn't actually be interacted with in practice.
- Branch names are now fetched live from GitHub instead of hardcoded
  (this also fixes the testing branch's name: `testing`, not
  `public-testing`). Picking anything other than `main`/`testing` shows a
  warning but is never blocked.
- New always-available **Reinstall** button: a full fresh sync whether or
  not an update is detected.
- New **History** page: browse a branch's recent commits and switch to
  any one of them, upgrade or downgrade.

## 0.1.1

- CI: fix the release build failing on the very first push (no parent
  commit to diff the version file against).

## 0.1.0

- Initial implementation: sync/manifest-based checkout management, venv
  check, override file editing, self-update.
