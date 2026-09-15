"""Pre-defined preference sampling plan (DRAFT design; authors approve before any collection).

Design (draft): 240 ratings from 3 raters = 80 per rater. 20 pairs are rated by all three raters (inter-rater
agreement); the remaining 180 ratings are 180 distinct pairs split evenly. Distinct pairs = 200.
Pairs are drawn within bugs that have >= 2 included candidates (primary policy), stratified by project, pair type
(correct-overfitting / overfitting-overfitting / correct-correct, from ground-truth labels used ONLY for sampling),
and patch-size bucket of the pair. Seed fixed; no information about any method's scores is used.

Output: preference_tool/plan.csv (pair_id, rater_id, bug_id, patch_A, patch_B, stratum). Raters never see
labels, tools, filenames, or scores — only bug context and the two diffs (see collect.py).
"""
import argparse
import csv
import itertools
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RATERS = ("R1", "R2", "R3")


def size_bucket(n_changed):
    return "small" if n_changed <= 2 else ("medium" if n_changed <= 6 else "large")


def candidate_pairs(manifest, audit):
    m = manifest[manifest.included_primary.astype(str) == "True"].merge(
        audit[["patch_id", "normalized_changed_lines"]], on="patch_id")
    rows = []
    for bug, g in m.groupby("bug_id"):
        if len(g) < 2:
            continue
        for a, b in itertools.combinations(g.sort_values("patch_id").itertuples(), 2):
            if a.duplicate_group_id and a.duplicate_group_id == b.duplicate_group_id:
                continue  # identical diffs are not a meaningful comparison
            labels = sorted([a.ground_truth_label, b.ground_truth_label])
            ptype = {("correct", "overfitting"): "C-O", ("overfitting", "overfitting"): "O-O",
                     ("correct", "correct"): "C-C"}[tuple(labels)]
            size = size_bucket(max(a.normalized_changed_lines, b.normalized_changed_lines))
            rows.append({"bug_id": bug, "project": a.project, "patch_A": a.patch_id, "patch_B": b.patch_id,
                         "stratum": f"{a.project}|{ptype}|{size}"})
    return pd.DataFrame(rows)


def make_plan(pairs, n_distinct=200, n_shared=20, seed=2026):
    rng = np.random.default_rng(seed)
    by_stratum = {s: g.sample(frac=1, random_state=int(rng.integers(1 << 31))) for s, g in pairs.groupby("stratum")}
    # Round-robin over strata -> balanced coverage; within a stratum prefer distinct bugs first.
    chosen, used_bugs = [], defaultdict(int)
    iters = {s: iter(g.itertuples(index=False)) for s, g in sorted(by_stratum.items())}
    while len(chosen) < n_distinct and iters:
        for s in list(iters):
            try:
                row = next(iters[s])
            except StopIteration:
                del iters[s]
                continue
            chosen.append(row._asdict())
            used_bugs[row.bug_id] += 1
            if len(chosen) == n_distinct:
                break
    chosen = pd.DataFrame(chosen).reset_index(drop=True)
    chosen.insert(0, "pair_id", [f"P{i:03d}" for i in range(len(chosen))])
    order = rng.permutation(len(chosen))
    shared, rest = order[:n_shared], order[n_shared:]
    plan = [{"rater_id": r, **chosen.iloc[i].to_dict()} for i in shared for r in RATERS]
    for j, i in enumerate(rest):
        plan.append({"rater_id": RATERS[j % len(RATERS)], **chosen.iloc[i].to_dict()})
    plan = pd.DataFrame(plan)
    # Randomize A/B presentation side per rating.
    flip = rng.random(len(plan)) < 0.5
    plan.loc[flip, ["patch_A", "patch_B"]] = plan.loc[flip, ["patch_B", "patch_A"]].values
    return plan.sample(frac=1, random_state=seed).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "preference_tool" / "plan.csv"))
    args = ap.parse_args()
    manifest = pd.read_csv(ROOT / "data" / "dataset_manifest.csv", keep_default_na=False)
    audit = pd.read_csv(ROOT / "results" / "normalization_audit.csv")
    pairs = candidate_pairs(manifest, audit)
    plan = make_plan(pairs)
    plan.to_csv(args.out, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"candidate pairs: {len(pairs)}; ratings planned: {len(plan)}; distinct pairs: {plan.pair_id.nunique()}")
    print(plan.groupby("rater_id").size().to_dict())


if __name__ == "__main__":
    main()
