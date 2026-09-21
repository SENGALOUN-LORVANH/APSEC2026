"""Recompute PVS* rows after the semantic reruns (Step 2) without re-running SpotBugs/context.

Only S_sem changed (from the credit-failed reruns); S_cex, S_edit, S_vuln are LLM-independent and already
recorded in patch_scores.csv, so they are carried forward unchanged. S_sem is re-read from the authoritative
semantic_results.csv. Applies the S_sem-missing PVS* guard (pvs.score_row) uniformly to every row.
"""
import csv
from pathlib import Path

import pvs as pvs_module

ROOT = Path(__file__).resolve().parents[1]
PATCH_SCORES = ROOT / "results" / "patch_scores.csv"
SEMANTIC_RESULTS = ROOT / "results" / "semantic_results.csv"
WEIGHTS = {"alpha": 0.25, "beta": 0.25, "gamma": 0.25, "delta": 0.25}
STRATEGY = "shifted_renormalized"
PVS_KEYS = ["S_sem", "S_cex", "S_edit", "S_vuln", "alpha", "beta", "gamma", "delta",
            "PVS", "PVS_strategy", "PVS_paper_formula_complete_only", "missing_component_flags"]


def _f(v):
    return float(v) if v not in (None, "", "None") else None


def main():
    with open(SEMANTIC_RESULTS, newline="", encoding="utf-8") as f:
        sem = {r["patch_id"]: _f(r["s_sem_final"]) for r in csv.DictReader(f)}
    with open(PATCH_SCORES, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = rows[0].keys() if rows else []

    changed = 0
    for row in rows:
        pid = row["patch_id"]
        new_s_sem = sem.get(pid, _f(row["S_sem"]))
        comps = {"S_sem": new_s_sem, "S_cex": _f(row["S_cex"]),
                 "S_edit": _f(row["S_edit"]), "S_vuln": _f(row["S_vuln"])}
        rescored = pvs_module.score_row(pid, comps, WEIGHTS, STRATEGY)
        before = (row.get("S_sem"), row.get("PVS"))
        for k in PVS_KEYS:
            row[k] = rescored[k]
        if (str(before[0]), str(before[1])) != (str(row["S_sem"]), str(row["PVS"])):
            changed += 1
            print(f"  rescored {pid}: S_sem {before[0]} -> {row['S_sem']}, PVS {before[1]} -> {row['PVS']}")

    with open(PATCH_SCORES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fieldnames))
        w.writeheader()
        w.writerows(rows)
    print(f"rescored rows changed: {changed} / {len(rows)}")


if __name__ == "__main__":
    main()
