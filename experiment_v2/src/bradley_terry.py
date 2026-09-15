"""Bradley-Terry calibration of PVS* weights from REAL human pairwise preferences.

Model: P(A preferred over B) = sigmoid(lambda * (PVS*_A(w) - PVS*_B(w)))
  w = (alpha, beta, gamma, delta) on the simplex (w >= 0, sum = 1), lambda >= 0 (scale).
  PVS* uses the protocol's normalized, missing-aware form (pvs.pvs_shifted_renormalized), so calibration and
  ranking use exactly the same score.
Ties ("no preference") are excluded from the likelihood and counted.
Fold rule: weights for a LOPO test project are fitted ONLY on preference pairs from the other projects.

No preferences exist yet. Never fit this on simulated or LLM-generated "preferences" for reported results.
"""
import numpy as np
from scipy.optimize import minimize

import pvs

WEIGHT_NAMES = ("alpha", "beta", "gamma", "delta")


def _weights_from(theta):
    e = np.exp(theta - theta.max())
    w = e / e.sum()
    return dict(zip(WEIGHT_NAMES, w))


def _pvs(components, w):
    v = pvs.pvs_shifted_renormalized(components, w)
    return np.nan if v is None else v


def negative_log_likelihood(params, pairs):
    w = _weights_from(params[:4])
    lam = np.exp(params[4])
    nll = 0.0
    for a, b, pref in pairs:
        d = _pvs(a, w) - _pvs(b, w)
        if np.isnan(d):
            continue
        z = lam * d if pref == "A" else -lam * d
        nll += np.logaddexp(0.0, -z)
    return nll


def fit(pairs, seed=2026, restarts=5):
    """pairs: list of (components_A, components_B, preference in {'A','B','tie'}). -> result dict."""
    usable = [(a, b, p) for a, b, p in pairs if p in ("A", "B")]
    ties = sum(1 for *_, p in pairs if p == "tie")
    if not usable:
        return {"weights": None, "scale": None, "n_pairs": 0, "n_ties": ties, "status": "NO_DATA"}
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        x0 = np.concatenate([rng.normal(0, 0.5, 4), [np.log(5.0)]])
        res = minimize(negative_log_likelihood, x0, args=(usable,), method="L-BFGS-B")
        if best is None or res.fun < best.fun:
            best = res
    w = _weights_from(best.x[:4])
    return {"weights": {k: float(v) for k, v in w.items()}, "scale": float(np.exp(best.x[4])),
            "nll": float(best.fun), "n_pairs": len(usable), "n_ties": ties,
            "status": "OK" if best.success else f"OPTIMIZER:{best.message}"}


def fit_lopo(preference_rows, projects):
    """preference_rows: dicts with keys project, components_A, components_B, preference.
    -> {held_out_project: fit result using only the other projects' pairs}."""
    out = {}
    for held_out in projects:
        train = [(r["components_A"], r["components_B"], r["preference"])
                 for r in preference_rows if r["project"] != held_out]
        res = fit(train)
        res["training_projects"] = sorted({r["project"] for r in preference_rows if r["project"] != held_out})
        out[held_out] = res
    return out
