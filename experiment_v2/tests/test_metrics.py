import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import metrics as m  # noqa: E402


def toy(n_bugs=40, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for b in range(n_bugs):
        proj = m.PROJECTS[b % 5]
        for p in range(rng.integers(1, 5)):
            rows.append({"patch_id": f"{proj}-{b}-{p}", "bug_id": f"{proj}-{b}", "project": proj,
                         "y": int(rng.random() < 0.7)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- detection
def test_all_overfitting_classifier_has_zero_retention_and_mcc():
    y = np.array([1] * 7 + [0] * 3)
    r = m.detection_metrics(y, np.ones(10, dtype=int), score=np.ones(10))
    assert r["f1"] == pytest.approx(14 / 17)
    assert r["correct_patch_retention"] == 0.0 and r["mcc"] == 0.0
    assert r["balanced_accuracy"] == 0.5 and r["auroc"] is None


def test_perfect_classifier():
    y = np.array([1, 1, 0, 0])
    r = m.detection_metrics(y, y, score=np.array([0.9, 0.8, 0.1, 0.2]))
    assert r["mcc"] == 1.0 and r["macro_f1"] == 1.0 and r["auroc"] == 1.0 and r["average_precision"] == 1.0


# ---------------------------------------------------------------- splits
def test_lopo_has_no_project_leakage():
    df = toy()
    folds = list(m.lopo_splits(df))
    assert [f[0] for f in folds] == sorted(df.project.unique())
    for _, tr, te in folds:
        m.assert_disjoint(df, tr, te, "project")
        m.assert_disjoint(df, tr, te, "bug_id")


def test_groupkfold_isolates_bugs_and_covers_all():
    df = toy()
    seen = []
    for _, tr, te in m.groupkfold_splits(df, seed=2026):
        m.assert_disjoint(df, tr, te, "bug_id")
        seen += list(te)
    assert sorted(seen) == list(range(len(df)))


def test_assert_disjoint_raises_on_leak():
    df = toy()
    with pytest.raises(AssertionError):
        m.assert_disjoint(df, np.arange(len(df)), np.arange(3), "bug_id")


def test_fold_assignments_has_both_splits():
    fa = m.fold_assignments(toy())
    assert set(fa.split) == {"LOPO", "GroupKFold"}


# ---------------------------------------------------------------- bootstrap
def test_cluster_weights_resample_clusters():
    w, order = m.cluster_weights(["a", "a", "b", "c"], B=50, seed=1)
    assert w.shape == (50, 3) and (w.sum(1) == 3).all() and list(order) == ["a", "b", "c"]


def test_paired_difference_identical_methods_is_zero():
    df = toy()
    pred = (np.arange(len(df)) % 2).astype(int)
    r = m.paired_difference(df.y.values, pred, pred, df.bug_id.values, B=200)
    assert r["difference"] == 0 and r["ci95"] == [0.0, 0.0] and not r["ci_excludes_zero"]


def test_paired_difference_detects_clear_improvement():
    df = toy(200)
    y = df.y.values
    r = m.paired_difference(y, y, 1 - y, df.bug_id.values, B=500)
    assert r["difference"] == pytest.approx(2.0) and r["ci_excludes_zero"]


# ---------------------------------------------------------------- ranking
def test_top1_ties_are_expected_values():
    assert m.expected_top_n_success([0.9, 0.9, 0.1], [1, 0, 0], 1) == pytest.approx(0.5)
    assert m.expected_top_n_success([0.9, 0.5, 0.1], [0, 0, 1], 1) == 0.0
    assert m.expected_top_n_success([0.9, 0.5, 0.1], [0, 0, 1], 3) == 1.0
    # 4 tied, 1 correct, top-3 -> 3/4
    assert m.expected_top_n_success([0.5] * 4, [1, 0, 0, 0], 3) == pytest.approx(0.75)


def test_expected_reciprocal_rank():
    assert m.expected_reciprocal_rank([0.9, 0.5], [0, 1]) == pytest.approx(0.5)
    # two tied, one correct: 0.5*1 + 0.5*(1/2)
    assert m.expected_reciprocal_rank([0.5, 0.5], [1, 0]) == pytest.approx(0.75)
    assert m.expected_reciprocal_rank([0.5, 0.4], [0, 0]) == 0.0


def test_conditional_vs_end_to_end_precision_at_1():
    df = pd.DataFrame({
        "bug_id": ["b1", "b1", "b2", "b2", "b3"],
        "y": [0, 1, 1, 1, 0],               # b1 has a correct patch, b2 none, b3 single candidate (ignored)
        "score": [0.9, 0.1, 0.8, 0.2, 0.5]})
    t = m.ranking_table(df, "score")
    s = m.ranking_summary(t, B=100)
    assert s["conditional"]["bugs"] == 1 and s["conditional"]["precision_at_1"] == 1.0
    assert s["end_to_end"]["bugs"] == 2 and s["end_to_end"]["precision_at_1"] == 0.5
    assert s["end_to_end"]["theoretical_max_p_at_1"] == 0.5
