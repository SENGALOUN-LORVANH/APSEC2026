"""Terminal tool for collecting REAL pairwise preferences from human raters.

  python preference_tool/collect.py --rater R1

Shows, for each planned comparison assigned to the rater: failing tests + failure messages (bug context) and the
two candidate diffs (normalized). Never shows labels, APR tools, filenames/patch ids, PVS, or model judgements.
All displayed text passes the leakage guard. Answers are appended to preference_tool/preferences.jsonl.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import leakage_guard  # noqa: E402

OUT = ROOT / "preference_tool" / "preferences.jsonl"
CRITERIA = ("correctness", "readability", "minimality", "security")


def render_task(bug_context, diff_a, diff_b):
    return (f"{'=' * 78}\nBUG CONTEXT\n{bug_context}\n\n{'-' * 78}\nPATCH A\n{diff_a}\n\n{'-' * 78}\nPATCH B\n"
            f"{diff_b}\n{'=' * 78}\nWhich patch would you prefer as the repair for this bug?")


def guarded_display_text(row, manifest, trigger, known_tools):
    diffs = {}
    for side in ("patch_A", "patch_B"):
        meta = manifest.loc[row[side]].to_dict() | {"patch_id": row[side]}
        diffs[side] = (ROOT / meta["normalized_patch_location"]).read_text()
    info = trigger.get(row["bug_id"], {"tests": [], "messages": []})
    context = "Failing tests:\n" + "\n".join(info["tests"]) + "\n\nFailure messages:\n" + "\n\n".join(
        m[:2000] for m in info["messages"])[:8000]
    text = render_task(context, diffs["patch_A"], diffs["patch_B"])
    for side in ("patch_A", "patch_B"):
        meta = manifest.loc[row[side]].to_dict() | {"patch_id": row[side]}
        leakage_guard.check_request(text, meta, known_tools, purpose="preference_display")
    return text


def ask(prompt, valid):
    while True:
        ans = input(prompt).strip().upper()
        if ans in valid:
            return ans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rater", required=True)
    ap.add_argument("--plan", default=str(ROOT / "preference_tool" / "plan.csv"))
    args = ap.parse_args()
    plan = pd.read_csv(args.plan)
    manifest = pd.read_csv(ROOT / "data" / "dataset_manifest.csv", keep_default_na=False).set_index("patch_id")
    trig_path = ROOT / "data" / "trigger_tests.json"
    trigger = json.loads(trig_path.read_text())["bugs"] if trig_path.exists() else {}
    known_tools = sorted(set(manifest.APR_tool))
    done = set()
    if OUT.exists():
        done = {(r["rater_id"], r["pair_id"]) for r in map(json.loads, OUT.read_text().splitlines())}
    todo = plan[(plan.rater_id == args.rater) & ~plan.pair_id.map(lambda p: (args.rater, p) in done)]
    print(f"{len(todo)} comparisons remaining for {args.rater}")
    for _, row in todo.iterrows():
        print(guarded_display_text(row, manifest, trigger, known_tools))
        pref = ask("Prefer [A] / [B] / [T]ie: ", {"A", "B", "T"})
        scores = {}
        if ask("Rate criteria 1-5 for both patches? [Y/N]: ", {"Y", "N"}) == "Y":
            for c in CRITERIA:
                scores[c] = {s: int(ask(f"  {c} for patch {s} (1-5): ", {"1", "2", "3", "4", "5"})) for s in "AB"}
        rec = {"rater_id": args.rater, "pair_id": row.pair_id, "bug_id": row.bug_id, "patch_A": row.patch_A,
               "patch_B": row.patch_B, "preference": {"A": "A", "B": "B", "T": "tie"}[pref],
               "criterion_scores": scores, "timestamp": datetime.now(timezone.utc).isoformat()}
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    main()
