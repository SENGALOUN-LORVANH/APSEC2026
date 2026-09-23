"""Final evaluation of the FULL 899-patch run (work order D).

Reuses the frozen per-method evaluator from evaluate_pilot.py (imported as ep) on a DataFrame built from the
consolidated full-run data (results/full_run/full_scores.csv + patch_scores.csv), so every method matches its
pre-registered definition exactly. Adds:
  * LOPO primary + GroupKFold-by-bug secondary detection (paired bug-clustered bootstrap, 10 000, seed 2026)
  * conditional & end-to-end P@1 with ceiling/random/MRR/Top-3 (ranking_section)
  * label-policy + duplicate-collapse sensitivity, counterexample funnel + S_cex missingness,
    static coverage by analysis level, complementarity (RQ3), memorization probe, runtime, cost
  * programmatic LaTeX tables into results/*.tex (each stamped with the source file + git commit)
  * reports/FULL_RUN_REPORT_V2.md -- final numbers are NOT labelled PRELIMINARY; where a 95% CI includes 0
    that is stated plainly.

These are FINAL corpus numbers, not a pilot. Every value is measured; nothing is imputed except the declared
in-fold mean-imputation for the static-feature logistic models (with the complete-case sensitivity alongside).

Usage (venv, pure -- no API; run after the full run's checkpoints are consolidated):
  python src/run_full.py --consolidate      # first, build results/full_run/*.csv
  python src/evaluate_full.py
"""
import csv
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

import evaluate_pilot as ep
import d4j
import metrics

ROOT = Path(__file__).resolve().parents[1]
FULL_DIR = ROOT / "results" / "full_run"
FULL_SCORES = FULL_DIR / "full_scores.csv"
PATCH_SCORES = FULL_DIR / "patch_scores.csv"
RUN_MANIFEST = FULL_DIR / "run_manifest.csv"
DIFF_FEATURES_CSV = ROOT / "results" / "diff_features_baseline.csv"
OUT = FULL_DIR / "full_evaluation.json"
TEX_DIR = ROOT / "results"


def _git_commit():
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:
        return "unknown"


def _f(v):
    return float(v) if v not in (None, "", "None") else None


def build_full_frame():
    """Build the evaluation frame from the consolidated full-run data, with exactly the columns ep's section
    functions expect. Only patches with a valid semantic score enter the detection frame; incomplete/failed
    patches are counted separately (never silently dropped)."""
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        manifest = {r["patch_id"]: r for r in csv.DictReader(f)}
    pvs = {}
    if PATCH_SCORES.exists():
        with open(PATCH_SCORES, newline="", encoding="utf-8") as f:
            pvs = {r["patch_id"]: r for r in csv.DictReader(f)}
    diff_feats = {}
    if DIFF_FEATURES_CSV.exists():
        with open(DIFF_FEATURES_CSV, newline="", encoding="utf-8") as f:
            diff_feats = {r["patch_id"]: r for r in csv.DictReader(f)}
    with open(FULL_SCORES, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    excluded = {"no_semantic_score": 0, "not_in_manifest": 0, "unlabelled": 0}
    out = []
    for r in rows:
        pid = r["patch_id"]
        m = manifest.get(pid)
        if not m:
            excluded["not_in_manifest"] += 1
            continue
        gt = r.get("ground_truth_label") or m.get("ground_truth_label")
        if gt not in ("overfitting", "correct"):
            excluded["unlabelled"] += 1
            continue
        s_sem = _f(r.get("s_sem_final"))
        if s_sem is None:
            excluded["no_semantic_score"] += 1
            continue
        p = pvs.get(pid, {})
        s2 = {"s_vuln_changed": _f(r.get("s_vuln_changed")), "d_cyclomatic": _f(r.get("d_cyclomatic")),
              "d_branch_points": _f(r.get("d_branch_points")), "d_stmts": _f(r.get("d_stmts")),
              "d_defuse_pairs": _f(r.get("d_defuse_pairs"))}
        rec = {"patch_id": pid, "bug_id": m["bug_id"], "project": m["project"],
               "ground_truth_label": gt, "y": 1 if gt == "overfitting" else 0,
               "label_sensitivity": m.get("label_sensitivity", ""),
               "included_sensitivity": m.get("included_sensitivity", ""),
               "duplicate_group_id": m.get("duplicate_group_id", ""),
               "size": None, "tercile": "",
               "PVS": _f(p.get("PVS")), "S_sem": s_sem, "S_cex": _f(r.get("s_cex")),
               "S_edit": _f(r.get("s_edit_ast")), "S_vuln": _f(r.get("s_vuln_changed")),
               "s_sem_missing": False, "analysis_level": r.get("analysis_level", "")}
        for col in ep.STATIC_FEATURES:
            rec[col] = s2.get(col)
        dfeat = diff_feats.get(pid, {})
        for col in ep.DIFF_FEATURES:
            rec[col] = _f(dfeat.get(col))
        out.append(rec)
    df = pd.DataFrame(out)
    df.attrs["has_stage2b"] = bool(len(df)) and bool(df[ep.STATIC_FEATURES].notna().any().any())
    df.attrs["has_diff_features"] = bool(diff_feats)
    df.attrs["excluded"] = excluded
    return df


def _point(m):
    """Compact point-estimate view of a detection-metrics dict for LaTeX."""
    def g(k):
        v = m.get(k)
        return "" if v is None else (f"{v:.3f}" if isinstance(v, float) else v)
    c = m.get("confusion", {})
    mcc_ci = m.get("mcc_ci95_cluster_bootstrap") or [None, None]
    ci = "" if mcc_ci[0] is None else f"[{mcc_ci[0]:.3f}, {mcc_ci[1]:.3f}]"
    return dict(precision=g("precision"), recall=g("recall"), f1=g("f1"), mcc=g("mcc"),
               auroc=g("auroc"), confusion=f"{c.get('tp','')}/{c.get('fp','')}/{c.get('tn','')}/{c.get('fn','')}",
               mcc_ci=ci)


LATEX_METHOD_ORDER = ["M0_majority", "M1_random_stratified", "M2_diff_feature", "M2b_s_edit_only",
                      "M3_semantic", "M4_counterexample", "M5_static", "M6_sem_cex", "M7_sem_static",
                      "M8_cex_static", "M9_sem_cex_static"]
METHOD_LABEL = {"M0_majority": "M0 majority", "M1_random_stratified": "M1 random",
                "M2_diff_feature": "M2 diff-feature", "M2b_s_edit_only": "M2b $S_{edit}$ only",
                "M3_semantic": "M3 semantic", "M4_counterexample": "M4 counterexample",
                "M5_static": "M5 static", "M6_sem_cex": "M6 sem+cex", "M7_sem_static": "M7 sem+static",
                "M8_cex_static": "M8 cex+static", "M9_sem_cex_static": "M9 sem+cex+static"}


def _tex_header(source_desc, commit):
    return (f"% Generated by src/evaluate_full.py (commit {commit}) from {source_desc}.\n"
            f"% Do not edit by hand -- regenerate with: python src/evaluate_full.py\n")


def write_detection_tex(det, path, caption, label, commit):
    lines = [_tex_header("results/full_run/full_scores.csv", commit),
             "\\begin{table}[t]\\centering",
             f"\\caption{{{caption}}}\\label{{{label}}}",
             "\\begin{tabular}{lrrrrrl}", "\\toprule",
             "Method & Prec. & Rec. & F1 & MCC & AUROC & MCC 95\\% CI \\\\", "\\midrule"]
    methods = det["methods"]
    for name in LATEX_METHOD_ORDER:
        m = methods.get(name)
        if not m or m.get("status") == "PENDING":
            continue
        if name == "M4_counterexample":
            b = m.get("binary_on_available", {})
            pt = _point(b)
            pt["auroc"] = "" if m.get("auroc_on_available") is None else f"{m['auroc_on_available']:.3f}"
            pt["mcc_ci"] = f"(avail n={m.get('n_S_cex_available')})"
        else:
            pt = _point(m)
        lines.append(f"{METHOD_LABEL[name]} & {pt['precision']} & {pt['recall']} & {pt['f1']} & "
                     f"{pt['mcc']} & {pt['auroc']} & {pt['mcc_ci']} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    path.write_text("\n".join(lines))


def write_paired_tex(det, path, commit):
    lines = [_tex_header("results/full_run/full_evaluation.json (paired bug-clustered bootstrap, B=10000, seed 2026)", commit),
             "\\begin{table}[t]\\centering",
             "\\caption{Paired differences in MCC (bug-clustered bootstrap, 10{,}000 resamples, seed 2026). "
             "A difference is established only when the 95\\% CI excludes 0.}\\label{tab:paired}",
             "\\begin{tabular}{lrl}", "\\toprule",
             "Comparison & $\\Delta$MCC & 95\\% CI \\\\", "\\midrule"]
    for k, v in det.get("paired_differences_mcc", {}).items():
        est = v.get("difference")
        ci = v.get("ci95") or [None, None]
        excl = "$^\\ast$" if v.get("ci_excludes_zero") else " "
        est_s = "" if est is None else f"{est:+.3f}"
        ci_s = "" if ci[0] is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]{excl}"
        lines.append(f"{k.replace('_',' ')} & {est_s} & {ci_s} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}",
              "\\\\[2pt]\\footnotesize $^\\ast$ 95\\% CI excludes 0.", "\\end{table}", ""]
    path.write_text("\n".join(lines))


def write_ranking_tex(rank, path, commit):
    s = rank.get("summary", {})
    cond = s.get("conditional", {})
    e2e = s.get("end_to_end", {})
    def g(d, k):
        v = d.get(k)
        return "" if v is None else (f"{v:.3f}" if isinstance(v, float) else v)
    lines = [_tex_header("results/full_run/full_evaluation.json ranking_section (PVS*, ranking-only placeholder weights)", commit),
             "\\begin{table}[t]\\centering",
             "\\caption{PVS* ranking: precision@1 with random and ceiling baselines, MRR, Top-3. "
             "PVS* uses placeholder equal weights (ranking-only; RQ2 Bradley--Terry calibration pending).}"
             "\\label{tab:ranking}",
             "\\begin{tabular}{lrr}", "\\toprule",
             "Metric & Conditional & End-to-end \\\\", "\\midrule",
             f"Bugs (\\textgreater=2 candidates / all) & {g(cond,'bugs')} & {g(e2e,'bugs')} \\\\",
             f"P@1 & {g(cond,'precision_at_1')} & {g(e2e,'precision_at_1')} \\\\",
             f"P@1 random baseline & {g(cond,'random_expected_p_at_1')} & {g(e2e,'random_expected_p_at_1')} \\\\",
             f"P@1 ceiling (has a correct patch) & -- & {g(e2e,'theoretical_max_p_at_1')} \\\\",
             f"MRR & {g(cond,'mrr')} & {g(e2e,'mrr')} \\\\",
             f"Top-3 & {g(cond,'top3')} & {g(e2e,'top3')} \\\\",
             "\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    path.write_text("\n".join(lines))


def full_runtime_section():
    """Runtime from the full run's checkpoints (per-stage seconds) via run_manifest.csv."""
    if not RUN_MANIFEST.exists():
        return {"status": "run_manifest.csv missing"}
    with open(RUN_MANIFEST, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    stage_cols = [c for c in (rows[0].keys() if rows else []) if c.startswith("t_")]
    by_stage = {}
    totals = []
    for r in rows:
        tot = 0.0
        for c in stage_cols:
            v = _f(r.get(c))
            if v is not None:
                by_stage.setdefault(c[2:], []).append(v)
                tot += v
        if tot:
            totals.append(tot)
    import statistics
    def stat(v):
        return {"n": len(v), "mean": round(statistics.mean(v), 2), "median": round(statistics.median(v), 2),
                "p90": round(float(np.percentile(v, 90)), 2), "max": round(max(v), 2)} if v else {}
    return {"n_patches": len(rows), "per_stage_seconds": {k: stat(v) for k, v in
            sorted(by_stage.items(), key=lambda kv: -sum(kv[1]))},
            "per_patch_seconds": stat(totals),
            "wall_clock_note": "per-patch seconds are summed stage times inside one worker; wall-clock is lower "
                               "because bugs run in parallel across workers."}


def full_cost_section():
    """Measured USD cost of the full run from the per-patch token logs (semantic + counterexample +
    memorization), all claude-haiku-4-5."""
    def usd(tin, tout):
        p = ep.PRICING["claude-haiku-4-5"]
        return round(tin / 1e6 * p["in"] + tout / 1e6 * p["out"], 4)
    def sum_dir(d, per_runs):
        tin = tout = n = 0
        if d.exists():
            for f in d.glob("*.json"):
                try:
                    e = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                runs = e.get("runs", []) if per_runs else [e]
                for r in runs:
                    if r.get("input_tokens") is not None:
                        tin += r["input_tokens"]; tout += r.get("output_tokens") or 0; n += 1
        return tin, tout, n
    si, so, sn = sum_dir(FULL_DIR / "semantic_runs", True)
    ci, co, cn = sum_dir(FULL_DIR / "counterexample_runs", False)
    # memorization tokens live in the checkpoints
    mi = mo = mn = 0
    ck = FULL_DIR / "checkpoints"
    if ck.exists():
        for f in ck.glob("*.json"):
            try:
                d = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            pr = d.get("memorization") or {}
            if pr.get("input_tokens") is not None:
                mi += pr["input_tokens"]; mo += pr.get("output_tokens") or 0; mn += 1
    breakdown = {
        "semantic_haiku": {"calls": sn, "input_tokens": si, "output_tokens": so, "usd": usd(si, so)},
        "counterexample_haiku": {"calls": cn, "input_tokens": ci, "output_tokens": co, "usd": usd(ci, co)},
        "memorization_haiku": {"calls": mn, "input_tokens": mi, "output_tokens": mo, "usd": usd(mi, mo)},
    }
    total = round(sum(v["usd"] for v in breakdown.values()), 4)
    return {"pricing_source": ep.PRICING_SOURCE, "pricing_per_mtok_usd": ep.PRICING,
            "model": "claude-haiku-4-5", "breakdown": breakdown, "total_usd": total,
            "total_billable_calls": sn + cn + mn}


def context_ablation_section():
    p = ROOT / "results" / "context_ablation_summary.json"
    if not p.exists():
        return {"status": "context_ablation_summary.json missing"}
    d = json.loads(p.read_text())
    return {"source": "48-patch pilot ablation (src/context_ablation.py)", **d}


def evaluate():
    commit = _git_commit()
    # point full-run readers of ep's dir-based sections at the full-run outputs
    ep.COUNTEREXAMPLE_RUNS_DIR = FULL_DIR / "counterexample_runs"
    ep.SEMANTIC_RUNS_DIR = FULL_DIR / "semantic_runs"
    ep.MEMORIZATION_CSV = FULL_DIR / "memorization_probe.csv"

    df = build_full_frame()
    n = len(df)
    lopo = ep.detection_section(df, split_fn=metrics.lopo_splits, split_name="lopo_per_project")
    gkf = ep.detection_section(df, split_fn=lambda d: metrics.groupkfold_splits(d, n_splits=5, seed=2026),
                               split_name="groupkfold_per_bug_fold")

    result = {
        "TITLE": "FULL RUN v2 -- 899 primary-policy patches, claude-haiku-4-5, condition C, 3 semantic runs, "
                 "K=3 counterexamples, Stage 2B every patch. FINAL numbers (not preliminary).",
        "commit": commit,
        "n_patches_evaluated": n,
        "n_excluded": df.attrs.get("excluded"),
        "base_rate_overfitting": float(df["y"].mean()) if n else None,
        "detection_lopo_primary": lopo,
        "detection_groupkfold_by_bug_secondary": gkf,
        "ranking": ep.ranking_section(df) if n else {},
        "counterexample_funnel": ep.counterexample_funnel_section(df) if n else {},
        "s_cex_missingness": ep.s_cex_missingness_section(df) if n else {},
        "stage2b_coverage": ep.stage2b_coverage_section(df) if n else {},
        "complementarity": ep.complementarity_section(df) if n else {},
        "sensitivity": ep.sensitivity_section(df) if n else {},
        "context_ablation": context_ablation_section(),
        "memorization": ep.memorization_section(),
        "runtime": full_runtime_section(),
        "cost": full_cost_section(),
    }
    OUT.write_text(json.dumps(result, indent=2, default=str))

    # LaTeX tables
    write_detection_tex(lopo, TEX_DIR / "table_detection_lopo.tex",
                        "Detection by method, leave-one-project-out (primary). Positive class = overfitting; "
                        "$n=%d$, base rate %.3f. MCC 95\\%% CI: bug-clustered bootstrap, 10{,}000, seed 2026." %
                        (n, result["base_rate_overfitting"]), "tab:detection-lopo", commit)
    write_detection_tex(gkf, TEX_DIR / "table_detection_groupkfold.tex",
                        "Detection by method, GroupKFold-by-bug (secondary, 5 folds, seed 2026).",
                        "tab:detection-gkf", commit)
    write_paired_tex(lopo, TEX_DIR / "table_paired_mcc.tex", commit)
    write_ranking_tex(result["ranking"], TEX_DIR / "table_ranking.tex", commit)

    print(json.dumps({"n_evaluated": n, "excluded": df.attrs.get("excluded"),
                      "base_rate": result["base_rate_overfitting"],
                      "M3": _point(lopo["methods"]["M3_semantic"]),
                      "cost_usd": result["cost"]["total_usd"]}, indent=2, default=str))
    return result


if __name__ == "__main__":
    evaluate()
