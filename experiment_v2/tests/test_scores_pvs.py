import itertools
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pvs  # noqa: E402
import scores as sc  # noqa: E402

W = {"alpha": 0.4, "beta": 0.3, "gamma": 0.2, "delta": 0.1}


# ---------------------------------------------------------------- S_sem
def test_s_sem_run_direction_and_clipping():
    assert sc.s_sem_run("CORRECT", 0.8) == (0.8, False)
    assert sc.s_sem_run("OVERFITTING", 0.8)[0] == pytest.approx(0.2)
    assert sc.s_sem_run("CORRECT", 1.4) == (1.0, True)
    with pytest.raises(ValueError):
        sc.s_sem_run("MAYBE", 0.5)


def test_s_sem_final_threshold_is_inclusive():
    assert sc.s_sem_final([0.5]) == (0.5, "CORRECT")
    assert sc.s_sem_final([0.3, 0.7, 0.55])[1] == "CORRECT"      # mean 0.517
    assert sc.s_sem_final([0.2, 0.7, 0.55])[1] == "OVERFITTING"  # mean 0.483
    assert sc.s_sem_final([0.2, 0.4, 0.8])[1] == "OVERFITTING"
    assert sc.s_sem_final([]) == (None, None)


def test_run_stability():
    assert sc.run_stability(["CORRECT", "CORRECT", "OVERFITTING"]) == pytest.approx(2 / 3)


# ---------------------------------------------------------------- counterexamples
@pytest.mark.parametrize("compiled,fixed,buggy,expected", [
    (False, [], [], "INVALID_COMPILE"),
    (True, ["FAIL"] * 3, ["FAIL"] * 3, "INVALID_ORACLE"),
    (True, ["PASS"] * 3, ["FAIL"] * 3, "VALID_BUG_REVEALING"),
    (True, ["PASS"] * 3, ["PASS"] * 3, "VALID_NON_DISCRIMINATING"),
    (True, ["PASS", "FAIL", "PASS"], ["FAIL"] * 3, "FLAKY"),
    (True, ["PASS"] * 3, ["FAIL", "TIMEOUT", "FAIL"], "TIMEOUT"),
])
def test_counterexample_status(compiled, fixed, buggy, expected):
    assert sc.counterexample_status(compiled, fixed, buggy) == expected


def test_s_cex_counts_only_valid_and_na_when_none():
    tests = [{"status": "VALID_BUG_REVEALING", "candidate_pass": True},
             {"status": "VALID_BUG_REVEALING", "candidate_pass": None},  # timeout -> not passed
             {"status": "VALID_NON_DISCRIMINATING", "candidate_pass": True},
             {"status": "INVALID_ORACLE", "candidate_pass": False}]
    assert sc.s_cex(tests) == (0.5, 2, 1)
    assert sc.s_cex([{"status": "INVALID_COMPILE"}]) == (None, 0, 0)


# ---------------------------------------------------------------- S_edit / S_vuln
def test_s_edit_prefers_ast_then_loc():
    assert sc.s_edit(ast_actions=3, ast_nodes=30) == (0.1, "ast")
    assert sc.s_edit(ast_actions=None, changed_exec_loc=5, method_exec_loc=2) == (1.0, "loc")
    assert sc.s_edit() == (None, "unavailable")


def test_new_warnings_multiset_and_s_vuln():
    buggy = [("NP", "A", "f()", "x"), ("NP", "A", "f()", "x")]
    cand = [("NP", "A", "f()", "x"), ("NP", "A", "f()", "x"), ("NP", "A", "f()", "x"), ("OS", "A", "g()", "")]
    new = sc.new_warnings(buggy, cand)
    assert sorted(new) == [("NP", "A", "f()", "x"), ("OS", "A", "g()", "")]
    weights = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.25}
    assert sc.s_vuln(["MEDIUM", "LOW"], weights) == 0.75
    assert sc.s_vuln(["HIGH", "HIGH"], weights) == 1.0
    assert sc.s_vuln([], weights) == 0.0
    assert sc.s_vuln(None, weights) is None
    assert sc.severity_from_rank(7, {"HIGH": [1, 4], "MEDIUM": [5, 9], "LOW": [10, 20]}) == "MEDIUM"


# ---------------------------------------------------------------- PVS
def test_weights_validated():
    with pytest.raises(ValueError):
        pvs.validate_weights({"alpha": 0.5, "beta": 0.5, "gamma": 0.1, "delta": 0.0})
    with pytest.raises(ValueError):
        pvs.validate_weights({"alpha": 1.1, "beta": -0.1, "gamma": 0.0, "delta": 0.0})


def test_paper_formula():
    c = {"S_sem": 0.9, "S_cex": 1.0, "S_edit": 0.1, "S_vuln": 0.0}
    assert pvs.pvs_paper(c, W) == pytest.approx(0.36 + 0.3 - 0.02)


def test_shifted_equals_paper_plus_constant_when_complete_and_same_ranking():
    rng = random.Random(2026)
    rows = [{k: rng.random() for k in pvs.COMPONENTS} for _ in range(200)]
    for c in rows:
        assert pvs.pvs_shifted_renormalized(c, W) == pytest.approx(pvs.pvs_paper(c, W) + W["gamma"] + W["delta"])
    order_paper = sorted(range(200), key=lambda i: pvs.pvs_paper(rows[i], W))
    order_shift = sorted(range(200), key=lambda i: pvs.pvs_shifted_renormalized(rows[i], W))
    assert order_paper == order_shift


def test_missing_s_cex_strategies():
    c = {"S_sem": 0.8, "S_cex": None, "S_edit": 0.2, "S_vuln": 0.0}
    assert pvs.pvs_paper(c, W) is None
    assert pvs.pvs_directive_renormalized(c, W) == pytest.approx((0.32 - 0.04) / 0.7)
    shifted = pvs.pvs_shifted_renormalized(c, W)
    assert shifted == pytest.approx((0.32 + 0.2 * 0.8 + 0.1 * 1.0) / 0.7)
    assert 0.0 <= shifted <= 1.0


def test_directive_strategy_does_not_impute_other_missing_components():
    assert pvs.pvs_directive_renormalized({"S_sem": 0.8, "S_cex": 1.0, "S_edit": None, "S_vuln": 0.0}, W) is None


def test_score_row_exports_all_components_and_flags():
    row = pvs.score_row("p1", {"S_sem": 0.8, "S_cex": None, "S_edit": 0.2, "S_vuln": 0.0}, W, "shifted_renormalized")
    for k in ("S_sem", "S_cex", "S_edit", "S_vuln", "alpha", "beta", "gamma", "delta", "PVS",
              "missing_component_flags"):
        assert k in row
    assert row["missing_component_flags"] == "S_cex"
    assert row["PVS_paper_formula_complete_only"] is None
    with pytest.raises(ValueError):
        pvs.score_row("p1", {"S_sem": 0.8, "S_cex": 1, "S_edit": 0.2, "S_vuln": 0.0}, W, "best_one")


def test_score_row_marks_pvs_missing_when_s_sem_missing():
    """PVS* is undefined without the semantic component (DEVIATIONS #4). Even though shifted_renormalized
    could compute a value from S_cex/S_edit/S_vuln, score_row must mark PVS missing."""
    row = pvs.score_row("p1", {"S_sem": None, "S_cex": 1.0, "S_edit": 0.2, "S_vuln": 0.0}, W, "shifted_renormalized")
    assert row["PVS"] is None
    assert "S_sem" in row["missing_component_flags"]
    # the raw strategy still computes from available components; only score_row applies the S_sem policy
    assert pvs.pvs_shifted_renormalized({"S_sem": None, "S_cex": 1.0, "S_edit": 0.2, "S_vuln": 0.0}, W) is not None
