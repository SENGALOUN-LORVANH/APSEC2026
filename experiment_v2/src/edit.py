"""S_edit LOC fallback (protocol.yaml scores.S_edit.fallback): changed executable LOC / executable LOC of the
changed buggy methods. GumTree AST-diff (primary) isn't wired up yet (deferred, thin pass) -- see
reports/D4J_DRIVER_NOTES.md / project notes for what's implemented vs deferred.
"""


def is_executable_line(line):
    s = line.strip()
    if not s:
        return False
    return not (s.startswith("//") or s.startswith("*") or s.startswith("/*"))


def method_exec_loc(method_source):
    """Executable LOC of one method's full source text (as returned by context.py's changed_method items)."""
    return sum(1 for line in method_source.splitlines() if is_executable_line(line))


def changed_exec_loc(diff_text):
    """Executable LOC actually added/removed by the diff (+/- lines, excluding the --- / +++ file headers)."""
    count = 0
    for line in diff_text.splitlines():
        if line[:3] in ("+++", "---"):
            continue
        if line[:1] in ("+", "-") and is_executable_line(line[1:]):
            count += 1
    return count
