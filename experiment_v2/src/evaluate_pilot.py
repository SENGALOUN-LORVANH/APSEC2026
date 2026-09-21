"""Pilot evaluation (Step 17-18, corrected). Detection is reported PER METHOD using the frozen protocol
rules (protocol.yaml evaluation.methods), NOT the old placeholder `PVS* < 0.5`:

  M0 majority            baseline (LOPO, predict training-fold majority class)
  M1 random stratified   baseline (LOPO, predict 1 at training-fold base rate; seed 2026)
  M2 diff-feature        logistic regression on [S_edit] (LOPO, C=1.0, standardized in-fold, no tuning)
  M3 semantic            frozen rule: OVERFITTING iff S_sem_final < 0.5 (no training); score = 1 - S_sem
  M4 counterexample      threshold-free AUROC/AP on (1 - S_cex) among patches with S_cex available, plus a
                         PRE-DECLARED binary rule (see protocol/DEVIATIONS.md) and S_cex missingness
  M6 sem+cex             logistic regression on [S_sem, S_cex + missingness indicator] (LOPO)
  M5/M7/M8/M9            static-analysis methods -- PENDING Stage 2B (Step 6); reported once CFG/PDG/vuln exist
  M10 full PVS           PENDING real human preferences (Bradley-Terry weights)

PVS* is a RANKING score only (never a detection threshold) and is never computed for a patch whose S_sem is
missing (pvs.score_row marks it missing). Every number here is PRELIMINARY ENGINEERING PILOT data.
"""
import csv
import json
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

import d4j
import metrics
import scores as scores_mod

ROOT = Path(__file__).resolve().parents[1]
PATCH_SCORES = ROOT / "results" / "patch_scores.csv"
SEMANTIC_RUNS_DIR = ROOT / "results" / "semantic_runs"
MODEL_COMPARISON_DIR = ROOT / "results" / "model_comparison"
COUNTEREXAMPLE_RUNS_DIR = ROOT / "results" / "counterexample_runs"
MEMORIZATION_CSV = ROOT / "results" / "memorization_probe.csv"
PILOT_SAMPLE = ROOT / "results" / "pilot_sample.csv"
PILOT_LOG = ROOT / "results" / "pilot_log.json"
SMOKE_LOG = ROOT / "results" / "smoke_test_log.json"
OUT = ROOT / "results" / "pilot_evaluation.json"

# Anthropic public API pricing, USD per 1,000,000 tokens (input/output). Source + date recorded so cost is
# reproducible and auditable; supplied by the author 2026-09-21.
PRICING = {"claude-haiku-4-5": {"in": 1.0, "out": 5.0},
           "claude-sonnet-5": {"in": 2.0, "out": 10.0}}
PRICING_SOURCE = ("Anthropic public API list pricing, USD per 1M tokens: Haiku 4.5 $1 in / $5 out, "
                  "Sonnet 5 $2 in / $10 out. Recorded 2026-09-21.")

# Pre-declared M4 binary rule (documented in protocol/DEVIATIONS.md BEFORE this code computes it).
M4_BINARY_RULE = ("OVERFITTING iff S_cex < 1.0 (candidate fails at least one VALID_BUG_REVEALING test), "
                  "computed only on patches where S_cex is available; S_cex==NA -> abstain (not predicted).")


def _f(v):
    return float(v) if v not in (None, "", "None") else None


def load_scored_frame():
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        manifest = {r["patch_id"]: r for r in csv.DictReader(f)}
    sample = {}
    if PILOT_SAMPLE.exists():
        with open(PILOT_SAMPLE, newline="", encoding="utf-8") as f:
            sample = {r["patch_id"]: r for r in csv.DictReader(f)}
    with open(PATCH_SCORES, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        m = manifest.get(r["patch_id"])
        if not m:
            continue
        s_sem = _f(r["S_sem"])
        samp = sample.get(r["patch_id"], {})
        out.append({"patch_id": r["patch_id"], "bug_id": m["bug_id"], "project": m["project"],
                    "ground_truth_label": r["ground_truth_label"],
                    "y": 1 if r["ground_truth_label"] == "overfitting" else 0,
                    "label_sensitivity": m.get("label_sensitivity", ""),
                    "included_sensitivity": m.get("included_sensitivity", ""),
                    "duplicate_group_id": m.get("duplicate_group_id", ""),
                    "size": int(samp["size"]) if samp.get("size") else None,
                    "tercile": samp.get("tercile", ""),
                    "PVS": _f(r["PVS"]), "S_sem": s_sem, "S_cex": _f(r["S_cex"]),
                    "S_edit": _f(r["S_edit"]), "S_vuln": _f(r["S_vuln"]),
                    "s_sem_missing": s_sem is None})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- detection per method
def _lopo_lr(df, cols):
    """Out-of-fold LOPO logistic-regression predictions. Missing features are mean-imputed within the
    training fold and flagged with a missingness indicator (protocol: missingness-indicator logistic model).
    Standardized within the training fold, C=1.0, threshold 0.5, no tuning."""
    y = df["y"].values
    pred = np.full(len(df), np.nan)
    score = np.full(len(df), np.nan)
    for _proj, tr, te in metrics.lopo_splits(df):
        Xtr = df.iloc[tr][cols].astype(float).copy()
        Xte = df.iloc[te][cols].astype(float).copy()
        means = Xtr.mean()
        for c in cols:
            if Xtr[c].isna().any():
                Xtr[c + "_miss"] = Xtr[c].isna().astype(float)
                Xte[c + "_miss"] = Xte[c].isna().astype(float)
        Xtr = Xtr.fillna(means)
        Xte = Xte.fillna(means)
        if len(np.unique(y[tr])) < 2:
            p = np.full(len(te), float(y[tr][0]))
        else:
            scaler = StandardScaler().fit(Xtr.values)
            clf = LogisticRegression(C=1.0, max_iter=1000).fit(scaler.transform(Xtr.values), y[tr])
            p = clf.predict_proba(scaler.transform(Xte.values))[:, 1]
        score[te] = p
        pred[te] = (p >= 0.5).astype(float)
    return pred.astype(int), score


def _baseline_majority(df):
    y = df["y"].values
    pred = np.full(len(df), np.nan)
    for _proj, tr, te in metrics.lopo_splits(df):
        maj = int(round(y[tr].mean()))
        pred[te] = maj
    return pred.astype(int), None


def _baseline_random(df, seed=2026):
    y = df["y"].values
    rng = np.random.default_rng(seed)
    pred = np.full(len(df), np.nan)
    for _proj, tr, te in metrics.lopo_splits(df):
        rate = y[tr].mean()
        pred[te] = (rng.random(len(te)) < rate).astype(int)
    return pred.astype(int), None


def _with_ci(df, y, pred, metric="mcc"):
    w, order = metrics.cluster_weights(df["bug_id"].values, B=10000, seed=2026)
    samples = metrics.bootstrap_count_metrics(y, pred, df["bug_id"].values, w, order)[metric]
    return metrics.ci95(samples)


def detection_section(df):
    y = df["y"].values
    out = {"positive_class": "overfitting", "n": int(len(df)),
           "base_rate_overfitting": float(y.mean()) if len(df) else None,
           "note": "PRELIMINARY ENGINEERING PILOT -- n is small and LOPO folds are tiny; not a paper result. "
                   "Detection is per-method per protocol.yaml, replacing the earlier placeholder PVS*<0.5.",
           "methods": {}}

    def record(name, pred, score, extra=None):
        m = metrics.detection_metrics(y, pred, score=score)
        m["mcc_ci95_cluster_bootstrap"] = _with_ci(df, y, pred, "mcc")
        m["f1_ci95_cluster_bootstrap"] = _with_ci(df, y, pred, "f1")
        # per-project LOPO test folds
        per_project = {}
        for proj, _tr, te in metrics.lopo_splits(df):
            yt = y[te]
            if len(np.unique(yt)) < 2:
                per_project[proj] = {"note": "single class in held-out project", "n": int(len(te))}
            else:
                per_project[proj] = metrics.detection_metrics(yt, np.asarray(pred)[te],
                                                              score=None if score is None else np.asarray(score)[te])
        m["lopo_per_project"] = per_project
        if extra:
            m.update(extra)
        out["methods"][name] = m
        return pred

    # M0 / M1 baselines
    p0, _ = _baseline_majority(df); record("M0_majority", p0, None)
    p1, _ = _baseline_random(df); record("M1_random_stratified", p1, None)
    # M2 diff-feature LR
    p2, s2 = _lopo_lr(df, ["S_edit"]); record("M2_diff_feature", p2, s2)
    # M3 semantic frozen rule (no training)
    p3 = (df["S_sem"] < 0.5).astype(int).values
    s3 = (1.0 - df["S_sem"]).values
    record("M3_semantic", p3, s3,
           {"rule": "OVERFITTING iff S_sem_final < 0.5 (frozen)", "n_missing_S_sem": int(df["s_sem_missing"].sum())})
    # M4 counterexample: threshold-free on available S_cex + declared binary rule
    out["methods"]["M4_counterexample"] = _m4_counterexample(df)
    # M6 sem+cex LR
    p6, s6 = _lopo_lr(df, ["S_sem", "S_cex"]); record("M6_sem_cex", p6, s6)

    # pending methods
    for name, why in [("M5_static", "Stage 2B (CFG/PDG + S_vuln) -- Step 6"),
                      ("M7_sem_static", "Stage 2B -- Step 6"), ("M8_cex_static", "Stage 2B -- Step 6"),
                      ("M9_sem_cex_static", "Stage 2B -- Step 6"),
                      ("M10_full_pvs_human_prefs", "real human preferences (Bradley-Terry) -- PENDING")]:
        out["methods"][name] = {"status": "PENDING", "reason": why}

    # paired bootstrap differences (improvement iff 95% CI of paired difference excludes 0)
    out["paired_differences_mcc"] = {
        "M3_semantic_vs_M0_majority": metrics.paired_difference(y, p3, p0, df["bug_id"].values, metric="mcc"),
        "M3_semantic_vs_M2_diff_feature": metrics.paired_difference(y, p3, p2, df["bug_id"].values, metric="mcc"),
        "M6_sem_cex_vs_M3_semantic": metrics.paired_difference(y, p6, p3, df["bug_id"].values, metric="mcc"),
    }
    return out


def _m4_counterexample(df):
    avail = df[df["S_cex"].notna()].copy()
    n_avail = int(len(avail))
    result = {"n_total": int(len(df)), "n_S_cex_available": n_avail,
              "n_S_cex_missing": int(df["S_cex"].isna().sum()),
              "binary_rule": M4_BINARY_RULE}
    if n_avail == 0:
        result["note"] = "no patch had a non-NA S_cex; threshold-free and binary metrics undefined"
        return result
    y = avail["y"].values
    score = (1.0 - avail["S_cex"]).values  # higher = more likely overfitting
    if len(np.unique(y)) == 2 and len(np.unique(score)) > 1:
        from sklearn.metrics import average_precision_score, roc_auc_score
        result["auroc_on_available"] = float(roc_auc_score(y, score))
        result["average_precision_on_available"] = float(average_precision_score(y, score))
    else:
        result["auroc_on_available"] = result["average_precision_on_available"] = None
        result["note_threshold_free"] = "single class or constant score among available; AUROC/AP undefined"
    pred = (avail["S_cex"] < 1.0).astype(int).values
    result["binary_on_available"] = metrics.detection_metrics(y, pred, score=score)
    return result


# ---------------------------------------------------------------- counterexample funnel + missingness
FUNNEL_STAGES = ["generated", "compiled", "fixed_pass", "buggy_fail", "stable_bug_revealing",
                 "candidate_discriminating"]


def _load_cex_runs():
    out = []
    if not COUNTEREXAMPLE_RUNS_DIR.exists():
        return out
    for f in sorted(COUNTEREXAMPLE_RUNS_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _funnel_counts(entries):
    """Per-test attrition, summed. status enum (scores.counterexample_status) collapses the stable multi-rep
    sequence, so fixed_pass == VALID_* and stable_bug_revealing == VALID_BUG_REVEALING by construction."""
    c = dict.fromkeys(FUNNEL_STAGES, 0)
    n_patches_with_error = 0
    for e in entries:
        if e.get("error"):
            n_patches_with_error += 1
        tests = e.get("tests", [])
        c["generated"] += len(tests)
        for t in tests:
            st = t.get("status")
            if st != "INVALID_COMPILE":
                c["compiled"] += 1
            if st in ("VALID_BUG_REVEALING", "VALID_NON_DISCRIMINATING"):
                c["fixed_pass"] += 1
            if st == "VALID_BUG_REVEALING":
                c["buggy_fail"] += 1
                c["stable_bug_revealing"] += 1
                if t.get("candidate_pass") is False:
                    c["candidate_discriminating"] += 1
    return c, n_patches_with_error


def counterexample_funnel_section(df):
    entries = _load_cex_runs()
    by_pid = {e["patch_id"]: e for e in entries}
    overall, n_err = _funnel_counts(entries)
    result = {"overall": overall, "n_patches_with_cex_run": len(entries),
              "n_patches_with_generation_error": n_err,
              "stage_definitions": "generated->compiled->fixed_pass->buggy_fail->stable_bug_revealing->"
                                   "candidate_discriminating (per-test, summed; see scores.counterexample_status)"}
    for dim in ("project", "ground_truth_label", "tercile"):
        grp = {}
        for key, sub in df.groupby(dim):
            sub_entries = [by_pid[p] for p in sub["patch_id"] if p in by_pid]
            counts, _ = _funnel_counts(sub_entries)
            grp[str(key) if key != "" else "(unknown)"] = {"n_patches": len(sub_entries), **counts}
        result[f"by_{dim}"] = grp
    return result


def s_cex_missingness_section(df):
    def frac(sub):
        n = len(sub); miss = int(sub["S_cex"].isna().sum())
        return {"n": int(n), "n_missing": miss, "missing_rate": (miss / n) if n else None}
    out = {"overall": frac(df)}
    for dim in ("project", "ground_truth_label", "tercile"):
        out[f"by_{dim}"] = {str(k) if k != "" else "(unknown)": frac(sub) for k, sub in df.groupby(dim)}
    return out


# ---------------------------------------------------------------- ranking (PVS* only, excl missing S_sem)
def ranking_section(df):
    ranked = df[df["PVS"].notna()].copy()
    excluded = int(df["PVS"].isna().sum())
    table = metrics.ranking_table(ranked, score_col="PVS", bug_col="bug_id", label_col="y")
    summary = metrics.ranking_summary(table) if not table.empty else {"conditional": {"bugs": 0},
                                                                       "end_to_end": {"bugs": 0}}
    return {"score": "PVS* (ranking only; placeholder equal weights -- NOT calibrated)",
            "n_patches_ranked": int(len(ranked)), "n_excluded_PVS_missing": excluded,
            "summary": summary, "n_bugs_with_multiple_candidates": int(len(table))}


# ---------------------------------------------------------------- model comparison (parse rate excl billing)
def _error_class(err):
    if err is None:
        return "ok"
    e = str(err).lower()
    if "credit balance" in e or "billing" in e or "insufficient" in e:
        return "billing"
    if "parse failure" in e:
        return "parse"
    if "max_tokens" in e or "token" in e and "limit" in e:
        return "token_limit"
    if "apiconnection" in e or "connection" in e:
        return "connection"
    if "ratelimit" in e or "overloaded" in e:
        return "rate"
    return "other"


def model_comparison_section():
    def load_runs(directory, suffix=""):
        out = []
        if directory.exists():
            for f in directory.glob(f"*{suffix}.json"):
                try:
                    out.append(json.loads(f.read_text()))
                except (json.JSONDecodeError, OSError):
                    continue
        return out

    def summarize(entries, model_name):
        all_runs = [r for e in entries for r in e.get("runs", [])]
        classes = [_error_class(r.get("error")) for r in all_runs]
        n_runs = len(all_runs)
        n_billing = sum(1 for c in classes if c == "billing")
        n_effective = n_runs - n_billing  # parse rate excludes billing/credit failures (protocol selection_rule)
        n_parsed = sum(1 for r in all_runs if "s_sem" in r)
        n_token_limit = sum(1 for c in classes if c == "token_limit")
        latencies = [r["latency_s"] for r in all_runs if r.get("latency_s") is not None and "s_sem" in r]
        input_tok = [r["input_tokens"] for r in all_runs if r.get("input_tokens") is not None]
        output_tok = [r["output_tokens"] for r in all_runs if r.get("output_tokens") is not None]
        stabilities = []
        for e in entries:
            js = [r["parsed"]["judgement"] for r in e.get("runs", []) if r.get("parsed")]
            if len(js) >= 2:
                stabilities.append(scores_mod.run_stability(js))
        return {"model": model_name, "n_patches": len(entries), "n_runs": n_runs,
                "n_billing_errors_excluded": n_billing, "n_effective_runs": n_effective,
                "parse_success_rate_excl_billing": (n_parsed / n_effective) if n_effective else None,
                "token_limit_failure_rate_excl_billing": (n_token_limit / n_effective) if n_effective else None,
                "mean_judgement_stability": (sum(stabilities) / len(stabilities)) if stabilities else None,
                "median_latency_s": (statistics.median(latencies)) if latencies else None,
                "mean_latency_s": (sum(latencies) / len(latencies)) if latencies else None,
                "mean_input_tokens": (sum(input_tok) / len(input_tok)) if input_tok else None,
                "mean_output_tokens": (sum(output_tok) / len(output_tok)) if output_tok else None,
                "error_class_counts": {c: classes.count(c) for c in sorted(set(classes))}}

    primary = load_runs(SEMANTIC_RUNS_DIR)
    comparison = load_runs(MODEL_COMPARISON_DIR)
    return {"primary": summarize(primary, primary[0]["model"] if primary else None),
            "comparison": summarize(comparison, comparison[0]["model"] if comparison else None),
            "selection_rule": "protocol.yaml llm.selection_rule; ground-truth agreement never decides. "
                              "Selected model recorded in protocol.yaml + DEVIATIONS.md (Step 7)."}


def cost_section():
    def tokens_for(directory):
        tin = tout = 0
        n = 0
        if directory.exists():
            for f in directory.glob("*.json"):
                try:
                    e = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                runs = e.get("runs") or ([e] if "input_tokens" in e else [])
                for r in runs:
                    if r.get("input_tokens") is not None:
                        tin += r["input_tokens"]; tout += r.get("output_tokens") or 0; n += 1
        return tin, tout, n

    def usd(model, tin, tout):
        p = PRICING[model]
        return round(tin / 1e6 * p["in"] + tout / 1e6 * p["out"], 4)

    hi_in, hi_out, hi_n = tokens_for(SEMANTIC_RUNS_DIR)
    so_in, so_out, so_n = tokens_for(MODEL_COMPARISON_DIR)
    cx_in, cx_out, cx_n = tokens_for(COUNTEREXAMPLE_RUNS_DIR)  # counterexample uses primary (haiku)
    breakdown = {
        "semantic_haiku": {"model": "claude-haiku-4-5", "calls": hi_n, "input_tokens": hi_in,
                           "output_tokens": hi_out, "usd": usd("claude-haiku-4-5", hi_in, hi_out)},
        "semantic_sonnet_comparison": {"model": "claude-sonnet-5", "calls": so_n, "input_tokens": so_in,
                                       "output_tokens": so_out, "usd": usd("claude-sonnet-5", so_in, so_out)},
        "counterexample_haiku": {"model": "claude-haiku-4-5", "calls": cx_n, "input_tokens": cx_in,
                                 "output_tokens": cx_out, "usd": usd("claude-haiku-4-5", cx_in, cx_out)},
    }
    total = round(sum(v["usd"] for v in breakdown.values()), 4)
    total_calls = hi_n + so_n + cx_n
    return {"pricing_source": PRICING_SOURCE, "pricing_per_mtok_usd": PRICING,
            "breakdown": breakdown, "total_usd": total, "total_billable_calls": total_calls,
            "usd_per_patch_semantic_haiku": round(breakdown["semantic_haiku"]["usd"] / max(hi_n, 1) * 3, 6)}


# ---------------------------------------------------------------- complementarity (RQ3, sem vs cex now)
def complementarity_section(df):
    sem_flag = df["S_sem"].apply(lambda v: v is not None and not pd.isna(v) and v < 0.5)
    cex_available = df["S_cex"].notna()
    cex_flag = df["S_cex"].apply(lambda v: v is not None and not pd.isna(v) and v < 1.0)
    both = cex_available
    if both.sum() == 0:
        return {"n_both_available": 0, "note": "no patches had a non-NA S_cex",
                "static_arm": "PENDING Stage 2B (Step 6): cex-only/static-only/both/neither overlap"}
    of = df["y"] == 1
    return {"n_both_available": int(both.sum()),
            "among_overfitting": {
                "sem_only": int((sem_flag & ~cex_flag & both & of).sum()),
                "cex_only": int((~sem_flag & cex_flag & both & of).sum()),
                "both": int((sem_flag & cex_flag & both & of).sum()),
                "neither": int((~sem_flag & ~cex_flag & both & of).sum())},
            "among_correct_wrongly_flagged": {
                "sem_only": int((sem_flag & ~cex_flag & both & ~of).sum()),
                "cex_only": int((~sem_flag & cex_flag & both & ~of).sum()),
                "both": int((sem_flag & cex_flag & both & ~of).sum())},
            "static_arm": "PENDING Stage 2B (Step 6)"}


def sensitivity_section(df):
    """Label-policy and duplicate-collapse sensitivity, evaluated with the M3 semantic rule (S_sem<0.5),
    not PVS* (which is ranking-only). Pure re-grouping of already-computed scores."""
    out = {}
    have = df[df["S_sem"].notna()].copy()
    have["pred_m3"] = (have["S_sem"] < 0.5).astype(int)

    label_df = have[have["included_sensitivity"] == "True"].copy()
    if len(label_df):
        label_df["y_sensitivity"] = (label_df["label_sensitivity"] == "overfitting").astype(int)
        changed = int((label_df["y_sensitivity"] != label_df["y"]).sum())
        out["label_policy"] = {
            "method": "M3 semantic rule S_sem<0.5", "n": len(label_df), "n_labels_changed_vs_primary": changed,
            "detection_primary_labels": metrics.detection_metrics(label_df["y"].values, label_df["pred_m3"].values),
            "detection_sensitivity_labels": metrics.detection_metrics(label_df["y_sensitivity"].values,
                                                                      label_df["pred_m3"].values)}
    else:
        out["label_policy"] = {"n": 0}

    dup = have[have["duplicate_group_id"] != ""]
    if len(dup):
        collapsed = have.sort_values("patch_id")
        collapsed["_keep"] = collapsed["duplicate_group_id"].where(collapsed["duplicate_group_id"] != "",
                                                                   collapsed["patch_id"])
        collapsed = collapsed.drop_duplicates(subset="_keep", keep="first")
        out["duplicates"] = {"method": "M3 semantic rule S_sem<0.5", "n_primary": len(have),
                             "n_collapsed": len(collapsed), "n_duplicate_patches_in_sample": len(dup),
                             "detection_collapsed": metrics.detection_metrics(collapsed["y"].values,
                                                                              collapsed["pred_m3"].values)}
    else:
        out["duplicates"] = {"n_primary": len(have), "n_duplicate_patches_in_sample": 0,
                             "note": "no duplicate-group members in this pilot sample"}
    return out


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
        "PRELIMINARY_NOTICE": "PRELIMINARY ENGINEERING PILOT -- NOT FINAL PAPER RESULTS.",
        "n_patches_scored": len(df),
        "detection": detection_section(df) if len(df) else {"note": "no scored patches yet"},
        "counterexample_funnel": counterexample_funnel_section(df) if len(df) else {},
        "s_cex_missingness": s_cex_missingness_section(df) if len(df) else {},
        "ranking": ranking_section(df) if len(df) else {"note": "no scored patches yet"},
        "model_comparison": model_comparison_section(),
        "cost": cost_section(),
        "complementarity": complementarity_section(df) if len(df) else {"note": "no scored patches yet"},
        "sensitivity": sensitivity_section(df) if len(df) else {"note": "no scored patches yet"},
        "memorization": memorization_section(),
        "runtime": runtime_section(),
        "failures": failures_section(),
    }
    OUT.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
