"""Parse Wang et al. (ASE'20) Patches.zip into per-patch records and dataset statistics.

Label mapping follows the source folder names:
  Dsame, Ddifferent, Dcorrect -> correct
  Doverfitting                -> overfitting
  Error                       -> excluded (not assigned a label)

Outputs:
  data/patches.jsonl       one record per usable patch
  data/excluded.csv        excluded patches + reason
  data/duplicates.csv      groups of byte-identical diffs (reported, not removed)
  data/dataset_stats.json  counts overall / per project / per tool
"""
import csv
import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "Patches"
OUT = ROOT / "data"

LABEL_OF = {"Dsame": "correct", "Ddifferent": "correct", "Dcorrect": "correct",
            "Doverfitting": "overfitting"}
# "plusible" is a typo present in 9 Arja filenames of the source dataset.
NAME_RE = re.compile(r"^patch(\d+)-([A-Za-z]+)-(\d+)-([A-Za-z0-9_]+?)(-pl(?:a)?usible)?\.patch$")

# Verbatim from the Zenodo record 3730599 description (fetched 2026-09-14).
ZENODO_EXCLUSIONS = {
    "Zenodo note: Mockito project patch": ["Kali-A-Mockito-10", "Arja-Mockito-10"],
    "Zenodo note: does not pass plausibility check": [
        "Kali-Closure-133", "kPAR-Chart-12", "FixMiner-Chart-12",
        "patch1-Lang-6-SketchFix-plausible", "patch2-Lang-6-SketchFix-plausible", "patch1-Math-2-SOFix"],
    "Zenodo note: mistakenly labeled": [
        "patch2-Lang-51-Jaid", "patch1-Lang-43-CapGen", "patch2-Lang-43-CapGen", "patch2-Math-53-CapGen",
        "patch2-Math-53-Jaid", "jKali-Lang-7", "ACS-Lang-35", "Arja-Math-35", "SimFix-Math-72",
        "SimFix-Closure-19", "Arja-Math-50", "SimFix-Lang-60"],
    "Zenodo note: borderline patch": ["ACS-Lang-7", "kPAR-Lang-7", "TBar-Lang-7"],
}


def parse_identifier(ident):
    """'patch2-Lang-51-Jaid[-plausible]' -> index given; 'jKali-Lang-7' -> all indices."""
    parts = ident.split("-")
    if re.fullmatch(r"patch\d+", parts[0]):
        # Full filename form: the -plausible suffix is part of the name and must match exactly,
        # because Patches_others holds e.g. both patch1-Lang-43-CapGen and patch1-Lang-43-CapGen-plausible.
        return {"index": int(parts[0][5:]), "bug_id": f"{parts[1]}-{parts[2]}", "tool": parts[3],
                "plausible": parts[-1] == "plausible"}
    return {"index": None, "bug_id": f"{parts[-2]}-{parts[-1]}", "tool": "-".join(parts[:-2]),
            "plausible": None}


def zenodo_exclusion(rec, match_counter):
    for reason, idents in ZENODO_EXCLUSIONS.items():
        for ident in idents:
            p = parse_identifier(ident)
            if (rec["tool"] == p["tool"] and rec["bug_id"] == p["bug_id"]
                    and (p["index"] is None or rec["patch_index"] == p["index"])
                    and (p["plausible"] is None or rec["plausible_suffix"] == p["plausible"])):
                match_counter[(reason, ident)] += 1
                return f"{reason} ({ident})"
    return None


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def normalize_trailing_whitespace(text):
    """Rebuild each hunk ignoring trailing whitespace (no semantic effect in Java).

    Returns the rebuilt diff, or None when normalization does not reduce the changed-line count, so
    unaffected patches keep their original diff byte-for-byte.
    """
    out, hunk, starts = [], None, None

    def flush():
        if hunk is None:
            return
        old = [l[1:].rstrip() for l in hunk if l[:1] in (" ", "-", "")]
        new = [l[1:].rstrip() for l in hunk if l[:1] in (" ", "+", "")]
        for line in difflib.unified_diff(old, new, lineterm="", n=3):
            if line.startswith(("--- ", "+++ ")):
                continue
            m = re.match(r"^@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@$", line)
            if m:
                line = (f"@@ -{int(m.group(1)) + starts[0] - 1}{m.group(2) or ''} "
                        f"+{int(m.group(3)) + starts[1] - 1}{m.group(4) or ''} @@")
            out.append(line)

    for line in text.splitlines():
        m = HUNK_RE.match(line)
        if line.startswith(("--- ", "+++ ")):
            flush()
            hunk = None
            out.append(line)
        elif m:
            flush()
            hunk, starts = [], (int(m.group(1)), int(m.group(2)))
        elif hunk is not None and not line.startswith("\\"):
            hunk.append(line)
    flush()
    rebuilt = "\n".join(out) + "\n"
    changed = lambda t: sum(1 for l in t.splitlines()
                            if l[:1] in ("+", "-") and not l.startswith(("+++ ", "--- ")))
    return rebuilt if changed(rebuilt) < changed(text) else None


def diff_stats(text):
    files, hunks, added, removed = set(), 0, 0, 0
    for line in text.splitlines():
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
    return {"n_files": len(files), "n_hunks": hunks, "lines_added": added, "lines_removed": removed}


def main():
    records, excluded = [], []
    zenodo_matches = Counter()
    for path in sorted(RAW.rglob("*.patch")):
        rel = path.relative_to(RAW)
        if path.name.startswith("._") or "__MACOSX" in rel.parts:
            continue
        source, folder = rel.parts[0], rel.parts[1]
        m = NAME_RE.match(path.name)
        text = path.read_text(encoding="utf-8", errors="replace")
        base = {"patch_id": str(rel.with_suffix("")).replace("/", "__"), "path": str(rel),
                "source": source, "folder": folder}
        if not m:
            excluded.append({**base, "reason": "filename does not match expected pattern"})
            continue
        idx, project, bug, tool_in_name, plaus = m.groups()
        tool_dir = rel.parts[2] if len(rel.parts) >= 5 else None
        base.update({"project": project, "bug_id": f"{project}-{bug}",
                     "tool": tool_dir or tool_in_name, "tool_in_filename": tool_in_name,
                     "patch_index": int(idx), "plausible_suffix": bool(plaus)})
        hit = zenodo_exclusion(base, zenodo_matches)
        if hit:
            excluded.append({**base, "reason": hit})
            continue
        if folder not in LABEL_OF:
            excluded.append({**base, "reason": f"in source-dataset folder '{folder}' (no label)"})
            continue
        if not text.strip():
            excluded.append({**base, "reason": "empty diff"})
            continue
        normalized = normalize_trailing_whitespace(text)
        diff_for_model = normalized if normalized is not None else text
        records.append({**base, "label": LABEL_OF[folder],
                        "sha1": hashlib.sha1(text.encode()).hexdigest(),
                        "whitespace_normalized": normalized is not None,
                        **diff_stats(diff_for_model), "diff": text, "diff_for_model": diff_for_model})

    # Duplicate groups: identical diff for the same bug (and across bugs, reported separately).
    by_hash = defaultdict(list)
    for r in records:
        by_hash[r["sha1"]].append(r)
    dup_rows, label_conflicts = [], 0
    for h, grp in by_hash.items():
        if len(grp) < 2:
            continue
        labels = {r["label"] for r in grp}
        bugs = {r["bug_id"] for r in grp}
        conflict = len(labels) > 1
        label_conflicts += conflict
        for r in grp:
            dup_rows.append({"sha1": h, "patch_id": r["patch_id"], "bug_id": r["bug_id"],
                             "tool": r["tool"], "label": r["label"], "group_size": len(grp),
                             "same_bug": len(bugs) == 1, "label_conflict": conflict})

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "patches.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    with open(OUT / "excluded.csv", "w", newline="") as f:
        cols = ["patch_id", "path", "source", "folder", "project", "bug_id", "tool", "reason"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(excluded)
    with open(OUT / "zenodo_exclusion_matches.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["reason", "identifier", "files_matched"])
        for reason, idents in ZENODO_EXCLUSIONS.items():
            for ident in idents:
                w.writerow([reason, ident, zenodo_matches[(reason, ident)]])
    with open(OUT / "duplicates.csv", "w", newline="") as f:
        cols = ["sha1", "patch_id", "bug_id", "tool", "label", "group_size", "same_bug", "label_conflict"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(dup_rows)

    def counts(rows):
        c = Counter(r["label"] for r in rows)
        n = len(rows)
        return {"patches": n, "correct": c["correct"], "overfitting": c["overfitting"],
                "overfitting_rate": round(c["overfitting"] / n, 4) if n else None,
                "bugs": len({r["bug_id"] for r in rows})}

    per_bug = defaultdict(list)
    for r in records:
        per_bug[r["bug_id"]].append(r["label"])
    multi = {b: l for b, l in per_bug.items() if len(l) >= 2}
    stats = {
        "overall": counts(records),
        "per_project": {p: counts([r for r in records if r["project"] == p])
                        for p in sorted({r["project"] for r in records})},
        "per_source": {s: counts([r for r in records if r["source"] == s])
                       for s in sorted({r["source"] for r in records})},
        "per_folder": dict(Counter(r["folder"] for r in records)),
        "per_tool": dict(sorted(Counter(r["tool"] for r in records).items())),
        "whitespace_normalized_patches": [r["patch_id"] for r in records if r["whitespace_normalized"]],
        "excluded": {"total": len(excluded), "by_reason": dict(Counter(e["reason"] for e in excluded))},
        "duplicates": {"groups": len({d["sha1"] for d in dup_rows}),
                       "patches_in_groups": len(dup_rows),
                       "groups_with_label_conflict": label_conflicts,
                       "groups_spanning_multiple_bugs": len({d["sha1"] for d in dup_rows if not d["same_bug"]})},
        "ranking_setting": {
            "bugs_with_>=2_patches": len(multi),
            "patches_in_those_bugs": sum(len(l) for l in multi.values()),
            "bugs_with_>=2_patches_and_>=1_correct": sum("correct" in l for l in multi.values()),
            "bugs_with_>=2_patches_and_both_labels": sum(len(set(l)) == 2 for l in multi.values()),
        },
    }
    with open(OUT / "dataset_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
