"""Fold Stage 2B outputs into patch_scores.csv (Step 6): S_edit becomes GumTree AST (primary), with the LOC
value preserved as S_edit_loc (sensitivity); S_vuln becomes the changed-class SpotBugs value. Recomputes PVS*
(placeholder weights, shifted_renormalized). Protocol fallback preserved: if GumTree S_edit is missing, keep
the LOC value. Analyzer-missing S_vuln stays missing (None), never 0.
"""
import csv
from pathlib import Path

import pvs as pvs_module

ROOT = Path(__file__).resolve().parents[1]
PATCH_SCORES = ROOT / "results" / "patch_scores.csv"
STAGE2B = ROOT / "results" / "stage2b_features.csv"
WEIGHTS = {"alpha": 0.25, "beta": 0.25, "gamma": 0.25, "delta": 0.25}
PVS_KEYS = ["S_sem", "S_cex", "S_edit", "S_vuln", "alpha", "beta", "gamma", "delta",
            "PVS", "PVS_strategy", "PVS_paper_formula_complete_only", "missing_component_flags"]


def _f(v):
    return float(v) if v not in (None, "", "None") else None


def main():
    with open(STAGE2B, newline="", encoding="utf-8") as f:
        s2b = {r["patch_id"]: r for r in csv.DictReader(f)}
    with open(PATCH_SCORES, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []
    if "S_edit_loc" not in fields:
        fields = fields + ["S_edit_loc"]

    changed = 0
    for row in rows:
        st = s2b.get(row["patch_id"])
        if not st:
            row.setdefault("S_edit_loc", row.get("S_edit"))
            continue
        loc_val = _f(row["S_edit"])          # current value is the LOC S_edit
        ast_val = _f(st.get("s_edit_ast"))   # GumTree primary
        row["S_edit_loc"] = loc_val
        s_edit = ast_val if ast_val is not None else loc_val
        s_edit_method = "ast" if ast_val is not None else ("loc" if loc_val is not None else "unavailable")
        s_vuln = _f(st.get("s_vuln_changed"))  # changed-class scope; None => MISSING (kept missing)
        comps = {"S_sem": _f(row["S_sem"]), "S_cex": _f(row["S_cex"]), "S_edit": s_edit, "S_vuln": s_vuln}
        rescored = pvs_module.score_row(row["patch_id"], comps, WEIGHTS, "shifted_renormalized")
        for k in PVS_KEYS:
            row[k] = rescored[k]
        row["S_edit_method"] = s_edit_method
        row["S_vuln_new_warning_count"] = st.get("s_vuln_new_warning_count", row.get("S_vuln_new_warning_count"))
        changed += 1

    with open(PATCH_SCORES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"updated {changed}/{len(rows)} rows with Stage 2B S_edit(ast)/S_vuln(changed-class); PVS* recomputed")


if __name__ == "__main__":
    main()
