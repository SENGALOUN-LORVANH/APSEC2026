"""M2 baseline features: the v1 handcrafted diff features, ported unchanged from v1
(`experiment/src/diff_features.py` at tag `rebuild-v1-snapshot`).

This is the protocol's "diff-feature baseline" (M2). It is NOT static analysis and must never be described as
CFG/PDG analysis. Computed from the normalized diffs plus Defects4J trigger-test failure messages; no LLM,
no workspace, fully deterministic.

Input:  data/dataset_manifest.csv, data/normalized_patches/<patch_id>.diff, data/trigger_tests.json
Output: results/diff_features_baseline.csv
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ["lines_added", "lines_removed", "total_changed", "code_lines_added", "code_lines_removed",
            "n_hunks", "n_files", "only_deletes", "adds_conditional_guard",
            "literal_in_failing_test_message"]

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


def diff_counts(diff):
    files, hunks, added, removed = set(), 0, 0, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            files.add(line[4:].strip())
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            hunks += 1
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return len(files), hunks, added, removed


def features_for(diff, failure_messages):
    n_files, n_hunks, added_n, removed_n = diff_counts(diff)
    added = [l for l in changed_lines(diff, "+") if is_code(l)]
    removed = [l for l in changed_lines(diff, "-") if is_code(l)]
    added_lits = literals(added)
    return {
        "lines_added": added_n, "lines_removed": removed_n, "total_changed": added_n + removed_n,
        "code_lines_added": len(added), "code_lines_removed": len(removed),
        "n_hunks": n_hunks, "n_files": n_files,
        "only_deletes": int(len(added) == 0 and len(removed) > 0),
        "adds_conditional_guard": int(any(GUARD_RE.match(l) for l in added)),
        # Proxy: Defects4J ships trigger-test failure messages, not test source (same definition as v1).
        "literal_in_failing_test_message": int(any(lit in failure_messages for lit in added_lits)),
    }


def main():
    trig_path = ROOT / "data" / "trigger_tests.json"
    trig = json.loads(trig_path.read_text())["bugs"] if trig_path.exists() else {}
    with open(ROOT / "data" / "dataset_manifest.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        path = ROOT / r["normalized_patch_location"]
        if not path.exists():
            continue
        msgs = "\n".join(trig.get(r["bug_id"], {}).get("messages", []))
        out.append({"patch_id": r["patch_id"], "bug_id": r["bug_id"],
                    "has_trigger_test_info": int(r["bug_id"] in trig),
                    **features_for(path.read_text(), msgs)})
    dest = ROOT / "results" / "diff_features_baseline.csv"
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["patch_id", "bug_id", "has_trigger_test_info"] + FEATURES)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows to {dest}")


if __name__ == "__main__":
    main()
