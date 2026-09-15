"""Bradley-Terry tests use SYNTHETIC preferences only to verify the estimator; they are never results."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import bradley_terry as bt  # noqa: E402
import pvs  # noqa: E402


def simulate(true_w, n=600, scale=12.0, seed=1, missing_cex_rate=0.0):
    rng = np.random.default_rng(seed)
    pairs = []
    for _ in range(n):
        a = {k: float(rng.random()) for k in pvs.COMPONENTS}
        b = {k: float(rng.random()) for k in pvs.COMPONENTS}
        if rng.random() < missing_cex_rate:
            a["S_cex"] = None
        d = pvs.pvs_shifted_renormalized(a, true_w) - pvs.pvs_shifted_renormalized(b, true_w)
        pairs.append((a, b, "A" if rng.random() < 1 / (1 + np.exp(-scale * d)) else "B"))
    return pairs


def test_recovers_weights_on_simplex():
    true_w = {"alpha": 0.5, "beta": 0.3, "gamma": 0.15, "delta": 0.05}
    res = bt.fit(simulate(true_w, n=1500))
    w = res["weights"]
    assert sum(w.values()) == pytest.approx(1.0) and all(v >= 0 for v in w.values())
    for k in true_w:
        assert w[k] == pytest.approx(true_w[k], abs=0.08)


def test_handles_missing_s_cex_and_ties():
    true_w = {"alpha": 0.4, "beta": 0.4, "gamma": 0.1, "delta": 0.1}
    pairs = simulate(true_w, n=400, missing_cex_rate=0.3) + [({}, {}, "tie")] * 5
    res = bt.fit(pairs)
    assert res["n_ties"] == 5 and res["n_pairs"] == 400 and res["weights"] is not None


def test_no_data():
    assert bt.fit([])["status"] == "NO_DATA"


def test_lopo_never_uses_held_out_project_pairs():
    true_w = {"alpha": 0.25, "beta": 0.25, "gamma": 0.25, "delta": 0.25}
    rows = [{"project": p, "components_A": a, "components_B": b, "preference": pref}
            for p, chunk in zip(["Chart", "Lang", "Math"], np.array_split(np.arange(300), 3))
            for (a, b, pref) in [simulate(true_w, n=300, seed=3)[i] for i in chunk]]
    res = bt.fit_lopo(rows, ["Chart", "Lang", "Math"])
    for held_out, r in res.items():
        assert held_out not in r["training_projects"] and r["n_pairs"] == 200
