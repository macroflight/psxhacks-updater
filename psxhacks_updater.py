"""Entry point for psxhacks-updater.

Usage model: place the EXE in the directory where psxhacks should live
(psxhacks itself ends up in a "psxhacks" subfolder next to it). On launch
it shows a branch dropdown and a status/log view; it checks whether an
update is available for whichever branch is selected and enables an
Install/Update button only when there's something to do. Clicking that
button asks for confirmation, then applies it. Changing the branch
dropdown re-checks against the newly-selected branch. See each imported
module's own docstring for how its piece of this actually works -- this
file is just orchestration wiring them together.
"""
import argparse
import pathlib
import sys

import pu_gui
import pu_manifest
import pu_override
import pu_selfupdate
import pu_sync
import pu_venvcheck

# (branch ref, dropdown label) -- "testing" is friendlier than exposing the
# real "public-testing" branch name in the UI.
BRANCH_CHOICES = [("main", "main"), ("public-testing", "testing")]
BRANCH_BY_LABEL = dict((label, branch) for branch, label in BRANCH_CHOICES)
LABEL_BY_BRANCH = dict(BRANCH_CHOICES)
DEFAULT_BRANCH = "main"

OVERRIDE_FILENAME = "psxhacks-start-override.ps1"
SETUP_VENV_SCRIPT_RELPATH = pathlib.Path("start_scripts") / "setup_python_venv.ps1"

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


class Controller:
    """Drives the GUI: checks status, reacts to branch changes and clicks."""

    def __init__(self, gui, target_dir, current_exe_path):
        self.gui = gui
        self.target_dir = pathlib.Path(target_dir)
        self.current_exe_path = current_exe_path
        self.state = None  # set by _after_status(); see its docstring

        gui.bind_branch_changed(self.on_branch_changed)
        gui.bind_update_clicked(self.on_update_clicked)

    def start(self):
        """Kick off the self-update check, then the first status check."""
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
        initial_branch = (manifest or {}).get("branch") or DEFAULT_BRANCH
        self.gui.set_branch_options(
            [label for _branch, label in BRANCH_CHOICES],
            LABEL_BY_BRANCH.get(initial_branch, initial_branch))
        self.refresh_status(initial_branch)

    # -- status check: read-only, safe to run any time, drives the button --

    def refresh_status(self, branch):
        self.gui.set_update_button(enabled=False)
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
        remote_commit = pu_sync.check_for_update(branch, manifest.get("source_commit"))
        return {
            "status": STATUS_MANAGED,
            "branch": branch,
            "manifest": manifest,
            "drifted": drifted,
            "remote_commit": remote_commit,
        }

    def _after_status(self, result, error):
        """Runs on the main thread. Updates self.state and the GUI to match."""
        self.gui.set_branch_combo_enabled(True)
        if error is not None:
            self.gui.show_error("Could not check status", str(error))
            return
        self.state = result
        status = result["status"]

        if status == STATUS_UNMANAGED:
            self.gui.set_status(
                f"{self.target_dir} exists but wasn't set up by this tool.")
            self.gui.log(
                "Rename or remove that folder, then run this tool again "
                "to install psxhacks.")
            self.gui.set_update_button(enabled=False)
            return

        if status == STATUS_NOT_INSTALLED:
            label = LABEL_BY_BRANCH.get(result["branch"], result["branch"])
            self.gui.set_status(f"psxhacks ({label}) is not installed yet.")
            self.gui.set_update_button(label="Install", enabled=True)
            return

        # STATUS_MANAGED
        drifted = result["drifted"]
        remote_commit = result["remote_commit"]
        branch_label = LABEL_BY_BRANCH.get(result["branch"], result["branch"])
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
            self.gui.set_status(f"Update available for {branch_label}.")
        else:
            commit = (result["manifest"].get("source_commit") or "?")[:8]
            self.gui.set_status(f"Up to date ({branch_label} @ {commit}).")
        self.gui.set_update_button(label="Update", enabled=needs_update)

    # -- user-driven actions --

    def on_branch_changed(self, branch_label):
        self.refresh_status(BRANCH_BY_LABEL.get(branch_label, branch_label))

    def on_update_clicked(self, branch_label):
        branch = BRANCH_BY_LABEL.get(branch_label, branch_label)
        if self.state is None:
            return

        if self.state["status"] == STATUS_NOT_INSTALLED:
            message = f"Install psxhacks ({branch_label}) into:\n\n{self.target_dir}"
        else:
            drifted = self.state.get("drifted") or []
            if drifted:
                shown = "\n".join(drifted[:15]) + ("\n..." if len(drifted) > 15 else "")
                message = (
                    f"{len(drifted)} local file(s) will be discarded and replaced:\n\n"
                    f"{shown}\n\nSync to the latest {branch_label}?")
            else:
                message = f"Update to the latest {branch_label}?"

        if not self.gui.ask_yes_no("Confirm", message):
            self.gui.log("Cancelled -- nothing was changed.")
            return

        self.gui.set_update_button(enabled=False)
        self.gui.set_branch_combo_enabled(False)
        self.gui.set_status(f"Syncing psxhacks ({branch_label})...")
        self.gui.run_in_background(
            self._do_update, branch, on_done=self._after_update)

    def _do_update(self, branch):
        self.target_dir.parent.mkdir(parents=True, exist_ok=True)
        return pu_sync.sync(self.target_dir, branch)

    def _after_update(self, result, error):
        if error is not None:
            self.gui.show_error("Update failed", str(error))
            self.refresh_status(self.state.get("branch", DEFAULT_BRANCH))
            return

        self.gui.log(f"Synced to {result.branch} @ {result.commit}.")
        if result.cleanup_warning:
            self.gui.log(f"Warning: {result.cleanup_warning}")
        self.gui.set_progress(1.0)

        self.gui.set_status("Checking Python environment...")
        self.gui.run_in_background(self._do_venv_check, on_done=self._after_venv_check)

    # -- venv check: automatic after every successful install/update --

    def _do_venv_check(self):
        override_path = self.target_dir.parent / OVERRIDE_FILENAME
        requirements_path = self.target_dir / "requirements.txt"
        current_python = pu_override.get_variable_value(
            override_path, pu_venvcheck.OVERRIDE_VARIABLE_NAME)

        needs_setup, reason = pu_venvcheck.needs_setup(current_python, requirements_path)
        if not needs_setup:
            self.gui.log("Python environment OK.")
            return

        self.gui.log(f"Python environment needs attention: {reason}")
        if not self.gui.ask_yes_no(
                "Python setup needed",
                "Your Python environment for psxhacks isn't ready "
                f"({reason}).\n\nRun the setup wizard now? It opens in its "
                "own window and will walk you through it."):
            self.gui.log("Skipped Python setup -- psxhacks may not run correctly yet.")
            return

        setup_script = self.target_dir / SETUP_VENV_SCRIPT_RELPATH
        if not setup_script.is_file():
            self.gui.show_error("Setup script not found", f"Could not find {setup_script}.")
            return

        self.gui.set_status("Waiting for the Python setup wizard...")
        new_python = pu_venvcheck.run_setup_wizard(setup_script)
        if new_python is None:
            self.gui.log("Python setup wizard did not complete successfully.")
            return

        self.gui.log(f"Python setup complete: {new_python}")
        manual_line = pu_override.format_variable_line(
            pu_venvcheck.OVERRIDE_VARIABLE_NAME, new_python)

        if not override_path.is_file():
            self.gui.show_error(
                "Override file not found",
                f"Could not find {override_path} to record the new Python path.\n\n"
                f"Add this line to it by hand:\n{manual_line}")
            return

        if not pu_venvcheck.apply_new_venv(override_path, new_python):
            self.gui.show_error(
                "Could not update override file",
                f"Could not find a $PsxhacksPython line in {override_path} to update.\n\n"
                f"Add this line to it by hand:\n{manual_line}")
            return

        self.gui.log(f"Updated {override_path.name} with the new Python path.")

    def _after_venv_check(self, _result, error):
        if error is not None:
            self.gui.show_error("Unexpected error", str(error))
        self.refresh_status(self.state.get("branch", DEFAULT_BRANCH))


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
