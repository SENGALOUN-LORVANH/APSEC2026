"""Assemble PVS* from already-computed component scores (Step 22). Reads S_sem/S_cex from their results
CSVs (does not re-call the LLM); computes S_edit (LOC fallback) and S_vuln (SpotBugs) directly since those
are local/deterministic.

SMOKE-TEST PLACEHOLDER WEIGHTS: equal weights (0.25 each), NOT calibrated. RQ2's Bradley-Terry calibration
from human preferences is PENDING (protocol.yaml weights_until_human_preferences) -- this only exists so the
PVS* pipeline can be exercised end-to-end before real weights exist. Any PVS number produced with these
weights is an engineering smoke-test value, never a paper result.
"""
import argparse
import csv
import json
from pathlib import Path

import context
import d4j
import edit
import pvs as pvs_module
import vuln
import workspaces

ROOT = Path(__file__).resolve().parents[1]
PATCH_SCORES_CSV = ROOT / "results" / "patch_scores.csv"
SEMANTIC_RESULTS = ROOT / "results" / "semantic_results.csv"
COUNTEREXAMPLE_RESULTS = ROOT / "results" / "counterexample_results.csv"

PLACEHOLDER_WEIGHTS = {"alpha": 0.25, "beta": 0.25, "gamma": 0.25, "delta": 0.25}


def _read_csv_row(path, key_col, key_val):
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row[key_col] == key_val:
                return row
    return None


def _float_or_none(v):
    if v is None or v == "" or v == "None":
        return None
    return float(v)


def compute_s_edit(bug_id, diff_path):
    with open(diff_path, encoding="utf-8", errors="replace", newline="") as f:
        diff_text = f.read().replace("\r\n", "\n")
    with open(d4j.D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
        d4j_row = next(r for r in csv.DictReader(f) if r["bug_id"] == bug_id)
    buggy_dir = workspaces.buggy_dir(bug_id)
    items, errors = context.extract(buggy_dir, d4j_row["dir_src_classes"], diff_text)
    method_loc = sum(edit.method_exec_loc(it.text) for it in items if it.kind == "changed_method")
    changed_loc = edit.changed_exec_loc(diff_text)
    return method_loc, changed_loc, errors


def assemble(patch_id, bug_id):
    import scores

    semantic_row = _read_csv_row(SEMANTIC_RESULTS, "patch_id", patch_id)
    s_sem = _float_or_none(semantic_row["s_sem_final"]) if semantic_row else None

    cex_row = _read_csv_row(COUNTEREXAMPLE_RESULTS, "patch_id", patch_id)
    s_cex = _float_or_none(cex_row["s_cex"]) if cex_row else None

    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        manifest_row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    diff_path = ROOT / manifest_row["normalized_patch_location"]

    method_loc, changed_loc, ctx_errors = compute_s_edit(bug_id, diff_path)
    s_edit_val, s_edit_method = scores.s_edit(changed_exec_loc=changed_loc, method_exec_loc=method_loc)

    buggy_dir = workspaces.buggy_dir(bug_id)
    candidate_dir = workspaces.candidate_dir(patch_id)
    vuln_result = vuln.compute_s_vuln(buggy_dir, candidate_dir)

    components = {"S_sem": s_sem, "S_cex": s_cex, "S_edit": s_edit_val, "S_vuln": vuln_result["s_vuln"]}
    row = pvs_module.score_row(patch_id, components, PLACEHOLDER_WEIGHTS, "shifted_renormalized")
    row["ground_truth_label"] = manifest_row["ground_truth_label"]
    row["S_edit_method"] = s_edit_method
    row["context_errors"] = ";".join(ctx_errors)
    row["S_vuln_new_warning_count"] = len(vuln_result.get("new_warnings", []))
    return row


def _write_row(row):
    PATCH_SCORES_CSV.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if PATCH_SCORES_CSV.exists():
        with open(PATCH_SCORES_CSV, newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["patch_id"] != row["patch_id"]]
    existing.append(row)
    with open(PATCH_SCORES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerows(existing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True)
    ap.add_argument("--bug", required=True)
    args = ap.parse_args()
    row = assemble(args.patch, args.bug)
    _write_row(row)
    print(json.dumps(row, indent=2, default=str))


if __name__ == "__main__":
    main()
