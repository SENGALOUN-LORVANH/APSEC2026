"""Single-threaded consolidation of the parallel full run (run_full.py --consolidate).

Reads every results/full_run/checkpoints/<patch>.json and writes the corpus-level tables the final evaluation
consumes. Kept strictly separate from the parallel run so no shared CSV is ever written concurrently. Emits:

  results/full_run/full_scores.csv          one row per patch: all component scores + ground truth in one place
  results/full_run/semantic_results.csv      (schema-compatible with the pilot's)
  results/full_run/counterexample_results.csv
  results/full_run/memorization_probe.csv
  results/full_run/stage2b_features.csv
  results/full_run/patch_scores.csv          PVS* (ranking-only placeholder weights, S_sem-guarded per pvs.py)
  results/full_run/run_manifest.csv          per-patch completion + per-stage seconds

Only measured values are written; a missing/failed analyzer stays blank (never 0), matching the analyzer_failure
policy. PVS* uses placeholder equal weights and is ranking-only until RQ2 human preferences exist.
"""
import csv
import json
from pathlib import Path

import pvs as pvs_module
import stage2b

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
FULL_DIR = ROOT / "results" / "full_run"
CKPT_DIR = FULL_DIR / "checkpoints"
PLACEHOLDER_WEIGHTS = {"alpha": 0.25, "beta": 0.25, "gamma": 0.25, "delta": 0.25}


def _load_manifest():
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return {r["patch_id"]: r for r in csv.DictReader(f)}


def _write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def consolidate():
    manifest = _load_manifest()
    ckpts = sorted(CKPT_DIR.glob("*.json"))
    full_rows, sem_rows, cex_rows, probe_rows, s2b_rows, pvs_rows, run_rows = [], [], [], [], [], [], []

    for cp in ckpts:
        try:
            d = json.loads(cp.read_text())
        except Exception as e:  # noqa: BLE001
            run_rows.append({"patch_id": cp.stem, "complete": False, "error": f"unreadable checkpoint: {e}"})
            continue
        pid = d["patch_id"]
        m = manifest.get(pid, {})
        sem = d.get("semantic") or {}
        cex = d.get("counterexample") or {}
        probe = d.get("memorization") or {}
        s2b = d.get("stage2b") or {}

        s_sem = sem.get("s_sem_final")
        s_cex = cex.get("s_cex")
        s_edit = s2b.get("s_edit_ast")          # GumTree AST = primary S_edit
        s_vuln = s2b.get("s_vuln_changed")

        full_rows.append({
            "patch_id": pid, "bug_id": d.get("bug_id"), "project": m.get("project"),
            "ground_truth_label": m.get("ground_truth_label"),
            "included_primary": m.get("included_primary"), "duplicate_group_id": m.get("duplicate_group_id"),
            "s_sem_final": s_sem, "semantic_decision": sem.get("decision"),
            "n_parsed": sem.get("n_parsed"), "n_runs": sem.get("n_runs"),
            "s_cex": s_cex, "cex_n_valid": cex.get("n_valid"), "cex_n_passed": cex.get("n_passed"),
            "s_edit_ast": s_edit, "s_vuln_changed": s_vuln, "analysis_level": s2b.get("analysis_level"),
            "d_cyclomatic": s2b.get("d_cyclomatic"), "d_stmts": s2b.get("d_stmts"),
            "d_branch_points": s2b.get("d_branch_points"), "d_cfg_edges": s2b.get("d_cfg_edges"),
            "d_defuse_pairs": s2b.get("d_defuse_pairs"),
            "memorization_recognized": probe.get("recognized"),
            "complete": d.get("complete"), "terminal_failure": d.get("terminal_failure"),
        })

        if sem:
            sem_rows.append({"patch_id": pid, "condition": sem.get("condition"), "model": sem.get("model"),
                             "n_runs": sem.get("n_runs"), "n_parsed": sem.get("n_parsed"),
                             "s_sem_final": s_sem, "decision": sem.get("decision")})
        if cex:
            cex_rows.append({"patch_id": pid, "bug_id": d.get("bug_id"), "model": cex.get("model"),
                             "s_cex": s_cex, "n_valid": cex.get("n_valid"), "n_passed": cex.get("n_passed"),
                             "n_generated": len(cex.get("tests", [])), "input_tokens": cex.get("input_tokens"),
                             "output_tokens": cex.get("output_tokens"), "error": cex.get("error")})
        if probe:
            probe_rows.append({k: probe.get(k, "") for k in
                               ["patch_id", "true_project", "true_bug_number", "model", "project",
                                "bug_number", "recalled_label", "recognized", "error"]})
        if s2b:
            s2b_rows.append({k: s2b.get(k) for k in stage2b.CSV_FIELDS})

        components = {"S_sem": s_sem, "S_cex": s_cex, "S_edit": s_edit, "S_vuln": s_vuln}
        row = pvs_module.score_row(pid, components, PLACEHOLDER_WEIGHTS, "shifted_renormalized")
        row["ground_truth_label"] = m.get("ground_truth_label")
        pvs_rows.append(row)

        run = {"patch_id": pid, "bug_id": d.get("bug_id"), "complete": d.get("complete"),
               "terminal_failure": d.get("terminal_failure")}
        for name, st in (d.get("stages") or {}).items():
            run[f"t_{name}"] = st.get("seconds")
            run[f"ok_{name}"] = st.get("ok")
        run_rows.append(run)

    _write_csv(FULL_DIR / "full_scores.csv", full_rows, list(full_rows[0].keys()) if full_rows else ["patch_id"])
    _write_csv(FULL_DIR / "semantic_results.csv", sem_rows,
               ["patch_id", "condition", "model", "n_runs", "n_parsed", "s_sem_final", "decision"])
    _write_csv(FULL_DIR / "counterexample_results.csv", cex_rows,
               ["patch_id", "bug_id", "model", "s_cex", "n_valid", "n_passed", "n_generated",
                "input_tokens", "output_tokens", "error"])
    _write_csv(FULL_DIR / "memorization_probe.csv", probe_rows,
               ["patch_id", "true_project", "true_bug_number", "model", "project", "bug_number",
                "recalled_label", "recognized", "error"])
    _write_csv(FULL_DIR / "stage2b_features.csv", s2b_rows, stage2b.CSV_FIELDS)
    if pvs_rows:
        _write_csv(FULL_DIR / "patch_scores.csv", pvs_rows, list(pvs_rows[0].keys()))
    # run_manifest columns are the union of all stage-timing keys seen
    run_fields = ["patch_id", "bug_id", "complete", "terminal_failure"]
    for r in run_rows:
        for k in r:
            if k not in run_fields:
                run_fields.append(k)
    _write_csv(FULL_DIR / "run_manifest.csv", run_rows, run_fields)

    print(json.dumps({"checkpoints": len(ckpts), "full_scores": len(full_rows),
                      "semantic": len(sem_rows), "counterexample": len(cex_rows),
                      "memorization": len(probe_rows), "stage2b": len(s2b_rows),
                      "pvs": len(pvs_rows)}, indent=2))


if __name__ == "__main__":
    consolidate()
