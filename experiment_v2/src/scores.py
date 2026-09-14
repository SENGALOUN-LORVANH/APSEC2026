"""Component scores S_sem, S_cex, S_edit, S_vuln (definitions: protocol/protocol.yaml § scores)."""
import math
from collections import Counter

VALID_BUG_REVEALING = "VALID_BUG_REVEALING"


# ---------------------------------------------------------------- S_sem
def s_sem_run(judgement: str, confidence: float):
    """-> (S_sem for one run, clipped?). S_sem is the probability-like score that the patch is CORRECT."""
    if judgement not in ("CORRECT", "OVERFITTING"):
        raise ValueError(f"invalid judgement {judgement!r}")
    c = float(confidence)
    if math.isnan(c):
        raise ValueError("confidence is NaN")
    clipped = not 0.0 <= c <= 1.0
    c = min(max(c, 0.0), 1.0)
    return (c if judgement == "CORRECT" else 1.0 - c), clipped


def s_sem_final(run_values):
    """Mean over runs; decision CORRECT iff >= 0.5 (fixed threshold). Empty -> (None, None)."""
    vals = [v for v in run_values if v is not None]
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    return m, ("CORRECT" if m >= 0.5 else "OVERFITTING")


def run_stability(judgements):
    """Fraction of runs agreeing with the modal judgement."""
    if not judgements:
        return None
    return Counter(judgements).most_common(1)[0][1] / len(judgements)


# ---------------------------------------------------------------- S_cex
def s_cex(tests):
    """tests: iterable of {"status": str, "candidate_pass": bool|None}.

    Only VALID_BUG_REVEALING tests count. Candidate TIMEOUT / missing result counts as not passed.
    -> (S_cex or None when no valid test, n_valid, n_passed)
    """
    valid = [t for t in tests if t["status"] == VALID_BUG_REVEALING]
    if not valid:
        return None, 0, 0
    passed = sum(1 for t in valid if t.get("candidate_pass") is True)
    return passed / len(valid), len(valid), passed


def counterexample_status(compiled: bool, fixed_runs, buggy_runs):
    """Classify one generated test. *_runs: list of "PASS" | "FAIL" | "TIMEOUT" over repetitions."""
    if not compiled:
        return "INVALID_COMPILE"
    if "TIMEOUT" in fixed_runs or "TIMEOUT" in buggy_runs:
        return "TIMEOUT"
    if len(set(fixed_runs)) > 1 or len(set(buggy_runs)) > 1:
        return "FLAKY"
    if fixed_runs[0] != "PASS":
        return "INVALID_ORACLE"
    return VALID_BUG_REVEALING if buggy_runs[0] == "FAIL" else "VALID_NON_DISCRIMINATING"


# ---------------------------------------------------------------- S_edit
def s_edit(ast_actions=None, ast_nodes=None, changed_exec_loc=None, method_exec_loc=None):
    """-> (S_edit in [0,1] or None, method) — AST ratio preferred, LOC ratio fallback."""
    if ast_actions is not None and ast_nodes:
        return min(1.0, ast_actions / ast_nodes), "ast"
    if changed_exec_loc is not None and method_exec_loc:
        return min(1.0, changed_exec_loc / method_exec_loc), "loc"
    return None, "unavailable"


# ---------------------------------------------------------------- S_vuln
def severity_from_rank(rank: int, mapping) -> str:
    for sev, (lo, hi) in mapping.items():
        if lo <= rank <= hi:
            return sev
    raise ValueError(f"rank {rank} not covered by severity mapping")


def new_warnings(buggy_keys, candidate_keys):
    """Multiset difference candidate - buggy on warning identity keys (line numbers excluded by caller)."""
    diff = Counter(candidate_keys) - Counter(buggy_keys)
    return list(diff.elements())


def s_vuln(new_warning_severities, weights):
    """min(1, sum of severity weights). Analyzer failure must be passed as None by the caller, not []."""
    if new_warning_severities is None:
        return None
    return min(1.0, sum(weights[s] for s in new_warning_severities))
