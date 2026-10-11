#!/usr/bin/env python3
"""Release management helper for psxhacks-updater.

Bumps the tool's version number (stored in psxhacks-updater.version -- see
psxhacks_version.py for how that reaches the running EXE) and reminds about
updating CHANGELOG.md. Does NOT commit, push, or tag -- that is left to the
user.

Trimmed from the main psxhacks repo's release.py: that one juggles many
addons (a name -> (version file, changelog file) dict, a --detect-changed
CI mode, and a commit-history scan across per-addon file ownership). This
repo has exactly one artifact, so none of that multi-addon machinery
applies -- CI here just checks whether psxhacks-updater.version is among a
push's changed files directly in bash (see .github/workflows/build.yml).

Usage:
    ./release.py            # bump the patch version, e.g. 1.2.3 -> 1.2.4
    ./release.py --minor    # bump the minor version, e.g. 1.2.3 -> 1.3.0
    ./release.py --major    # bump the major version, e.g. 1.2.3 -> 2.0.0

A patch release needs no changelog reminder. A minor release gets a
suggestion to add a changelog entry. A major release requires typing "YES"
to confirm the changelog has actually been updated.
"""
import argparse
import datetime
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent
_VERSION_FILE = _ROOT / 'psxhacks-updater.version'
_CHANGELOG_FILE = _ROOT / 'CHANGELOG.md'


def _parse_version(text: str) -> tuple:
    """Parse a MAJOR.MINOR.PATCH string into a 3-tuple of ints."""
    parts = text.strip().split('.')
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"version {text!r} is not in MAJOR.MINOR.PATCH form")
    return tuple(int(p) for p in parts)


def _bump(version: tuple, level: str) -> tuple:
    """Return the next version for level 'major', 'minor', or 'patch'."""
    ma, mi, pa = version
    if level == 'major':
        return (ma + 1, 0, 0)
    if level == 'minor':
        return (ma, mi + 1, 0)
    return (ma, mi, pa + 1)


def _format(version: tuple) -> str:
    return '.'.join(str(p) for p in version)


def _confirm(prompt: str, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {hint} ").strip().lower()
    if not answer:
        return default
    return answer.startswith('y')


def main() -> None:
    """Bump psxhacks-updater's version number and remind about its changelog."""
    parser = argparse.ArgumentParser(description="Bump psxhacks-updater's version number.")
    bump_group = parser.add_mutually_exclusive_group()
    bump_group.add_argument(
        '--minor', action='store_true',
        help="Bump the minor version instead of the patch version (e.g. 1.2.3 -> 1.3.0).")
    bump_group.add_argument(
        '--major', action='store_true',
        help="Bump the major version instead of the patch version (e.g. 1.2.3 -> 2.0.0).")
    args = parser.parse_args()

    level = 'major' if args.major else 'minor' if args.minor else 'patch'

    if not _VERSION_FILE.exists():
        print(f"Version file not found: {_VERSION_FILE}", file=sys.stderr)
        sys.exit(1)

    try:
        current = _parse_version(_VERSION_FILE.read_text(encoding='utf-8'))
    except ValueError as exc:
        print(f"Error reading {_VERSION_FILE}: {exc}", file=sys.stderr)
        sys.exit(1)

    new = _bump(current, level)
    current_str, new_str = _format(current), _format(new)

    print(f"The current psxhacks-updater version is {current_str}, "
          f"new version will be {new_str}")
    if not _confirm("Is this OK?", default=True):
        print("Aborted, no changes made.")
        sys.exit(0)

    if level == 'patch':
        # A patch release is small enough that no changelog reminder is
        # needed -- don't nag for the common case.
        pass
    else:
        print()
        if _CHANGELOG_FILE.exists():
            print(f"Changelog is located at: {_CHANGELOG_FILE.relative_to(_ROOT)}")
        else:
            print(f"No changelog file found (expected at "
                  f"{_CHANGELOG_FILE.relative_to(_ROOT)}).")
            if _confirm("Create it now with a skeleton entry?", default=True):
                today = datetime.date.today().isoformat()
                _CHANGELOG_FILE.write_text(
                    f"# psxhacks-updater changelog\n\n"
                    f"## {new_str} ({today})\n\n"
                    f"- \n",
                    encoding='utf-8')
                print(f"Created {_CHANGELOG_FILE.relative_to(_ROOT)} -- fill in "
                      f"the entry above before committing.")

        if level == 'minor':
            print("Consider adding a changelog entry for this release.")
        else:
            answer = input("Have you updated the changelog? Type YES to confirm: ")
            if answer.strip() != "YES":
                print("Aborted, no changes made.")
                sys.exit(0)

    _VERSION_FILE.write_text(new_str + "\n", encoding='utf-8')
    print()
    print(f"Updated {_VERSION_FILE.relative_to(_ROOT)} to {new_str}.")
    print("Remember to commit and push as needed -- this script does not do that for you.")


if __name__ == '__main__':
    main()
