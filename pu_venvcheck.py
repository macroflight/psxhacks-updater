"""Validate the configured Python venv against psxhacks' requirements.txt.

Mirrors start_scripts/common.ps1's own $PsxhacksPython validity checks
exactly (see is_valid_venv()), so the two never disagree about what counts
as a valid venv, and can hand off to the existing setup_python_venv.ps1
wizard to create/repair one.
"""
import json
import re
import subprocess
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

import pu_override

_PYTHON_VERSION_RE = re.compile(r"^Python 3\.13\.")
_VENV_PYTHON_MARKER_RE = re.compile(r"^VENV_PYTHON=(.+)$")

OVERRIDE_VARIABLE_NAME = "PsxhacksPython"


def is_valid_venv(python_exe):  # pylint: disable=too-many-return-statements
    """Return (True, None) if python_exe is a usable psxhacks venv, else (False, reason).

    Exactly mirrors common.ps1's own chain of checks (not set / not found /
    not .exe / no sibling 'activate' / not Python 3.13.x), in the same
    order, so this tool and common.ps1's own preflight always agree.
    """
    if not python_exe:
        return False, "not set"
    path = Path(python_exe)
    if not path.is_file():
        return False, f"not found: {python_exe}"
    if path.suffix.lower() != ".exe":
        return False, f"not an .exe file: {python_exe}"
    if not (path.parent / "activate").exists():
        return False, (
            f"does not look like it is inside a Python virtual environment "
            f"(no 'activate' next to it): {python_exe}")
    try:
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True,
            timeout=10, check=False)
    except OSError as exc:
        return False, f"could not run --version: {exc}"
    version_output = (result.stdout + result.stderr).strip()
    if not _PYTHON_VERSION_RE.match(version_output):
        return False, f"reports '{version_output}', not Python 3.13.x: {python_exe}"
    return True, None


def _parse_requirements(requirements_path):
    requirements = []
    for raw_line in Path(requirements_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirements.append(Requirement(line))
        except InvalidRequirement:
            continue
    return requirements


def _installed_versions(python_exe):
    result = subprocess.run(
        [str(python_exe), "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True, timeout=60, check=True)
    data = json.loads(result.stdout)
    return {entry["name"].lower().replace("_", "-"): entry["version"] for entry in data}


def check_requirements(python_exe, requirements_path):
    """Return a list of human-readable unmet-requirement strings (empty = satisfied).

    Checks actual version specifiers via packaging.specifiers, not just
    package presence -- entirely offline (pip list --format=json reads
    only what's already installed, no PyPI/network access).
    """
    requirements = _parse_requirements(requirements_path)
    try:
        installed = _installed_versions(python_exe)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError):
        return [str(req) for req in requirements]

    unmet = []
    for req in requirements:
        if req.marker is not None and not req.marker.evaluate():
            continue
        name = req.name.lower().replace("_", "-")
        installed_version = installed.get(name)
        if installed_version is None:
            unmet.append(f"{req.name} (missing)")
        elif req.specifier and not req.specifier.contains(installed_version, prereleases=True):
            unmet.append(f"{req.name} (have {installed_version}, need {req.specifier})")
    return unmet


def needs_setup(python_exe, requirements_path):
    """Return (True, reason) if the venv needs (re)creating, else (False, None)."""
    valid, reason = is_valid_venv(python_exe)
    if not valid:
        return True, reason
    unmet = check_requirements(python_exe, requirements_path)
    if unmet:
        return True, "requirements not satisfied: " + ", ".join(unmet)
    return False, None


def run_setup_wizard(setup_script_path):
    """Launch setup_python_venv.ps1 interactively and capture its result.

    Only stdout is piped (to scrape the one VENV_PYTHON=... marker line --
    see the matching edit in setup_python_venv.ps1, which uses Write-Output
    for that one line specifically because every other line in that script
    uses Write-Host, which bypasses the stdout stream entirely and keeps
    displaying live regardless). stdin and stderr are left inherited, so
    the wizard's own Read-Host prompts keep working normally. This process
    (the updater EXE) is windowed/has no console of its own, so Windows
    automatically allocates a new console window for this child -- no
    special creation flags needed.

    Returns the captured venv python.exe path, or None if the wizard
    failed or never printed the marker line.
    """
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(setup_script_path)],
        stdout=subprocess.PIPE, text=True)

    venv_python = None
    for line in proc.stdout:
        match = _VENV_PYTHON_MARKER_RE.match(line.strip())
        if match:
            venv_python = match.group(1)
    proc.wait()
    return venv_python


def apply_new_venv(override_path, python_exe):
    """Record the new venv's python.exe in the override file.

    Thin wrapper over pu_override.set_variable() -- returns the same
    True/False contract (False meaning no existing line was found to
    rewrite, so the caller must show instructions instead of guessing).
    """
    return pu_override.set_variable(override_path, OVERRIDE_VARIABLE_NAME, str(python_exe))
