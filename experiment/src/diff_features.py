"""Signal B: deterministic diff features (S_edit). No API calls.

Inputs:  data/patches.jsonl, data/trigger_tests.json
Output:  results/patch_features.csv
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GUARD_RE = re.compile(r"^\s*(\}\s*)?(else\s+)?if\s*\(")
STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?[dDfFlL]?(?![\w.])")
TRIVIAL_NUMBERS = {"0", "1", "-1", "2"}


def changed_lines(diff, sign):
    other = "+++ " if sign == "+" else "--- "
    return [l[1:] for l in diff.splitlines() if l.startswith(sign) and not l.startswith(other)]


def is_code(line):
    s = line.strip()
    return bool(s) and not s.startswith(("//", "/*", "*"))


def literals(lines):
    lits = set()
    for line in lines:
        lits.update(s for s in STRING_RE.findall(line) if len(s) >= 2)
        lits.update(n.rstrip("dDfFlL") for n in NUMBER_RE.findall(line)
                    if n.rstrip("dDfFlL") not in TRIVIAL_NUMBERS)
    return lits


def main():
    trig = json.loads((ROOT / "data" / "trigger_tests.json").read_text())["bugs"]
    rows = []
    for line in open(ROOT / "data" / "patches.jsonl"):
        r = json.loads(line)
        # Trailing-whitespace-normalized diff (identical to the original for unaffected patches).
        added = [l for l in changed_lines(r["diff_for_model"], "+") if is_code(l)]
        removed = [l for l in changed_lines(r["diff_for_model"], "-") if is_code(l)]
        msg_text = "\n".join(trig.get(r["bug_id"], {}).get("messages", []))
        added_lits = literals(added)
        rows.append({
            "patch_id": r["patch_id"], "bug_id": r["bug_id"], "project": r["project"],
            "tool": r["tool"], "label": r["label"],
            "lines_added": r["lines_added"], "lines_removed": r["lines_removed"],
            "total_changed": r["lines_added"] + r["lines_removed"],
            "code_lines_added": len(added), "code_lines_removed": len(removed),
            "n_hunks": r["n_hunks"], "n_files": r["n_files"],
            "only_deletes": int(len(added) == 0 and len(removed) > 0),
            "adds_conditional_guard": int(any(GUARD_RE.match(l) for l in added)),
            # Proxy: Defects4J trigger_tests contain failure messages, not test source code.
            "literal_in_failing_test_message": int(any(lit in msg_text for lit in added_lits)),
            "has_trigger_test_info": int(r["bug_id"] in trig),
            "whitespace_normalized": int(r["whitespace_normalized"]),
        })
    out = ROOT / "results" / "patch_features.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
