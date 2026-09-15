"""Pilot evaluation (Step 17-18): detection metrics, ranking, model-selection comparison, complementarity,
memorization diagnostic, runtime/token accounting -- assembled into results/pilot_evaluation.json for
PRE_FLIGHT_REPORT_V2.md. Every number here is PRELIMINARY ENGINEERING PILOT data, not a paper result.
"""
import csv
import json
import statistics
from pathlib import Path

import numpy as np
import pandas as pd

import d4j
import metrics

ROOT = Path(__file__).resolve().parents[1]
PATCH_SCORES = ROOT / "results" / "patch_scores.csv"
SEMANTIC_RUNS_DIR = ROOT / "results" / "semantic_runs"
MODEL_COMPARISON_DIR = ROOT / "results" / "model_comparison"
COUNTEREXAMPLE_RUNS_DIR = ROOT / "results" / "counterexample_runs"
MEMORIZATION_CSV = ROOT / "results" / "memorization_probe.csv"
PILOT_LOG = ROOT / "results" / "pilot_log.json"
SMOKE_LOG = ROOT / "results" / "smoke_test_log.json"
OUT = ROOT / "results" / "pilot_evaluation.json"


def load_scored_frame():
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        manifest = {r["patch_id"]: r for r in csv.DictReader(f)}
    with open(PATCH_SCORES, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        m = manifest.get(r["patch_id"])
        if not m:
            continue
        pvs = r["PVS"]
        if pvs in (None, "", "None"):
            continue
        out.append({"patch_id": r["patch_id"], "bug_id": m["bug_id"], "project": m["project"],
                    "ground_truth_label": r["ground_truth_label"],
                    "y": 1 if r["ground_truth_label"] == "overfitting" else 0,
                    "PVS": float(pvs), "S_sem": _f(r["S_sem"]), "S_cex": _f(r["S_cex"]),
                    "S_edit": _f(r["S_edit"]), "S_vuln": _f(r["S_vuln"])})
    return pd.DataFrame(out)


def _f(v):
    return float(v) if v not in (None, "", "None") else None


def detection_section(df):
    """PVS < 0.5 -> predict overfitting (y=1). Preliminary: n=50, LOPO folds are tiny per project."""
    pred = (df["PVS"] < 0.5).astype(int)
    overall = metrics.detection_metrics(df["y"].values, pred.values, score=1 - df["PVS"].values)
    per_project = {}
    for proj, train_idx, test_idx in metrics.lopo_splits(df):
        test = df.iloc[test_idx]
        if test["y"].nunique() < 2:
            per_project[proj] = {"note": "single class in held-out project, metrics undefined", "n": len(test)}
            continue
        p = (test["PVS"] < 0.5).astype(int)
        per_project[proj] = metrics.detection_metrics(test["y"].values, p.values, score=1 - test["PVS"].values)
    return {"overall": overall, "lopo_per_project": per_project,
            "note": "PRELIMINARY -- n=50 is far too small for reliable LOPO folds; reported per protocol.yaml "
                    "staging regardless, not as a claim about method accuracy."}


def ranking_section(df):
    table = metrics.ranking_table(df, score_col="PVS", bug_col="bug_id", label_col="y")
    summary = metrics.ranking_summary(table) if not table.empty else {"conditional": {"bugs": 0}, "end_to_end": {"bugs": 0}}
    return {"summary": summary, "n_bugs_with_multiple_candidates": int(len(table))}


def model_comparison_section():
    """Parse rate, stability, latency, tokens for both candidate models, per protocol.yaml selection_rule."""
    def load_runs(directory, suffix=""):
        out = []
        if not directory.exists():
            return out
        for f in directory.glob(f"*{suffix}.json"):
            try:
                out.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def summarize(entries, model_name):
        all_runs = [r for e in entries for r in e.get("runs", [])]
        n_runs = len(all_runs)
        n_parsed = sum(1 for r in all_runs if "s_sem" in r)
        n_token_limit = sum(1 for r in all_runs if r.get("error") and "max_tokens" in str(r.get("error", "")).lower())
        latencies = [r["latency_s"] for r in all_runs if r.get("latency_s") is not None]
        input_tok = [r["input_tokens"] for r in all_runs if r.get("input_tokens") is not None]
        output_tok = [r["output_tokens"] for r in all_runs if r.get("output_tokens") is not None]
        stabilities = []
        for e in entries:
            vals = [r["s_sem"] for r in e.get("runs", []) if "s_sem" in r]
            if len(vals) >= 2:
                stabilities.append(statistics.pstdev(vals))
        return {"model": model_name, "n_patches": len(entries), "n_runs": n_runs,
                "parse_success_rate": (n_parsed / n_runs) if n_runs else None,
                "token_limit_failure_rate": (n_token_limit / n_runs) if n_runs else None,
                "mean_latency_s": (sum(latencies) / len(latencies)) if latencies else None,
                "mean_input_tokens": (sum(input_tok) / len(input_tok)) if input_tok else None,
                "mean_output_tokens": (sum(output_tok) / len(output_tok)) if output_tok else None,
                "mean_run_to_run_stability_stdev": (sum(stabilities) / len(stabilities)) if stabilities else None,
                "monetary_cost": "not computed -- no pricing table available for these models in this session"}

    primary = load_runs(SEMANTIC_RUNS_DIR)
    comparison = load_runs(MODEL_COMPARISON_DIR)
    primary_model = primary[0]["model"] if primary else None
    comparison_model = comparison[0]["model"] if comparison else None
    return {"primary": summarize(primary, primary_model), "comparison": summarize(comparison, comparison_model),
            "selection_rule": "protocol.yaml llm.selection_rule -- hierarchy: parse success >= 0.95, "
                              "token-limit failures <= 0.02, stability, latency, cost. Ground-truth agreement "
                              "never decides. This section is the evidence; the actual selected_model decision "
                              "is an author call recorded in protocol.yaml + DEVIATIONS.md, not computed here."}


def complementarity_section(df):
    """Overlap between S_sem-flagged-overfitting and S_cex-flagged-overfitting (candidate fails a valid
    bug-revealing test), among patches where both signals exist."""
    sem_flag = df["S_sem"].apply(lambda v: v is not None and v < 0.5)
    cex_available = df["S_cex"].notna()
    cex_flag = df["S_cex"].apply(lambda v: v is not None and v < 1.0)
    both = cex_available
    if both.sum() == 0:
        return {"n_both_available": 0, "note": "no patches had both S_sem and a non-NA S_cex"}
    sem_only = int((sem_flag & ~cex_flag & both).sum())
    cex_only = int((~sem_flag & cex_flag & both).sum())
    both_flag = int((sem_flag & cex_flag & both).sum())
    neither = int((~sem_flag & ~cex_flag & both).sum())
    return {"n_both_available": int(both.sum()), "sem_only_flags_overfitting": sem_only,
            "cex_only_flags_overfitting": cex_only, "both_flag_overfitting": both_flag,
            "neither_flags": neither}


def memorization_section():
    if not MEMORIZATION_CSV.exists():
        return {"n": 0}
    with open(MEMORIZATION_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    recognized = [r for r in rows if r.get("recognized") == "True"]
    return {"n": len(rows), "n_recognized": len(recognized),
            "recognition_rate": (len(recognized) / len(rows)) if rows else None}


def runtime_section():
    def total_seconds(log_path):
        if not log_path.exists():
            return None, 0
        entries = json.loads(log_path.read_text())
        total = sum(s["seconds"] for e in entries for s in e["stages"].values())
        return total, len(entries)

    smoke_total, smoke_n = total_seconds(SMOKE_LOG)
    pilot_total, pilot_n = total_seconds(PILOT_LOG)
    return {"smoke_test_seconds": smoke_total, "smoke_test_n_patches": smoke_n,
            "pilot_seconds": pilot_total, "pilot_n_patches": pilot_n,
            "pilot_mean_seconds_per_patch": (pilot_total / pilot_n) if pilot_total and pilot_n else None}


def failures_section():
    log = json.loads(PILOT_LOG.read_text()) if PILOT_LOG.exists() else []
    failed = [e for e in log if e.get("stopped_after")]
    return {"n_total": len(log), "n_completed": len(log) - len(failed), "n_stopped_early": len(failed),
            "stopped_early_detail": [{"bug_id": e["bug_id"], "patch_id": e["patch_id"],
                                      "stopped_after": e["stopped_after"]} for e in failed]}


def main():
    df = load_scored_frame()
    result = {
        "n_patches_scored": len(df),
        "detection": detection_section(df) if len(df) else {"note": "no scored patches yet"},
        "ranking": ranking_section(df) if len(df) else {"note": "no scored patches yet"},
        "model_comparison": model_comparison_section(),
        "complementarity": complementarity_section(df) if len(df) else {"note": "no scored patches yet"},
        "memorization": memorization_section(),
        "runtime": runtime_section(),
        "failures": failures_section(),
    }
    OUT.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
