"""Patch Validity Score.

PVS(p) = alpha*S_sem + beta*S_cex - gamma*S_edit - delta*S_vuln   (manuscript formula)

Missing-component strategies (the protocol freeze selects one; both are always computable for sensitivity):
  directive_renormalized  : only S_cex may be missing ->
                            (alpha*S_sem - gamma*S_edit - delta*S_vuln) / (alpha + gamma + delta)
  shifted_renormalized    : [alpha*S_sem + beta*S_cex + gamma*(1-S_edit) + delta*(1-S_vuln)] / sum(available weights)
                            == PVS + gamma + delta when complete and weights sum to 1 (same ranking).
Every component is exported; the final score is never stored alone.
"""
import math

COMPONENTS = ("S_sem", "S_cex", "S_edit", "S_vuln")
WEIGHT_OF = {"S_sem": "alpha", "S_cex": "beta", "S_edit": "gamma", "S_vuln": "delta"}
STRATEGIES = ("directive_renormalized", "shifted_renormalized")


def _missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def validate_weights(w, tol=1e-9):
    for k in ("alpha", "beta", "gamma", "delta"):
        if w[k] < 0:
            raise ValueError(f"weight {k} must be >= 0")
    if abs(sum(w[k] for k in ("alpha", "beta", "gamma", "delta")) - 1.0) > tol:
        raise ValueError("weights must sum to 1")


def pvs_paper(c, w):
    if any(_missing(c[k]) for k in COMPONENTS):
        return None
    return w["alpha"] * c["S_sem"] + w["beta"] * c["S_cex"] - w["gamma"] * c["S_edit"] - w["delta"] * c["S_vuln"]


def pvs_directive_renormalized(c, w):
    if any(_missing(c[k]) for k in ("S_sem", "S_edit", "S_vuln")):
        return None
    if not _missing(c["S_cex"]):
        return pvs_paper(c, w)
    denom = w["alpha"] + w["gamma"] + w["delta"]
    if denom == 0:
        return None
    return (w["alpha"] * c["S_sem"] - w["gamma"] * c["S_edit"] - w["delta"] * c["S_vuln"]) / denom


def pvs_shifted_renormalized(c, w):
    terms = {"S_sem": lambda v: v, "S_cex": lambda v: v, "S_edit": lambda v: 1.0 - v, "S_vuln": lambda v: 1.0 - v}
    avail = [k for k in COMPONENTS if not _missing(c[k])]
    denom = sum(w[WEIGHT_OF[k]] for k in avail)
    if not avail or denom == 0:
        return None
    return sum(w[WEIGHT_OF[k]] * terms[k](c[k]) for k in avail) / denom


def score_row(patch_id, components, weights, strategy):
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy}")
    validate_weights(weights)
    fn = pvs_directive_renormalized if strategy == "directive_renormalized" else pvs_shifted_renormalized
    flags = [k for k in COMPONENTS if _missing(components.get(k))]
    pvs_val = fn(components, weights)
    # PVS* is the Stage-1-anchored patch-validity/ranking score; it is undefined without the semantic
    # component. Never emit a PVS* for a patch whose S_sem is missing -- mark it missing instead. This is a
    # post-freeze correction (see protocol/DEVIATIONS.md); the un-guarded shifted_renormalized would otherwise
    # return a high PVS* from S_cex/S_edit/S_vuln alone, contradicting a missing semantic judgement.
    if _missing(components.get("S_sem")):
        pvs_val = None
    return {"patch_id": patch_id, **{k: components.get(k) for k in COMPONENTS}, **weights,
            "PVS": pvs_val, "PVS_strategy": strategy,
            "PVS_paper_formula_complete_only": pvs_paper(components, weights),
            "missing_component_flags": ";".join(flags)}
