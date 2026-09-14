"""Dataset reconstruction for v2: download + verify archive, parse, apply label policies, normalize, detect
duplicates, write the canonical manifest and audit files.

Usage:
  python src/dataset.py --download      # fetch Patches.zip from Zenodo into data/raw/ and verify checksum
  python src/dataset.py                 # build manifest from data/raw/

Outputs:
  data/dataset_manifest.csv, data/normalized_patches/<patch_id>.diff, data/DATASET_PROVENANCE.md
  results/exclusions.csv, results/corrected_labels.csv, results/duplicates.csv,
  results/normalization_audit.csv, results/dataset_stats.json, results/policy_identifier_matches.csv
"""
import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"

ZENODO_RECORD = "3730599"
ARCHIVE = "Patches.zip"
ARCHIVE_URL = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/{ARCHIVE}/content"
ARCHIVE_MD5 = "11203b88e6ae8a657757c6b5842d5a46"  # published on the Zenodo record

LABEL_OF_FOLDER = {"Dsame": "correct", "Ddifferent": "correct", "Dcorrect": "correct",
                   "Doverfitting": "overfitting"}
# "plusible" is a typo in 9 Arja filenames of the source archive.
NAME_RE = re.compile(r"^patch(\d+)-([A-Za-z]+)-(\d+)-([A-Za-z0-9_]+?)(-pl(?:a)?usible)?\.patch$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


# ------------------------------------------------------------------ archive
def file_hash(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / ARCHIVE
    if not dest.exists():
        urllib.request.urlretrieve(ARCHIVE_URL, dest)
    md5 = file_hash(dest, "md5")
    if md5 != ARCHIVE_MD5:
        sys.exit(f"Checksum mismatch for {dest}: {md5} != {ARCHIVE_MD5}")
    with zipfile.ZipFile(dest) as z:
        z.extractall(RAW)
    print(f"verified {dest} md5={md5}")


# ------------------------------------------------------------------ diff utilities
def changed_line_count(text):
    return sum(1 for l in text.splitlines() if l[:1] in ("+", "-") and not l.startswith(("+++ ", "--- ")))


def normalize_trailing_whitespace(text):
    """Rebuild hunks ignoring trailing whitespace; None if that does not reduce changed lines."""
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
    return rebuilt if changed_line_count(rebuilt) < changed_line_count(text) else None


def _hunks(diff):
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


def verify_normalization(original, rebuilt):
    """Apply rebuilt hunks to each original hunk's old side; must equal its new side (rstrip)."""
    rebuilt_hunks = _hunks(rebuilt)
    for path, start, body in _hunks(original):
        old = [l[1:].rstrip() for l in body if l[:1] in (" ", "-", "")]
        new = [l[1:].rstrip() for l in body if l[:1] in (" ", "+", "")]
        res, ln, end = [], start, start + len(old)
        for _, hs, hb in sorted((h for h in rebuilt_hunks if h[0] == path and start <= h[1] < end),
                                key=lambda h: h[1]):
            while ln < hs:
                res.append(old[ln - start]); ln += 1
            for l in hb:
                kind, txt = l[:1], l[1:].rstrip()
                if kind in (" ", "", "-"):
                    if ln - start >= len(old) or old[ln - start] != txt:
                        return False
                    if kind != "-":
                        res.append(txt)
                    ln += 1
                elif kind == "+":
                    res.append(txt)
        while ln < end:
            res.append(old[ln - start]); ln += 1
        if res != new:
            return False
    return True


# ------------------------------------------------------------------ policies
def parse_identifier(ident):
    parts = ident.split("-")
    if re.fullmatch(r"patch\d+", parts[0]):
        return {"index": int(parts[0][5:]), "bug_id": f"{parts[1]}-{parts[2]}", "tool": parts[3],
                "plausible": parts[-1] == "plausible"}
    return {"index": None, "bug_id": f"{parts[-2]}-{parts[-1]}", "tool": "-".join(parts[:-2]), "plausible": None}


def identifier_matches(ident, rec):
    p = parse_identifier(ident)
    return (rec["APR_tool"] == p["tool"] and rec["bug_id"] == p["bug_id"]
            and (p["index"] is None or rec["patch_index"] == p["index"])
            and (p["plausible"] is None or rec["plausible_suffix"] == p["plausible"]))


def load_policy(name):
    return yaml.safe_load((ROOT / "configs" / f"label_policy_{name}.yaml").read_text())


def apply_policy(rec, policy, match_log):
    """-> (included, label, correction_status, exclusion_reason)"""
    original = rec["original_label"]
    for category, value in (policy.get("exclude") or {}).items():
        if category == "unlabeled_folders":
            if rec["archive_folder"] in value:
                return False, None, "none", f"{category}:{rec['archive_folder']}"
            continue
        for ident in value:
            if identifier_matches(ident, rec):
                match_log[(policy["policy"], category, ident)].append(rec["patch_id"])
                return False, None, "none", f"{category}:{ident}"
    corr = policy.get("corrections")
    if corr:
        for ident in corr["ids"]:
            if identifier_matches(ident, rec):
                match_log[(policy["policy"], "corrections", ident)].append(rec["patch_id"])
                if original == corr["corrected_label"]:
                    sys.exit(f"Correction {ident} matched {rec['patch_id']} already labeled {original}; "
                             "stop and investigate.")
                return True, corr["corrected_label"], f"corrected:{original}->{corr['corrected_label']}", ""
    if original is None:
        return False, None, "none", "no_label"
    return True, original, "none", ""


# ------------------------------------------------------------------ build
def build():
    src = RAW / "Patches"
    if not src.exists():
        sys.exit("data/raw/Patches missing; run with --download first")
    known_ids = {"primary": load_policy("primary"), "sensitivity": load_policy("sensitivity")}
    trig_file = ROOT / "data" / "trigger_tests.json"
    trig_bugs = set(json.loads(trig_file.read_text())["bugs"]) if trig_file.exists() else None

    records, unparsable = [], []
    for path in sorted(src.rglob("*.patch")):
        rel = path.relative_to(src)
        if path.name.startswith("._") or "__MACOSX" in rel.parts:
            continue
        m = NAME_RE.match(path.name)
        if not m:
            unparsable.append(str(rel))
            continue
        idx, project, bug, tool_in_name, plaus = m.groups()
        folder = rel.parts[1]
        tool = rel.parts[2] if len(rel.parts) >= 5 else tool_in_name
        raw = path.read_text(encoding="utf-8", errors="replace")
        records.append({
            "patch_id": str(rel.with_suffix("")).replace("/", "__"), "bug_id": f"{project}-{bug}",
            "project": project, "bug_number": int(bug), "APR_tool": tool, "patch_index": int(idx),
            "plausible_suffix": bool(plaus), "archive_source": rel.parts[0], "archive_folder": folder,
            "original_label": LABEL_OF_FOLDER.get(folder), "original_dataset_location": f"{ARCHIVE}:Patches/{rel}",
            "raw": raw,
        })
    if unparsable:
        sys.exit(f"Unparsable patch filenames: {unparsable[:5]}")

    match_log = defaultdict(list)
    norm_dir = ROOT / "data" / "normalized_patches"
    norm_dir.mkdir(parents=True, exist_ok=True)
    audit = []
    for r in records:
        rebuilt = normalize_trailing_whitespace(r["raw"])
        r["normalized"] = rebuilt if rebuilt is not None else r["raw"]
        ok = verify_normalization(r["raw"], rebuilt) if rebuilt is not None else True
        audit.append({"patch_id": r["patch_id"], "raw_changed_lines": changed_line_count(r["raw"]),
                      "normalized_changed_lines": changed_line_count(r["normalized"]),
                      "normalization_applied": rebuilt is not None,
                      "verification_status": "PASS" if ok else "FAIL"})
        if not ok:
            sys.exit(f"Normalization verification failed for {r['patch_id']}")
        (norm_dir / f"{r['patch_id']}.diff").write_text(r["normalized"])
        r["normalized_patch_location"] = f"data/normalized_patches/{r['patch_id']}.diff"
        for name, pol in known_ids.items():
            inc, lab, corr, reason = apply_policy(r, pol, match_log)
            r[f"included_{name}"], r[f"label_{name}"] = inc, lab
            r[f"correction_status_{name}"], r[f"exclusion_reason_{name}"] = corr, reason
        r["trigger_tests_available"] = (r["bug_id"] in trig_bugs) if trig_bugs is not None else "NA"

    # Duplicates: byte-identical normalized diffs within the same bug.
    groups = defaultdict(list)
    for r in records:
        groups[(r["bug_id"], hashlib.sha256(r["normalized"].encode()).hexdigest())].append(r)
    dup_rows, gid = [], 0
    for (bug, _), members in sorted(groups.items()):
        if len(members) < 2:
            for r in members:
                r["duplicate_group_id"] = ""
            continue
        gid += 1
        group_id = f"DUP{gid:04d}"
        for r in members:
            r["duplicate_group_id"] = group_id
        for name in ("primary", "sensitivity"):
            labels = {r[f"label_{name}"] for r in members if r[f"included_{name}"]}
            if len(labels) > 1:
                sys.exit(f"Duplicate group {group_id} ({bug}) has conflicting {name} labels "
                         f"{[(r['patch_id'], r[f'label_{name}']) for r in members]}; stop and investigate.")
        dup_rows.append({"duplicate_group_id": group_id, "bug_id": bug,
                         "member_patch_ids": ";".join(r["patch_id"] for r in members),
                         "number_of_duplicates": len(members),
                         "labels_consistent": True})

    RESULTS.mkdir(parents=True, exist_ok=True)
    manifest_cols = ["patch_id", "bug_id", "project", "bug_number", "ground_truth_label", "original_label",
                     "original_dataset_location", "normalized_patch_location", "duplicate_group_id", "APR_tool",
                     "included_primary", "included_sensitivity", "correction_status", "exclusion_reason",
                     "label_sensitivity", "exclusion_reason_sensitivity", "trigger_tests_available",
                     "buggy_checkout_available", "fixed_checkout_available", "patch_applies", "patch_compiles",
                     "original_tests_pass"]
    with open(ROOT / "data" / "dataset_manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=manifest_cols)
        w.writeheader()
        for r in records:
            w.writerow({**{k: r.get(k) for k in manifest_cols},
                        "ground_truth_label": r["label_primary"] or "",
                        "correction_status": r["correction_status_primary"],
                        "exclusion_reason": r["exclusion_reason_primary"],
                        "label_sensitivity": r["label_sensitivity"] or "",
                        # Filled on the authoritative PC by the Defects4J stage.
                        "buggy_checkout_available": "NA", "fixed_checkout_available": "NA",
                        "patch_applies": "NA", "patch_compiles": "NA", "original_tests_pass": "NA"})

    def write_csv(name, rows, cols):
        with open(RESULTS / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    write_csv("normalization_audit.csv", audit, list(audit[0]))
    write_csv("duplicates.csv", dup_rows, ["duplicate_group_id", "bug_id", "member_patch_ids",
                                           "number_of_duplicates", "labels_consistent"])
    excl = [{"patch_id": r["patch_id"], "bug_id": r["bug_id"], "policy": name, "archive_folder": r["archive_folder"],
             "original_label": r["original_label"] or "", "exclusion_reason": r[f"exclusion_reason_{name}"]}
            for name in ("primary", "sensitivity") for r in records if not r[f"included_{name}"]]
    write_csv("exclusions.csv", excl, ["patch_id", "bug_id", "policy", "archive_folder", "original_label",
                                        "exclusion_reason"])
    corr = [{"patch_id": r["patch_id"], "bug_id": r["bug_id"], "archive_folder": r["archive_folder"],
             "original_label": r["original_label"], "corrected_label": r["label_primary"],
             "source": "Zenodo 3730599 author notes: mistakenly labeled"}
            for r in records if r["correction_status_primary"].startswith("corrected")]
    write_csv("corrected_labels.csv", corr, ["patch_id", "bug_id", "archive_folder", "original_label",
                                             "corrected_label", "source"])
    matches = []
    for name, pol in known_ids.items():
        for cat, ids in list((pol.get("exclude") or {}).items()) + \
                [("corrections", (pol.get("corrections") or {}).get("ids", []))]:
            if cat == "unlabeled_folders":
                continue
            for ident in ids:
                hit = match_log.get((name, cat, ident), [])
                matches.append({"policy": name, "category": cat, "identifier": ident,
                                "files_matched": len(hit), "patch_ids": ";".join(hit)})
    write_csv("policy_identifier_matches.csv", matches, ["policy", "category", "identifier", "files_matched",
                                                         "patch_ids"])

    def counts(rows, label_key):
        c = Counter(r[label_key] for r in rows)
        n = len(rows)
        return {"patches": n, "correct": c["correct"], "overfitting": c["overfitting"],
                "overfitting_rate": round(c["overfitting"] / n, 4) if n else None,
                "bugs": len({r["bug_id"] for r in rows})}

    stats = {"archive_files_parsed": len(records)}
    for name in ("primary", "sensitivity"):
        inc = [r for r in records if r[f"included_{name}"]]
        stats[name] = {"overall": counts(inc, f"label_{name}"),
                       "per_project": {p: counts([r for r in inc if r["project"] == p], f"label_{name}")
                                       for p in sorted({r["project"] for r in inc})},
                       "excluded": len(records) - len(inc),
                       "bugs_with_>=2": sum(1 for b, n in Counter(r["bug_id"] for r in inc).items() if n >= 2)}
        collapsed = {(r["bug_id"], r["duplicate_group_id"] or r["patch_id"]) for r in inc}
        stats[name]["after_duplicate_collapse"] = len(collapsed)
    stats["duplicate_groups"] = len(dup_rows)
    stats["normalized_patches"] = sum(a["normalization_applied"] for a in audit)
    stats["corrected_labels_primary"] = len(corr)
    (RESULTS / "dataset_stats.json").write_text(json.dumps(stats, indent=2))

    archive = RAW / ARCHIVE
    manifest = ROOT / "data" / "dataset_manifest.csv"
    prov = f"""# Dataset Provenance

Generated by `src/dataset.py` on {datetime.now(timezone.utc).isoformat()}.

## Source
- Wang, S., Wen, M., Lin, B., Wu, H., Qin, Y., Zou, D., Mao, X., Jin, H. "Automated Patch Correctness Assessment:
  How Far are We?" ASE 2020.
- Zenodo record {ZENODO_RECORD}: https://zenodo.org/records/{ZENODO_RECORD}
- Archive: `{ARCHIVE}` from `{ARCHIVE_URL}`
- MD5 (published on Zenodo, verified): `{ARCHIVE_MD5}`
- SHA-256 (computed): `{file_hash(archive, 'sha256') if archive.exists() else 'NA'}`

## Extraction
1. `python src/dataset.py --download` downloads the archive, verifies the MD5, extracts to `data/raw/`.
2. `python src/dataset.py` parses every `*.patch` under `Patches/` (macOS `__MACOSX` / `._*` entries skipped).
3. Labels from archive folders: `Dsame`, `Ddifferent`, `Dcorrect` → correct; `Doverfitting` → overfitting;
   `Error` → unlabeled. (The dataset authors state `Dsame`/`Ddifferent` are all correct.)
4. Label policies: `configs/label_policy_primary.yaml`, `configs/label_policy_sensitivity.yaml`
   (identifiers verbatim from the Zenodo record description). Per-identifier matches:
   `results/policy_identifier_matches.csv`.
5. Trailing-whitespace normalization with per-patch verification: `results/normalization_audit.csv`.
6. Duplicates: byte-identical normalized diffs within a bug: `results/duplicates.csv`.

## Counts
- Patch files parsed: {len(records)}
- Primary policy: {json.dumps(stats['primary']['overall'])}
- Sensitivity policy: {json.dumps(stats['sensitivity']['overall'])}
- Normalized patches: {stats['normalized_patches']}; duplicate groups: {stats['duplicate_groups']};
  corrected labels (primary): {stats['corrected_labels_primary']}
- Manifest SHA-256: `{file_hash(manifest, 'sha256')}`

## Fields that must never reach an LLM prompt
`ground_truth_label`, `original_label`, `label_sensitivity`, `APR_tool`, `original_dataset_location`, `patch_id`,
archive folder names, `-plausible`/`-plusible` suffixes.
"""
    (ROOT / "data" / "DATASET_PROVENANCE.md").write_text(prov)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    a = ap.parse_args()
    download() if a.download else build()
