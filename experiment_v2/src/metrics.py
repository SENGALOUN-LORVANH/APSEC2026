"""Evaluation primitives: imbalance-aware metrics, splits with leakage checks, cluster bootstrap, ranking metrics.

Conventions
- Detection: positive class = OVERFITTING (y = 1). `pred` in {0,1}. `score` = higher means more likely overfitting.
- Ranking: `correct_score` = higher means more likely correct (e.g. S_sem, PVS). Ties broken uniformly at random,
  reported as expectations.
- Bootstrap unit = bug (cluster).
"""
from math import comb

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold

PROJECTS = ("Chart", "Closure", "Lang", "Math", "Time")


# ---------------------------------------------------------------- detection metrics
def _rates(tp, fp, tn, fn):
    tp, fp, tn, fn = (np.asarray(x, dtype=float) for x in (tp, fp, tn, fn))
    with np.errstate(divide="ignore", invalid="ignore"):
        prec = np.where(tp + fp > 0, tp / (tp + fp), np.nan)
        rec = np.where(tp + fn > 0, tp / (tp + fn), np.nan)
        spec = np.where(tn + fp > 0, tn / (tn + fp), np.nan)
        f1_pos = np.where(2 * tp + fp + fn > 0, 2 * tp / (2 * tp + fp + fn), np.nan)
        f1_neg = np.where(2 * tn + fn + fp > 0, 2 * tn / (2 * tn + fn + fp), np.nan)
        denom = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        mcc = np.where(denom > 0, (tp * tn - fp * fn) / denom, 0.0)
    return {"precision": prec, "recall": rec, "f1": f1_pos, "macro_f1": (f1_pos + f1_neg) / 2,
            "specificity": spec, "correct_patch_retention": spec,
            "balanced_accuracy": (rec + spec) / 2, "accuracy": (tp + tn) / (tp + fp + tn + fn), "mcc": mcc}


def confusion(y, pred):
    y, pred = np.asarray(y), np.asarray(pred)
    return {"tp": int(((y == 1) & (pred == 1)).sum()), "fp": int(((y == 0) & (pred == 1)).sum()),
            "tn": int(((y == 0) & (pred == 0)).sum()), "fn": int(((y == 1) & (pred == 0)).sum())}


def detection_metrics(y, pred, score=None):
    c = confusion(y, pred)
    out = {k: float(v) for k, v in _rates(c["tp"], c["fp"], c["tn"], c["fn"]).items()}
    y = np.asarray(y)
    if score is not None and len(np.unique(y)) == 2 and len(np.unique(score)) > 1:
        out["auroc"] = float(roc_auc_score(y, score))
        out["average_precision"] = float(average_precision_score(y, score))
    else:
        out["auroc"] = out["average_precision"] = None
    out["confusion"] = c
    out["n"] = int(len(y))
    out["base_rate_overfitting"] = float(y.mean()) if len(y) else None
    return out


# ---------------------------------------------------------------- splits
def lopo_splits(df, project_col="project"):
    """Yield (held_out_project, train_index, test_index)."""
    for proj in sorted(df[project_col].unique()):
        test = np.flatnonzero(df[project_col].values == proj)
        train = np.flatnonzero(df[project_col].values != proj)
        yield proj, train, test


def groupkfold_splits(df, n_splits=5, seed=2026, group_col="bug_id"):
    gkf = GroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for k, (train, test) in enumerate(gkf.split(df, groups=df[group_col].values)):
        yield f"fold{k}", train, test


def assert_disjoint(df, train, test, col):
    overlap = set(df[col].values[train]) & set(df[col].values[test])
    if overlap:
        raise AssertionError(f"{col} leakage between train and test: {sorted(overlap)[:5]}")


def fold_assignments(df, seed=2026):
    rows = []
    for proj, train, test in lopo_splits(df):
        assert_disjoint(df, train, test, "project")
        rows += [{"patch_id": df.patch_id.values[i], "split": "LOPO", "fold": proj} for i in test]
    for fold, train, test in groupkfold_splits(df, seed=seed):
        assert_disjoint(df, train, test, "bug_id")
        rows += [{"patch_id": df.patch_id.values[i], "split": "GroupKFold", "fold": fold} for i in test]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- cluster bootstrap
def cluster_weights(clusters, B=10_000, seed=2026):
    """Multinomial cluster resampling weights: shape (B, n_clusters), plus cluster order."""
    uniq = pd.unique(np.asarray(clusters))
    rng = np.random.default_rng(seed)
    return rng.multinomial(len(uniq), np.full(len(uniq), 1 / len(uniq)), size=B), uniq


def _per_cluster_counts(y, pred, clusters, order):
    d = pd.DataFrame({"c": clusters, **confusion_arrays(y, pred)}).groupby("c", sort=False).sum()
    return d.reindex(order)[["tp", "fp", "tn", "fn"]].values.astype(float)


def confusion_arrays(y, pred):
    y, pred = np.asarray(y), np.asarray(pred)
    return {"tp": (y == 1) & (pred == 1), "fp": (y == 0) & (pred == 1),
            "tn": (y == 0) & (pred == 0), "fn": (y == 1) & (pred == 0)}


def ci95(samples):
    s = np.asarray(samples, dtype=float)
    s = s[~np.isnan(s)]
    return [float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))] if len(s) else None


def bootstrap_count_metrics(y, pred, clusters, weights, order):
    counts = _per_cluster_counts(y, pred, clusters, order)
    return _rates(*(weights @ counts).T)


def paired_difference(y, pred_a, pred_b, clusters, B=10_000, seed=2026, metric="mcc"):
    """Paired cluster bootstrap of metric(a) - metric(b). Improvement claimed only if CI excludes 0."""
    w, order = cluster_weights(clusters, B, seed)
    a = bootstrap_count_metrics(y, pred_a, clusters, w, order)[metric]
    b = bootstrap_count_metrics(y, pred_b, clusters, w, order)[metric]
    pa, pb = detection_metrics(y, pred_a)[metric], detection_metrics(y, pred_b)[metric]
    ci = ci95(a - b)
    return {"metric": metric, "a": pa, "b": pb, "difference": pa - pb, "ci95": ci,
            "ci_excludes_zero": bool(ci and (ci[0] > 0 or ci[1] < 0))}


def bootstrap_score_metric(y, score, clusters, fn, B=2_000, seed=2026):
    """Generic (slower) cluster bootstrap for score-based metrics such as AUROC / AP."""
    y, score, clusters = np.asarray(y), np.asarray(score), np.asarray(clusters)
    uniq = pd.unique(clusters)
    idx_by = {c: np.flatnonzero(clusters == c) for c in uniq}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        idx = np.concatenate([idx_by[c] for c in rng.choice(uniq, size=len(uniq), replace=True)])
        if len(np.unique(y[idx])) < 2:
            out.append(np.nan)
            continue
        out.append(fn(y[idx], score[idx]))
    return ci95(out)


# ---------------------------------------------------------------- ranking
def _blocks(scores, is_correct):
    """Tie blocks in descending score order: list of (size, n_correct)."""
    d = pd.DataFrame({"s": scores, "c": is_correct}).groupby("s", sort=True)["c"].agg(["size", "sum"])
    return [(int(r["size"]), int(r["sum"])) for _, r in d.iloc[::-1].iterrows()]


def expected_top_n_success(scores, is_correct, n):
    p_none, filled = 1.0, 0
    for size, k in _blocks(scores, is_correct):
        if filled >= n:
            break
        slots = min(size, n - filled)
        if slots == size:
            if k > 0:
                return 1.0
        else:
            p_none *= comb(size - k, slots) / comb(size, slots)
        filled += slots
    return 1.0 - p_none


def expected_reciprocal_rank(scores, is_correct):
    start = 1
    for size, k in _blocks(scores, is_correct):
        if k > 0:
            total = comb(size, k)
            return sum(comb(size - j, k - 1) / total / (start + j - 1) for j in range(1, size - k + 2))
        start += size
    return 0.0


def ranking_table(df, score_col, bug_col="bug_id", label_col="y"):
    """Per bug with >= 2 candidates. label y: 1 overfitting, 0 correct. score: higher = more likely correct."""
    rows = []
    for bug, g in df.groupby(bug_col):
        if len(g) < 2:
            continue
        correct = (g[label_col].values == 0).astype(int)
        s = g[score_col].values
        rows.append({"bug_id": bug, "n_candidates": len(g), "n_correct": int(correct.sum()),
                     "p_at_1": expected_top_n_success(s, correct, 1),
                     "top3": expected_top_n_success(s, correct, 3),
                     "rr": expected_reciprocal_rank(s, correct),
                     "random_p_at_1": correct.mean()})
    return pd.DataFrame(rows)


def ranking_summary(table, B=10_000, seed=2026):
    def summarize(t):
        if t.empty:
            return {"bugs": 0}
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(t), size=(B, len(t)))
        return {"bugs": int(len(t)), "precision_at_1": float(t.p_at_1.mean()),
                "precision_at_1_ci95": ci95(t.p_at_1.values[idx].mean(1)),
                "mrr": float(t.rr.mean()), "top3": float(t.top3.mean()),
                "random_expected_p_at_1": float(t.random_p_at_1.mean())}
    conditional = table[table.n_correct >= 1]
    return {"conditional": summarize(conditional),
            "end_to_end": {**summarize(table),
                           "theoretical_max_p_at_1": float((table.n_correct >= 1).mean()) if len(table) else None}}
