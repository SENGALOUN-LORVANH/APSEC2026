"""Verify that every whitespace-normalized diff is equivalent to its original.

For each hunk of the original diff, apply the rebuilt diff to the original's old side and check that
the result equals the original's new side (trailing whitespace ignored).

Output: data/normalization_check.json
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def hunks(diff):
    """-> list of (file, old_start, body_lines)"""
    out, path, cur = [], None, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path, cur = line[4:].strip(), None
        elif line.startswith("--- "):
            cur = None
        elif m := HUNK_RE.match(line):
            cur = (path, int(m.group(1)), [])
            out.append(cur)
        elif cur is not None and not line.startswith("\\"):
            cur[2].append(line)
    return out


def sides(body):
    old = [l[1:].rstrip() for l in body if l[:1] in (" ", "-", "")]
    new = [l[1:].rstrip() for l in body if l[:1] in (" ", "+", "")]
    return old, new


def apply(old_lines, old_start, patch_hunks, path):
    result, ln, end = [], old_start, old_start + len(old_lines)
    inside = sorted((h for h in patch_hunks if h[0] == path and old_start <= h[1] < end), key=lambda h: h[1])
    for _, hunk_start, body in inside:
        while ln < hunk_start:
            result.append(old_lines[ln - old_start])
            ln += 1
        for line in body:
            kind, text = line[:1], line[1:].rstrip()
            if kind in (" ", ""):
                if old_lines[ln - old_start] != text:
                    return None, f"context mismatch at line {ln}"
                result.append(text)
                ln += 1
            elif kind == "-":
                if old_lines[ln - old_start] != text:
                    return None, f"removed-line mismatch at line {ln}"
                ln += 1
            elif kind == "+":
                result.append(text)
    while ln < end:
        result.append(old_lines[ln - old_start])
        ln += 1
    return result, None


def main():
    records = [json.loads(l) for l in open(ROOT / "data" / "patches.jsonl")]
    checked, mismatches = 0, []
    for r in records:
        if not r["whitespace_normalized"]:
            if r["diff_for_model"] != r["diff"]:
                mismatches.append({"patch_id": r["patch_id"], "error": "unnormalized patch has altered diff"})
            continue
        checked += 1
        rebuilt = hunks(r["diff_for_model"])
        for path, start, body in hunks(r["diff"]):
            old, new = sides(body)
            got, err = apply(old, start, rebuilt, path)
            if err or got != new:
                mismatches.append({"patch_id": r["patch_id"], "file": path, "hunk_old_start": start,
                                   "error": err or "result differs from original new side"})
                break
    labels = {}
    for r in records:
        if r["whitespace_normalized"]:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
    result = {"normalized_patches_checked": checked, "unnormalized_patches": len(records) - checked,
              "mismatches": mismatches, "normalized_by_label": labels}
    (ROOT / "data" / "normalization_check.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
