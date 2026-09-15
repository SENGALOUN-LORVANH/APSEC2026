"""Defects4J v2.0.1 workspace driver: checkout buggy/fixed, compile, apply candidate patches, run trigger tests.

Usage:
  python src/d4j.py --bug Chart-19                 # checkout+compile+trigger-test buggy & fixed_oracle
  python src/d4j.py --patch <patch_id>              # apply one candidate patch onto its bug's buggy checkout
  python src/d4j.py --sample N                      # process N bugs (one per distinct bug_id, in manifest order)
  python src/d4j.py --update-manifest               # write accumulated status back into data/dataset_manifest.csv

Writes one row per bug to results/d4j_status.csv (bug-level: buggy_checkout_available, fixed_checkout_available,
trigger_tests_available) and one row per patch to results/patch_d4j_status.csv (candidate-level: patch_applies,
patch_compiles, original_tests_pass). Only this module and oracle_runner may resolve fixed-oracle paths
(see workspaces.ORACLE_MODULES).
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import leakage_guard
import workspaces

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINTS_DIR = ROOT / "results" / "fingerprints"
D4J_HOME = os.environ.get("D4J_V2_HOME", "/opt/defects4j-2.0.1")
D4J_BIN = f"{D4J_HOME}/framework/bin"
JDK8 = os.environ.get("JDK8", "/usr/lib/jvm/java-8-openjdk-amd64")
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
D4J_STATUS_CSV = ROOT / "results" / "d4j_status.csv"
PATCH_STATUS_CSV = ROOT / "results" / "patch_d4j_status.csv"

# Known source-root prefixes used by the Wang et al. archive's diff headers (PC_HANDOFF.md step 8).
SRC_PREFIXES = ["/source/", "/src/main/java/", "/src/java/"]
FILE_HEADER_RE = re.compile(r"^(---|\+\+\+) (\S+)(.*)$")


def _env():
    e = os.environ.copy()
    e["JAVA_HOME"] = JDK8
    e["PATH"] = f"{JDK8}/bin:{D4J_BIN}:" + e.get("PATH", "")
    return e


def _run(cmd, cwd=None, timeout=1800):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return None, e.stdout or "", f"TIMEOUT after {timeout}s: {e}"


def bug_parts(bug_id):
    project, number = bug_id.rsplit("-", 1)
    return project, number


def checkout(bug_id, suffix, workdir: Path):
    """suffix: 'b' (buggy) or 'f' (fixed)."""
    project, number = bug_parts(bug_id)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = _run(["defects4j", "checkout", "-p", project, "-v", f"{number}{suffix}", "-w", str(workdir)])
    return rc == 0, out + err


def compile_workdir(workdir: Path):
    rc, out, err = _run(["defects4j", "compile", "-w", str(workdir)])
    return rc == 0, out + err


def export(workdir: Path, prop):
    with tempfile.TemporaryDirectory() as td:
        out_file = Path(td) / "export.txt"
        rc, out, err = _run(["defects4j", "export", "-p", prop, "-w", str(workdir), "-o", str(out_file)])
        if rc != 0 or not out_file.exists():
            return None
        return out_file.read_text(encoding="utf-8", errors="replace").strip()


def failing_tests(workdir: Path):
    """Parse workdir/failing_tests (absent or empty => no failures). Never trust the exit code (d4j-test exits 0
    even when developer tests fail; failures are reported only via this file)."""
    f = workdir / "failing_tests"
    if not f.exists():
        return []
    names = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("--- "):
            names.append(line[4:].strip())
    return names


def run_tests(workdir: Path, single_test=None, timeout=1800):
    cmd = ["defects4j", "test", "-w", str(workdir)]
    if single_test:
        cmd += ["-t", single_test]
    _run(cmd, timeout=timeout)
    return failing_tests(workdir)


# ------------------------------------------------------------------ bug-level (Step 7)
def process_bug(bug_id):
    """Checkout buggy -> workspaces/buggy/<P>_<N>, fixed -> workspaces/fixed_oracle/<P>_<N> (read-only afterwards).
    Compile both, export properties, run trigger tests. Returns a status dict; never raises on tool failure."""
    buggy_dir = workspaces.buggy_dir(bug_id)
    fixed_dir = workspaces.fixed_oracle_dir(bug_id)  # allowed: this module is in ORACLE_MODULES

    status = {"bug_id": bug_id, "buggy_checkout_available": False, "fixed_checkout_available": False,
              "buggy_compiles": False, "fixed_compiles": False, "trigger_tests_available": False,
              "trigger_tests": "", "buggy_trigger_failures": 0, "fixed_trigger_failures": 0,
              "dir_src_classes": "", "error": ""}

    ok, log = checkout(bug_id, "b", buggy_dir)
    status["buggy_checkout_available"] = ok
    if not ok:
        status["error"] = f"buggy checkout failed: {log[-500:]}"
        return status

    ok, log = compile_workdir(buggy_dir)
    status["buggy_compiles"] = ok
    if not ok:
        status["error"] = f"buggy compile failed: {log[-500:]}"
        return status

    trigger = export(buggy_dir, "tests.trigger")
    status["dir_src_classes"] = export(buggy_dir, "dir.src.classes") or ""
    if trigger:
        status["trigger_tests_available"] = True
        status["trigger_tests"] = trigger.replace("\n", ";")

    status["buggy_trigger_failures"] = len(run_tests(buggy_dir))

    ok, log = checkout(bug_id, "f", fixed_dir)
    status["fixed_checkout_available"] = ok
    if ok:
        ok, log = compile_workdir(fixed_dir)
        status["fixed_compiles"] = ok
        if ok:
            status["fixed_trigger_failures"] = len(run_tests(fixed_dir))
    if not ok:
        status["error"] = (status["error"] + f"; fixed stage failed: {log[-500:]}").strip("; ")
    return status


# ------------------------------------------------------------------ patch-level (Step 8)
def _strip_src_prefix(path):
    for pref in SRC_PREFIXES:
        if path.startswith(pref):
            return path[len(pref):]
    return None


def _touched_relpaths(diff_text):
    """Relative (post-prefix-strip) paths of files the diff writes to (+++ side)."""
    paths = set()
    for line in diff_text.splitlines():
        m = FILE_HEADER_RE.match(line)
        if m and m.group(1) == "+++":
            rel = _strip_src_prefix(m.group(2))
            if rel:
                paths.add(rel)
    return paths


def rewrite_diff_for_target(diff_text, src_root):
    """Rewrite --- / +++ header paths (archive-relative, e.g. /source/org/...) to paths relative to the checkout
    root (e.g. source/org/...), joining the real dir.src.classes value, so `patch -p0` run with cwd=<checkout root>
    applies unambiguously. Deliberately relative: GNU patch refuses absolute paths as "potentially dangerous
    file name". Returns (text, ok)."""
    src_root = Path(src_root)
    out = []
    ok = True
    for line in diff_text.splitlines(keepends=True):
        m = FILE_HEADER_RE.match(line)
        if m:
            marker, path, rest = m.group(1), m.group(2), m.group(3)
            rel = _strip_src_prefix(path)
            if rel is None:
                ok = False
                out.append(line)
                continue
            out.append(f"{marker} {src_root / rel}{rest}\n")
        else:
            out.append(line)
    return "".join(out), ok


def apply_candidate(patch_id, bug_id, diff_path: Path, trigger_tests):
    """Copy the bug's buggy checkout to workspaces/candidate/<patch_id>, apply the candidate diff, compile,
    and check whether the bug's own trigger tests now pass. Returns a status dict."""
    buggy_dir = workspaces.buggy_dir(bug_id)
    candidate_dir = workspaces.candidate_dir(patch_id)
    result = {"patch_id": patch_id, "bug_id": bug_id, "patch_applies": False,
              "patch_compiles": "NA", "original_tests_pass": "NA", "error": ""}

    if not buggy_dir.exists():
        result["error"] = "buggy checkout missing; run process_bug first"
        return result

    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    shutil.copytree(buggy_dir, candidate_dir, symlinks=True)

    src_classes_rel = export(candidate_dir, "dir.src.classes")
    if not src_classes_rel:
        result["error"] = "export dir.src.classes failed on candidate copy"
        return result

    # newline='' preserves the file's original line endings byte-for-byte on read; we then normalize CRLF -> LF
    # on both the diff and the touched checkout files, because the archive's diffs and the old jfreechart/commons
    # sources mix CRLF/LF inconsistently (even within one diff), which `patch` rejects as "different line endings"
    # even though the content matches. Line endings are not semantic content: this is not context-fuzz.
    with open(diff_path, encoding="utf-8", errors="replace", newline="") as f:
        diff_text = f.read().replace("\r\n", "\n")
    for rel in _touched_relpaths(diff_text):
        target_file = candidate_dir / src_classes_rel / rel
        if target_file.exists():
            raw = target_file.read_bytes()
            if b"\r\n" in raw:
                target_file.write_bytes(raw.replace(b"\r\n", b"\n"))
    rewritten, ok = rewrite_diff_for_target(diff_text, src_classes_rel)
    if not ok:
        result["error"] = "diff header path did not match any known source-root prefix"
        return result

    with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False, encoding="utf-8", newline="") as tmp:
        tmp.write(rewritten)
        tmp_path = tmp.name
    # --ignore-whitespace: the archive's context lines and the real Defects4J checkout disagree on incidental
    # whitespace (e.g. trailing spaces on otherwise-blank lines) even when the content is identical; observed
    # directly on Chart-19/patch1-ACS. This is distinct from --fuzz (context-radius tolerance), which stays at 0
    # per protocol ("no fuzz"): whitespace-insensitive matching, not approximate line-number/context matching.
    try:
        dry = subprocess.run(["patch", "-p0", "--fuzz=0", "--ignore-whitespace", "--dry-run", "-i", tmp_path],
                              cwd=str(candidate_dir), capture_output=True, text=True)
        result["patch_applies"] = dry.returncode == 0
        if not result["patch_applies"]:
            result["error"] = f"dry-run failed: {(dry.stdout + dry.stderr)[-500:]}"
        else:
            real = subprocess.run(["patch", "-p0", "--fuzz=0", "--ignore-whitespace", "-i", tmp_path],
                                   cwd=str(candidate_dir), capture_output=True, text=True)
            if real.returncode != 0:
                result["patch_applies"] = False
                result["error"] = f"dry-run passed but real apply failed: {real.stderr[-500:]}"
    finally:
        os.unlink(tmp_path)

    if not result["patch_applies"]:
        return result

    ok, log = compile_workdir(candidate_dir)
    result["patch_compiles"] = ok
    if not ok:
        result["error"] = f"candidate compile failed: {log[-500:]}"
        return result

    still_failing = set(run_tests(candidate_dir)) & set(trigger_tests)
    result["original_tests_pass"] = len(still_failing) == 0
    return result


# ------------------------------------------------------------------ leakage-guard fingerprint (oracle-side only)
def compute_fingerprint(patch_id, bug_id, diff_path: Path):
    """Hashes of developer-fix-only lines (leakage_guard.developer_fix_fingerprint), written to
    results/fingerprints/<patch_id>.json. Only this module (an ORACLE_MODULE) may read fixed_oracle/ content;
    semantic.py/counterexamples.py load the precomputed hash file and never touch the fixed source themselves."""
    buggy_dir = workspaces.buggy_dir(bug_id)
    fixed_dir = workspaces.fixed_oracle_dir(bug_id)
    src_classes_rel = export(buggy_dir, "dir.src.classes")
    if not src_classes_rel:
        return {"patch_id": patch_id, "error": "export dir.src.classes failed", "hashes": []}

    with open(diff_path, encoding="utf-8", errors="replace", newline="") as f:
        diff_text = f.read().replace("\r\n", "\n")

    hashes = set()
    errors = []
    for rel in _touched_relpaths(diff_text):
        buggy_file = buggy_dir / src_classes_rel / rel
        fixed_file = fixed_dir / src_classes_rel / rel
        if not buggy_file.exists() or not fixed_file.exists():
            errors.append(f"missing source for {rel}")
            continue
        buggy_source = buggy_file.read_text(encoding="utf-8", errors="replace")
        fixed_source = fixed_file.read_text(encoding="utf-8", errors="replace")
        hashes |= leakage_guard.developer_fix_fingerprint(buggy_source, fixed_source, diff_text)

    FINGERPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {"patch_id": patch_id, "bug_id": bug_id, "error": "; ".join(errors), "hashes": sorted(hashes)}
    (FINGERPRINTS_DIR / f"{patch_id}.json").write_text(json.dumps(out, indent=2))
    return out


def load_fingerprint(patch_id):
    f = FINGERPRINTS_DIR / f"{patch_id}.json"
    if not f.exists():
        return frozenset()
    return frozenset(json.loads(f.read_text()).get("hashes", []))


# ------------------------------------------------------------------ CSV I/O + CLI
def _write_status_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row[fieldnames[0]]] = row
    for row in rows:
        existing[row[fieldnames[0]]] = {k: row.get(k, "") for k in fieldnames}
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for key in sorted(existing):
            w.writerow(existing[key])


BUG_FIELDS = ["bug_id", "buggy_checkout_available", "fixed_checkout_available", "buggy_compiles", "fixed_compiles",
              "trigger_tests_available", "trigger_tests", "buggy_trigger_failures", "fixed_trigger_failures",
              "dir_src_classes", "error"]
PATCH_FIELDS = ["patch_id", "bug_id", "patch_applies", "patch_compiles", "original_tests_pass", "error"]


def load_manifest_rows():
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def trigger_tests_for(bug_id):
    if D4J_STATUS_CSV.exists():
        with open(D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["bug_id"] == bug_id and row["trigger_tests"]:
                    return row["trigger_tests"].split(";")
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bug")
    ap.add_argument("--patch")
    ap.add_argument("--fingerprint")
    ap.add_argument("--sample", type=int)
    args = ap.parse_args()

    if args.bug:
        status = process_bug(args.bug)
        _write_status_csv(D4J_STATUS_CSV, [status], BUG_FIELDS)
        print(status)
    elif args.patch:
        rows = load_manifest_rows()
        row = next(r for r in rows if r["patch_id"] == args.patch)
        trigger = trigger_tests_for(row["bug_id"])
        diff_path = ROOT / row["normalized_patch_location"]
        result = apply_candidate(args.patch, row["bug_id"], diff_path, trigger)
        _write_status_csv(PATCH_STATUS_CSV, [result], PATCH_FIELDS)
        print(result)
    elif args.fingerprint:
        rows = load_manifest_rows()
        row = next(r for r in rows if r["patch_id"] == args.fingerprint)
        diff_path = ROOT / row["normalized_patch_location"]
        result = compute_fingerprint(args.fingerprint, row["bug_id"], diff_path)
        print({"patch_id": result["patch_id"], "n_hashes": len(result["hashes"]), "error": result["error"]})
    elif args.sample:
        rows = load_manifest_rows()
        seen = []
        for r in rows:
            if r["bug_id"] not in seen:
                seen.append(r["bug_id"])
            if len(seen) >= args.sample:
                break
        for bug_id in seen:
            status = process_bug(bug_id)
            _write_status_csv(D4J_STATUS_CSV, [status], BUG_FIELDS)
            print(status["bug_id"], "buggy_ok=", status["buggy_checkout_available"],
                  "fixed_ok=", status["fixed_checkout_available"], "trigger=", status["trigger_tests_available"])
    else:
        ap.error("one of --bug / --patch / --sample is required")


if __name__ == "__main__":
    main()
