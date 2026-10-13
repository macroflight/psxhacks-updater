# psxhacks-updater changelog

## Unreleased

- Fix "certificate verify failed" errors talking to GitHub on freshly
  installed Windows machines. HTTPS is now verified by Windows' own
  certificate verifier (via `truststore`), which fetches missing root
  certificates on demand like a browser does, instead of only trusting
  roots already present in the Windows certificate store.
- New **Installed version** box on the main page showing the installed
  commit's ID, message, author and date. The commit details are now also
  stored in the manifest at sync time; installs made by 0.1.2 and older
  get them fetched from GitHub instead.
- Updates now download the exact commit they checked, so the recorded
  commit ID can't be wrong if someone pushes to the branch mid-update.

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
