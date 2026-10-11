"""Generic editor for a single "$VarName = ..." line in an override file.

Used today only for $PsxhacksPython (see pu_venvcheck.py), but written as
a generic "find/replace a named PowerShell variable assignment line,
preserving everything else byte-for-byte" utility, parameterized on
variable name -- not hardcoded to one variable -- so a planned future
wizard for managing the whole psxhacks-start-override.ps1 file can build
on this instead of needing a rewrite.
"""
import re

_TERMINATOR_RE = re.compile(r"(\r\n|\r|\n)\Z")


def _variable_line_re(var_name):
    return re.compile(r"^\s*#?\s*\$" + re.escape(var_name) + r"\s*=", re.IGNORECASE)


def find_variable_line(lines, var_name):
    """Return the index of the line assigning $var_name (active or commented out).

    lines is a list of raw lines, each still carrying its own original
    line terminator (e.g. from str.splitlines(keepends=True)). Matches
    both an active assignment ($Var = ...) and a commented-out one
    (#$Var = ... or # $Var = ...), since that's how a not-yet-configured
    override file ships it (see psxhacks-start-override-EXAMPLE.ps1).
    Returns None if no such line exists anywhere.
    """
    pattern = _variable_line_re(var_name)
    for index, line in enumerate(lines):
        if pattern.match(line):
            return index
    return None


def set_variable(override_path, var_name, value):
    """Rewrite the line assigning $var_name in override_path to an active value.

    Preserves every other line byte-for-byte, including the file's
    original line endings -- only the matched line's content changes,
    reusing that same line's own terminator.

    Returns True if a line was found and rewritten. Returns False if no
    matching line exists anywhere in the file -- callers must not guess
    or insert one in that case (the file may have more than one plausible
    variant, e.g. a no-router profile, or the user may have deleted the
    line entirely); instead they should tell the user the exact line to
    add and to which file.
    """
    with open(override_path, "r", encoding="utf-8", newline="") as handle:
        lines = handle.readlines()

    index = find_variable_line(lines, var_name)
    if index is None:
        return False

    terminator_match = _TERMINATOR_RE.search(lines[index])
    terminator = terminator_match.group(1) if terminator_match else ""
    lines[index] = f'${var_name} = "{value}"{terminator}'

    with open(override_path, "w", encoding="utf-8", newline="") as handle:
        handle.writelines(lines)
    return True


def format_variable_line(var_name, value):
    """Return the exact line text that would be written for var_name/value.

    Used to tell the user what to add by hand when set_variable() returns
    False (no existing line found to rewrite).
    """
    return f'${var_name} = "{value}"'


def get_variable_value(override_path, var_name):
    """Return the current value of an ACTIVE $var_name = "..." line, or None.

    None covers every case where there is no single literal value to
    safely read back: the variable is absent, commented out, or set to
    something other than a plain double-quoted string (e.g. built from
    other variables/expressions) -- common.ps1 itself would reject most
    of those anyway (see pu_venvcheck.is_valid_venv()), so callers should
    treat None the same as "not configured".
    """
    pattern = re.compile(r'^\s*\$' + re.escape(var_name) + r'\s*=\s*"([^"]*)"')
    try:
        with open(override_path, "r", encoding="utf-8", newline="") as handle:
            for line in handle:
                match = pattern.match(line)
                if match:
                    return match.group(1)
    except OSError:
        return None
    return None
