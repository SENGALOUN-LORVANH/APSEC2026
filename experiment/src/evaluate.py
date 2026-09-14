"""Evaluation (RQ1-RQ4): baselines, leave-one-project-out CV, bug-level bootstrap CIs, McNemar, Precision@1,
cost and latency, generated LaTeX tables.

Positive class = OVERFITTING.

Usage:
  python src/evaluate.py                                   # features-only baselines (no LLM yet)
  python src/evaluate.py --llm main=results/raw_llm_responses.jsonl [--llm diffonly=results/other.jsonl]

The first --llm entry is the main configuration used for "LLM only" and "Combined" in Table I; further entries
appear as extra rows (e.g. prompt/context ablations). Every LLM log must cover every patch; nothing is dropped.
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
sys.path.insert(0, str(Path(__file__).parent))
from pilot_summary import PRICES  # noqa: E402

# Label-leaking columns (filename suffix, tool, source, whitespace artefact) are deliberately NOT features.
FEATURES = ["lines_added", "lines_removed", "total_changed", "code_lines_added", "code_lines_removed",
            "n_hunks", "n_files", "only_deletes", "adds_conditional_guard", "literal_in_failing_test_message"]
LOG_FEATURES = ["lines_added", "lines_removed", "total_changed", "code_lines_added", "code_lines_removed"]
B = 10_000
SEED = 2026


# ---------------------------------------------------------------- data
def load_base():
    feats = pd.read_csv(RES / "patch_features.csv")
    for c in LOG_FEATURES:
        feats[c] = np.log1p(feats[c])
    feats["y"] = (feats["label"] == "overfitting").astype(int)
    return feats.reset_index(drop=True)


def load_llm(path, patch_ids):
    rows = [json.loads(l) for l in open(path)]
    ok = [r for r in rows if r["status"] == "ok" and r.get("parsed")]
    models, shas = {r["model"] for r in ok}, {r["prompt_sha"] for r in ok}
    if len(models) != 1 or len(shas) != 1:
        sys.exit(f"{path}: expected one model and one prompt, found {models} / {shas}")
    per, out_of_range = defaultdict(list), 0
    for r in ok:
        conf = float(r["parsed"]["confidence"])
        if not 0.0 <= conf <= 1.0:
            out_of_range += 1
            conf = min(max(conf, 0.0), 1.0)
        over = r["parsed"]["judgement"] == "OVERFITTING"
        per[r["patch_id"]].append((over, conf if over else 1.0 - conf))
    missing = sorted(set(patch_ids) - set(per))
    if missing:
        sys.exit(f"{path}: {len(missing)} patches have no successful parsed response, e.g. {missing[:3]}. "
                 "Re-run llm_review.py (it resumes) before evaluating.")
    df = pd.DataFrame([{
        "patch_id": pid,
        "llm_runs": len(v),
        "llm_votes_overfitting": sum(o for o, _ in v),
        "llm_p": float(np.mean([p for _, p in v])),
    } for pid, v in per.items()])
    df["llm_vote"] = np.where(df.llm_votes_overfitting * 2 == df.llm_runs, (df.llm_p >= 0.5).astype(int),
                              (df.llm_votes_overfitting * 2 > df.llm_runs).astype(int))
    df["llm_consistency"] = np.maximum(df.llm_votes_overfitting, df.llm_runs - df.llm_votes_overfitting) / df.llm_runs
    meta = {"log": str(path), "model": models.pop(), "prompt_sha": shas.pop(), "calls_ok_parsed": len(ok),
            "calls_total": len(rows), "confidence_out_of_range_clipped": out_of_range}
    return df, meta, [r for r in rows if r["status"] == "ok"]


# ---------------------------------------------------------------- methods
def lopo_lr(df, cols):
    p, coefs = np.full(len(df), np.nan), {}
    for proj in sorted(df.project.unique()):
        tr, te = (df.project != proj).values, (df.project == proj).values
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000))
        m.fit(df.loc[tr, cols], df.loc[tr, "y"])
        p[te] = m.predict_proba(df.loc[te, cols])[:, 1]
    full = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000)).fit(df[cols], df["y"])
    coefs = dict(zip(cols, np.round(full[-1].coef_[0], 4).tolist()))
    return p, coefs


def lopo_trivial(df, kind):
    rng = np.random.default_rng(SEED)
    score, pred = np.zeros(len(df)), np.zeros(len(df), dtype=int)
    for proj in sorted(df.project.unique()):
        tr, te = (df.project != proj).values, (df.project == proj).values
        rate = df.loc[tr, "y"].mean()
        if kind == "majority":
            score[te], pred[te] = rate, int(rate >= 0.5)
        else:
            score[te] = rng.random(te.sum())
            pred[te] = (rng.random(te.sum()) < rate).astype(int)
    return score, pred


# ---------------------------------------------------------------- metrics
def rates(tp, fp, tn, fn):
    tp, fp, tn, fn = (np.asarray(x, dtype=float) for x in (tp, fp, tn, fn))
    with np.errstate(divide="ignore", invalid="ignore"):
        prec = np.where(tp + fp > 0, tp / (tp + fp), np.nan)
        rec = np.where(tp + fn > 0, tp / (tp + fn), np.nan)
        f1 = np.where(2 * tp + fp + fn > 0, 2 * tp / (2 * tp + fp + fn), np.nan)
        acc = (tp + tn) / (tp + fp + tn + fn)
        spec = np.where(tn + fp > 0, tn / (tn + fp), np.nan)
    return {"precision": prec, "recall": rec, "f1": f1, "accuracy": acc, "specificity_correct_kept": spec}


def per_bug_counts(df, pred):
    y = df["y"].values
    c = pd.DataFrame({"bug": df["bug_id"].values, "tp": (y == 1) & (pred == 1), "fp": (y == 0) & (pred == 1),
                      "tn": (y == 0) & (pred == 0), "fn": (y == 1) & (pred == 0)}).groupby("bug").sum()
    return c[["tp", "fp", "tn", "fn"]].values.astype(float)


def ci(a):
    a = a[~np.isnan(a)]
    return [round(float(np.percentile(a, 2.5)), 4), round(float(np.percentile(a, 97.5)), 4)] if len(a) else None


def mcnemar(y, pred_a, pred_b):
    a_ok, b_ok = pred_a == y, pred_b == y
    b, c = int((a_ok & ~b_ok).sum()), int((~a_ok & b_ok).sum())
    return {"a_right_b_wrong": b, "a_wrong_b_right": c,
            "p_value_exact": float(binomtest(min(b, c), b + c, 0.5).pvalue) if b + c else 1.0}


def precision_at_1(df, score):
    rows = []
    d = df.assign(score=score)
    for bug, g in d.groupby("bug_id"):
        if len(g) < 2:
            continue
        best = g.score.min()  # lowest P(overfitting) ranked first
        top = g[np.isclose(g.score, best)]
        rows.append({"bug_id": bug, "n_patches": len(g), "n_correct": int((g.y == 0).sum()),
                     "n_tied_top": len(top), "top1_correct_expected": float((top.y == 0).mean()),
                     "random_expected": float((g.y == 0).mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="append", default=[], help="name=path to an LLM log (first = main)")
    args = ap.parse_args()

    df = load_base()
    methods, notes, llm_meta, llm_rows_main = {}, {}, {}, None
    for kind in ("majority", "random"):
        s, p = lopo_trivial(df, kind)
        methods[{"majority": "Majority class", "random": "Random (stratified)"}[kind]] = (s, p)
    s, coefs = lopo_lr(df, FEATURES)
    methods["Diff features only"] = (s, (s >= 0.5).astype(int))
    notes["lr_coefficients_full_fit"] = {"Diff features only": coefs}

    for i, spec in enumerate(args.llm):
        name, path = spec.split("=", 1)
        llm, meta, ok_rows = load_llm(ROOT / path, df.patch_id)
        llm = llm.rename(columns={c: f"{c}__{name}" for c in llm.columns if c != "patch_id"})
        df = df.merge(llm, on="patch_id", how="left")
        llm_meta[name] = meta
        suffix = "" if i == 0 else f" [{name}]"
        methods[f"LLM only{suffix}"] = (df[f"llm_p__{name}"].values, df[f"llm_vote__{name}"].values)
        cols = FEATURES + [f"llm_p__{name}", f"llm_vote__{name}"]
        s, coefs = lopo_lr(df, cols)
        methods[f"Combined{suffix}"] = (s, (s >= 0.5).astype(int))
        notes["lr_coefficients_full_fit"][f"Combined{suffix}"] = coefs
        if i == 0:
            llm_rows_main = ok_rows

    y, rng = df["y"].values, np.random.default_rng(SEED)
    bugs = df["bug_id"].unique()
    weights = rng.multinomial(len(bugs), np.full(len(bugs), 1 / len(bugs)), size=B)  # bug-level resampling
    boot_f1, results = {}, {}
    for name, (score, pred) in methods.items():
        counts = per_bug_counts(df, pred)
        point = {k: float(v) for k, v in rates(*counts.sum(0)).items()}
        boot = rates(*(weights @ counts).T)
        boot_f1[name] = boot["f1"]
        try:
            auc = float(roc_auc_score(y, score)) if len(np.unique(score)) > 1 else 0.5
        except ValueError:
            auc = None
        tp, fp, tn, fn = counts.sum(0).astype(int).tolist()
        results[name] = {**{k: round(v, 4) for k, v in point.items()},
                         **{f"{k}_ci95": ci(v) for k, v in boot.items()},
                         "auc": None if auc is None else round(auc, 4),
                         "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn}}

    ref = next((m for m in methods if m == "Combined"), "Diff features only")
    comparisons = {}
    for name, (_, pred) in methods.items():
        if name == ref:
            continue
        comparisons[f"{ref} vs {name}"] = {**mcnemar(y, methods[ref][1], pred),
                                           "delta_f1": round(float(results[ref]["f1"] - results[name]["f1"]), 4),
                                           "delta_f1_ci95": ci(boot_f1[ref] - boot_f1[name])}

    p1_tables, p1 = [], {}
    for name, (score, _) in methods.items():
        t = precision_at_1(df, score)
        t.insert(0, "method", name)
        p1_tables.append(t)
        idx = rng.integers(0, len(t), size=(B, len(t)))
        vals = t.top1_correct_expected.values
        has = t[t.n_correct > 0].top1_correct_expected.values
        p1[name] = {"bugs_with_>=2_patches": len(t), "precision_at_1": round(float(vals.mean()), 4),
                    "precision_at_1_ci95": ci(vals[idx].mean(1)),
                    "precision_at_1_among_bugs_with_a_correct_patch": round(float(has.mean()), 4),
                    "ceiling_fraction_bugs_with_a_correct_patch": round(float((t.n_correct > 0).mean()), 4),
                    "random_ranking_expected": round(float(t.random_expected.mean()), 4)}
    pd.concat(p1_tables).to_csv(RES / "precision_at_1.csv", index=False)

    per_project = {name: {proj: {"n": int(g.shape[0]), "base_rate": round(float(g.y.mean()), 4),
                                 "f1": round(float(rates(*per_bug_counts(g, pred[g.index]).sum(0))["f1"]), 4)}
                          for proj, g in df.groupby("project")}
                   for name, (_, pred) in methods.items()}

    pred_df = df[["patch_id", "bug_id", "project", "label", "y"]].copy()
    for name, (score, pred) in methods.items():
        pred_df[f"score::{name}"], pred_df[f"pred::{name}"] = score, pred
    extra = [c for c in df.columns if c.startswith("llm_")]
    pred_df = pd.concat([pred_df, df[extra]], axis=1)
    pred_df.to_csv(RES / "predictions.csv", index=False)

    cost = None
    if llm_rows_main:
        model = llm_rows_main[0]["model"]
        pin, pout = PRICES[model]
        lat = np.array([r["latency_s"] for r in llm_rows_main])
        tin = np.array([r["usage"]["input_tokens"] + (r["usage"].get("cache_read_input_tokens") or 0)
                        + (r["usage"].get("cache_creation_input_tokens") or 0) for r in llm_rows_main])
        tout = np.array([r["usage"]["output_tokens"] for r in llm_rows_main])
        usd = (tin * pin + tout * pout) / 1e6
        per_patch = pd.DataFrame({"pid": [r["patch_id"] for r in llm_rows_main], "lat": lat, "usd": usd}) \
            .groupby("pid").sum()
        cost = {"model": model, "calls": len(llm_rows_main),
                "latency_s_per_call": {"mean": round(float(lat.mean()), 2), "median": round(float(np.median(lat)), 2),
                                       "p90": round(float(np.percentile(lat, 90)), 2)},
                "latency_s_per_patch_all_runs_sequential": {"mean": round(float(per_patch.lat.mean()), 2),
                                                            "median": round(float(per_patch.lat.median()), 2)},
                "tokens_per_call": {"input_mean": round(float(tin.mean())), "output_mean": round(float(tout.mean()))},
                "usd_per_call_mean": round(float(usd.mean()), 5),
                "usd_per_patch_all_runs_mean": round(float(per_patch.usd.mean()), 5),
                "usd_total": round(float(usd.sum()), 2),
                "price_source": "Anthropic list prices from Claude API skill table cached 2026-06-24; verify",
                "retried_calls": int(sum(r["attempts"] > 1 for r in llm_rows_main))}
        (RES / "cost_and_latency.json").write_text(json.dumps(cost, indent=2))

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    metrics = {"generated_by": "src/evaluate.py", "git_commit": commit, "positive_class": "overfitting",
               "n_patches": len(df), "n_bugs": int(df.bug_id.nunique()), "base_rate_overfitting": round(float(y.mean()), 4),
               "validation": "leave-one-project-out; metrics pooled over all out-of-fold predictions",
               "bootstrap": {"resamples": B, "unit": "bug", "seed": SEED},
               "features": FEATURES, "log1p_features": LOG_FEATURES, "llm_logs": llm_meta,
               "methods": results, "comparisons": comparisons, "precision_at_1": p1,
               "per_project": per_project, **notes, "cost_and_latency": cost}
    (RES / "metrics.json").write_text(json.dumps(metrics, indent=2))

    with open(RES / "confusion_matrices.txt", "w") as f:
        for name, r in results.items():
            c = r["confusion"]
            f.write(f"{name}\n                 pred OVERFIT  pred CORRECT\n"
                    f"  true OVERFIT   {c['tp']:>12}  {c['fn']:>12}\n  true CORRECT   {c['fp']:>12}  {c['tn']:>12}\n\n")

    fmt = lambda v, c: f"{v:.2f} [{c[0]:.2f}, {c[1]:.2f}]" if c and v == v else "--"
    gen = f"% Generated by src/evaluate.py at commit {commit}. Do not edit by hand.\n"
    lines = [gen, "\\begin{tabular}{lcccc}", "\\hline",
             "Method & Precision & Recall & F1 & Accuracy \\\\", "\\hline"]
    for name, r in results.items():
        lines.append(f"{name} & {fmt(r['precision'], r['precision_ci95'])} & {fmt(r['recall'], r['recall_ci95'])} & "
                     f"{fmt(r['f1'], r['f1_ci95'])} & {fmt(r['accuracy'], r['accuracy_ci95'])} \\\\")
    lines += ["\\hline", "\\end{tabular}", ""]
    (RES / "table1_main.tex").write_text("\n".join(lines))

    abl = [m for m in methods if m.startswith(("LLM only", "Diff features only", "Combined"))]
    lines = [gen, "\\begin{tabular}{lccc}", "\\hline",
             f"Configuration & F1 & $\\Delta$F1 vs {ref} & McNemar $p$ \\\\", "\\hline"]
    for name in abl:
        comp = comparisons.get(f"{ref} vs {name}")
        d = f"{-comp['delta_f1']:+.2f} [{-comp['delta_f1_ci95'][1]:.2f}, {-comp['delta_f1_ci95'][0]:.2f}]" if comp else "--"
        p = f"{comp['p_value_exact']:.3g}" if comp else "--"
        lines.append(f"{name} & {fmt(results[name]['f1'], results[name]['f1_ci95'])} & {d} & {p} \\\\")
    lines += ["\\hline", "\\end{tabular}", ""]
    (RES / "table2_ablation.tex").write_text("\n".join(lines))

    print(json.dumps({"base_rate": metrics["base_rate_overfitting"],
                      "methods": {k: {m: v[m] for m in ("precision", "recall", "f1", "f1_ci95", "accuracy", "auc")}
                                  for k, v in results.items()},
                      "comparisons": comparisons, "precision_at_1": p1}, indent=1))


if __name__ == "__main__":
    main()
