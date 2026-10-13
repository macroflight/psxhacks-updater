"""Entry point for psxhacks-updater.

Usage model: place the EXE in the directory where psxhacks should live
(psxhacks itself ends up in a "psxhacks" subfolder next to it). On launch
it fetches the real branch list from GitHub and shows a branch dropdown
plus a status/log view; it checks whether an update is available for
whichever branch is selected and enables an Install/Update button only
when there's something to do, plus an always-available Reinstall button
for forcing a full fresh sync regardless, and a History button to browse
that branch's commits and jump to any one of them (an upgrade or a
downgrade). Changing the branch dropdown re-checks against the
newly-selected branch, warning if it isn't one of the two officially
supported ones. See each imported module's own docstring for how its
piece of this actually works -- this file is just orchestration wiring
them together.
"""
import argparse
import pathlib
import sys

import pu_github
import pu_gui
import pu_manifest
import pu_selfupdate
import pu_sync

RECOMMENDED_BRANCHES = {"main", "testing"}
# Used only if GitHub's branch list can't be fetched at all (offline,
# rate-limited, etc.) -- without this, a fetch failure would leave the
# dropdown completely empty and the tool unusable.
FALLBACK_BRANCHES = ["main", "testing"]
DEFAULT_BRANCH = "main"

# Status strings for the directory itself, independent of any branch.
STATUS_NOT_INSTALLED = "not_installed"
STATUS_UNMANAGED = "unmanaged"
STATUS_MANAGED = "managed"


def _default_target_dir():
    """One level above wherever this EXE/script itself lives, /psxhacks."""
    if getattr(sys, "frozen", False):
        own_dir = pathlib.Path(sys.executable).resolve().parent
    else:
        own_dir = pathlib.Path(__file__).resolve().parent
    return own_dir / "psxhacks"


class Controller:  # pylint: disable=too-many-instance-attributes
    """Drives the GUI: checks status, reacts to branch changes and clicks."""

    def __init__(self, gui, target_dir, current_exe_path):
        self.gui = gui
        self.target_dir = pathlib.Path(target_dir)
        self.current_exe_path = current_exe_path
        self.branches = []  # populated by _after_list_branches()
        self.current_branch = DEFAULT_BRANCH
        self.state = None  # set by _after_status(); see its docstring
        self.history_commits = {}  # sha -> commit dict, from the last history fetch

        gui.bind_branch_changed(self.on_branch_changed)
        gui.bind_update_clicked(self.on_update_clicked)
        gui.bind_reinstall_clicked(self.on_reinstall_clicked)
        gui.bind_history_clicked(self.on_history_clicked)
        gui.bind_history_switch_clicked(self.on_history_switch_clicked)
        gui.bind_history_back_clicked(self.on_history_back_clicked)

    def start(self):
        """Kick off the self-update check, then the branch list, then status."""
        self.gui.set_status("Checking for a newer version of this tool...")
        self.gui.run_in_background(
            pu_selfupdate.check_and_apply, self.current_exe_path,
            on_done=self._after_self_update_check)

    def _after_self_update_check(self, handing_off, error):
        if error is not None:
            self.gui.show_error("Unexpected error", str(error))
            self.gui.close()
            return
        if handing_off:
            self.gui.set_status("Updating psxhacks-updater itself...")
            self.gui.close()
            return

        manifest = pu_manifest.load(self.target_dir) if self.target_dir.is_dir() else None
        self.current_branch = (manifest or {}).get("branch") or DEFAULT_BRANCH
        self.gui.set_status("Fetching branch list...")
        self.gui.run_in_background(pu_sync.list_branches, on_done=self._after_list_branches)

    def _after_list_branches(self, branches, error):
        if error is not None or not branches:
            branches = list(FALLBACK_BRANCHES)
        if self.current_branch not in branches:
            # Whatever the manifest recorded should stay selectable even
            # if the fetch didn't happen to include it (e.g. a branch
            # since deleted upstream, or the fetch fell back to the
            # minimal list above).
            branches = [self.current_branch] + branches
        self.branches = branches
        self._render_branch_combo()
        self.refresh_status(self.current_branch)

    def _render_branch_combo(self):
        """Restore the branch combo's values/selection after a page rebuild."""
        self.gui.set_branch_options(self.branches, self.current_branch)

    # -- status check: read-only, safe to run any time, drives the buttons --

    def refresh_status(self, branch):
        self.current_branch = branch
        self.gui.set_update_button(enabled=False)
        self.gui.set_reinstall_button(enabled=False)
        self.gui.set_history_button(enabled=False)
        self.gui.set_branch_combo_enabled(False)
        self.gui.set_status("Checking status...")
        self.gui.clear_log()
        self.gui.run_in_background(
            self._compute_status, branch, on_done=self._after_status)

    def _compute_status(self, branch):
        """Runs off the main thread. Returns a dict describing the current state."""
        if not self.target_dir.is_dir():
            return {"status": STATUS_NOT_INSTALLED, "branch": branch}

        manifest = pu_manifest.load(self.target_dir)
        if manifest is None:
            return {"status": STATUS_UNMANAGED}

        drifted = pu_manifest.diff(self.target_dir, manifest)
        source_commit = manifest.get("source_commit")
        remote_commit = pu_sync.check_for_update(branch, source_commit)
        installed_commit = manifest.get("source_commit_info")
        if installed_commit is None and source_commit:
            # Manifest from before commit details were recorded (<= 0.1.2),
            # or the lookup failed at sync time -- best-effort fetch now.
            try:
                installed_commit = pu_sync.get_commit(source_commit)
            except (pu_github.GitHubError, KeyError, TypeError):
                installed_commit = None
        return {
            "status": STATUS_MANAGED,
            "branch": branch,
            "manifest": manifest,
            "drifted": drifted,
            "remote_commit": remote_commit,
            "installed_commit": installed_commit,
        }

    def _after_status(self, result, error):
        self.gui.set_branch_combo_enabled(True)
        if error is not None:
            self.gui.show_error("Could not check status", str(error))
            return
        self.state = result
        self._render_status()

    def _render_status(self):
        """Updates the status page from self.state. Main-thread only, no I/O."""
        result = self.state
        status = result["status"]

        self._render_installed_info()

        if status == STATUS_UNMANAGED:
            self.gui.set_status(
                f"{self.target_dir} exists but wasn't set up by this tool.")
            self.gui.log(
                "Rename or remove that folder, then run this tool again "
                "to install psxhacks.")
            self.gui.set_update_button(enabled=False)
            self.gui.set_reinstall_button(enabled=False)
            self.gui.set_history_button(enabled=False)
            return

        if status == STATUS_NOT_INSTALLED:
            self.gui.set_status(f"psxhacks ({result['branch']}) is not installed yet.")
            self.gui.set_update_button(label="Install", enabled=True)
            self.gui.set_reinstall_button(enabled=False)
            self.gui.set_history_button(enabled=True)
            return

        # STATUS_MANAGED
        drifted = result["drifted"]
        remote_commit = result["remote_commit"]
        branch = result["branch"]
        needs_update = bool(drifted) or remote_commit is not None

        if drifted:
            self.gui.log(f"{len(drifted)} local file(s) differ from the last sync:")
            for entry in drifted:
                self.gui.log(f"  {entry}")

        if remote_commit == "unknown":
            self.gui.log(
                "Could not check GitHub for updates (offline?) -- Update will "
                "still work, it just can't tell in advance if one's needed.")

        if needs_update:
            self.gui.set_status(f"Update available for {branch}.")
        else:
            commit = (result["manifest"].get("source_commit") or "?")[:8]
            self.gui.set_status(f"Up to date ({branch} @ {commit}).")
        self.gui.set_update_button(label="Update", enabled=needs_update)
        # Always available while managed, even when nothing's actually
        # new -- a deliberate "nuke and resync anyway" escape hatch.
        self.gui.set_reinstall_button(enabled=True)
        self.gui.set_history_button(enabled=True)

    def _render_installed_info(self):
        """Fill the installed-version pane from self.state. Main-thread only."""
        result = self.state
        status = result["status"]
        if status == STATUS_NOT_INSTALLED:
            text = "Nothing installed yet."
        elif status == STATUS_UNMANAGED:
            text = "Unknown -- this folder wasn't set up by this tool."
        else:
            manifest = result["manifest"]
            installed = result.get("installed_commit")
            header = (
                f"Branch: {manifest.get('branch') or '?'}    "
                f"Synced: {manifest.get('synced_at_utc') or '?'}\n")
            if installed is not None:
                text = header + pu_gui.format_commit_details(installed)
            else:
                text = header + (
                    f"commit {manifest.get('source_commit') or '?'}\n"
                    f"(commit details unavailable -- could not reach GitHub)\n")
        self.gui.set_installed_info(text.rstrip("\n"))

    # -- branch selection --

    def on_branch_changed(self, branch):
        if branch not in RECOMMENDED_BRANCHES:
            self.gui.show_warning(
                "Unsupported branch",
                f"'{branch}' is not one of the officially supported branches "
                f"(main, testing). It may be experimental, broken, or "
                f"abandoned -- proceed with caution.")
        self.refresh_status(branch)

    # -- install / update / reinstall --

    def on_update_clicked(self, branch):
        if self.state is None:
            return

        if self.state["status"] == STATUS_NOT_INSTALLED:
            message = f"Install psxhacks ({branch}) into:\n\n{self.target_dir}"
        else:
            drifted = self.state.get("drifted") or []
            if drifted:
                shown = "\n".join(drifted[:15]) + ("\n..." if len(drifted) > 15 else "")
                message = (
                    f"{len(drifted)} local file(s) will be discarded and replaced:\n\n"
                    f"{shown}\n\nSync to the latest {branch}?")
            else:
                message = f"Update to the latest {branch}?"

        self._confirm_and_run(message, self._do_update, branch)

    def on_reinstall_clicked(self, branch):
        if self.state is None or self.state["status"] != STATUS_MANAGED:
            return
        message = (
            f"This discards your entire psxhacks folder and reinstalls "
            f"{branch} from scratch:\n\n{self.target_dir}\n\nContinue?")
        self._confirm_and_run(message, self._do_update, branch)

    def _do_update(self, branch):
        self.target_dir.parent.mkdir(parents=True, exist_ok=True)
        return pu_sync.sync(self.target_dir, branch)

    # -- commit history --

    def on_history_clicked(self, branch):
        self.gui.set_update_button(enabled=False)
        self.gui.set_reinstall_button(enabled=False)
        self.gui.set_history_button(enabled=False)
        self.gui.set_branch_combo_enabled(False)
        self.gui.set_status(f"Fetching commit history for {branch}...")
        self.gui.run_in_background(
            pu_sync.list_commits, branch, on_done=self._after_list_commits)

    def _after_list_commits(self, commits, error):
        if error is not None:
            self.gui.show_error("Could not fetch commit history", str(error))
            self._render_status()
            self.gui.set_branch_combo_enabled(True)
            return
        self.history_commits = {c["sha"]: c for c in commits}
        self.gui.show_history_page(commits)

    def on_history_switch_clicked(self, commit_sha):
        branch = self.current_branch
        message = (
            f"Discard your entire psxhacks folder and replace it with commit "
            f"{commit_sha[:8]} from {branch}?\n\n"
            f"This can be either an upgrade or a downgrade from what's "
            f"currently installed:\n\n{self.target_dir}")
        self._confirm_and_run(
            message, self._do_switch_to_commit, branch, commit_sha, back_to_status=True)

    def on_history_back_clicked(self):
        self.gui.show_status_page()
        self._render_branch_combo()
        if self.state is not None:
            self._render_status()

    def _do_switch_to_commit(self, branch, commit_sha):
        self.target_dir.parent.mkdir(parents=True, exist_ok=True)
        return pu_sync.sync_to_commit(
            self.target_dir, branch, commit_sha,
            commit_info=self.history_commits.get(commit_sha))

    # -- shared confirm-then-run-in-background plumbing --

    def _confirm_and_run(self, message, func, *args, back_to_status=False):
        if not self.gui.ask_yes_no("Confirm", message):
            self.gui.log("Cancelled -- nothing was changed.")
            return

        if back_to_status:
            self.gui.show_status_page()
            self._render_branch_combo()

        self.gui.set_update_button(enabled=False)
        self.gui.set_reinstall_button(enabled=False)
        self.gui.set_history_button(enabled=False)
        self.gui.set_branch_combo_enabled(False)
        self.gui.set_status("Syncing psxhacks...")
        self.gui.run_in_background(func, *args, on_done=self._after_update)

    def _after_update(self, result, error):
        if error is not None:
            self.gui.show_error("Update failed", str(error))
            self.refresh_status(self.current_branch)
            return

        self.gui.log(f"Synced to {result.branch} @ {result.commit}.")
        if result.cleanup_warning:
            self.gui.log(f"Warning: {result.cleanup_warning}")
        self.gui.set_progress(1.0)
        self.refresh_status(result.branch)


def main():
    """Parse arguments and run the updater (or the self-update bootstrap)."""
    parser = argparse.ArgumentParser(description="Set up and update a psxhacks checkout.")
    parser.add_argument(
        "--finish-update", metavar="OLD_EXE_PATH", default=None,
        help="Internal: used by a freshly-downloaded self-update to replace OLD_EXE_PATH.")
    parser.add_argument("--target-dir", type=pathlib.Path, default=None)
    args = parser.parse_args()

    if args.finish_update is not None:
        success = pu_selfupdate.finish_update(args.finish_update)
        sys.exit(0 if success else 1)

    current_exe_path = sys.executable if getattr(sys, "frozen", False) else __file__
    target_dir = args.target_dir or _default_target_dir()

    gui = pu_gui.UpdaterWindow()
    controller = Controller(gui, target_dir, current_exe_path)
    controller.start()
    gui.mainloop()


if __name__ == "__main__":
    main()
