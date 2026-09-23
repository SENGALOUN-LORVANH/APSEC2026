"""Context-condition ablation (work order B1) on the 48 pilot patches, claude-haiku-4-5, 3 runs each.

The pilot's primary results are condition C (full context: failing tests + failure messages + extracted
changed-method/signature/class context). This runs the two pre-registered leaner conditions on the SAME 48
patches so A/B/C can be compared side by side:
  A = candidate diff + patch metadata only (no failing tests, no failure messages, no extracted context)
  B = A + failing-test names + failure messages (no extracted code context)
  C = B + extracted context  (already computed during the pilot -> results/semantic_runs/<patch>.json)

Condition-A/B results are written to results/context_ablation/<patch_id>__<cond>.json and NEVER touch the
shared semantic_results.csv (which holds the primary condition-C result PVS* is assembled from), mirroring the
model-comparison pattern. --summarize then reads A, B, and the pilot's C and reports the per-condition M3
detection metrics (positive class = overfitting, predict overfitting iff s_sem_final < 0.5).

Usage (run inside the qc-v2 container; --summarize is pure and runs in the venv):
  python src/context_ablation.py --run                 # A and B for all 48, 3 runs each
  python src/context_ablation.py --run --only P1,P2    # subset
  python src/context_ablation.py --summarize           # write results/context_ablation_summary.json
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
SEMANTIC_RUNS_C = ROOT / "results" / "semantic_runs"          # pilot condition-C results
ABLATION_DIR = ROOT / "results" / "context_ablation"
SUMMARY = ROOT / "results" / "context_ablation_summary.json"
MODEL = "claude-haiku-4-5"
CONDITIONS = ("A", "B")


def pilot_patch_ids():
    """The 48 patches with a condition-C semantic result (the ones actually scored in the pilot)."""
    return sorted(p.stem for p in SEMANTIC_RUNS_C.glob("*.json"))


def run(only):
    import semantic
    ABLATION_DIR.mkdir(parents=True, exist_ok=True)
    patch_ids = pilot_patch_ids()
    if only:
        only_set = set(only)
        patch_ids = [p for p in patch_ids if p in only_set]
    print(f"context ablation: {len(patch_ids)} patches x {len(CONDITIONS)} conditions", flush=True)
    for pid in patch_ids:
        for cond in CONDITIONS:
            out = ABLATION_DIR / f"{pid}__{cond}.json"
            if out.exists() and json.loads(out.read_text()).get("n_parsed"):
                print(f"  skip {pid} [{cond}] (done)", flush=True)
                continue
            result = semantic.run_semantic(pid, cond, MODEL)
            out.write_text(json.dumps(result, indent=2, default=str))
            print(json.dumps({"patch_id": pid, "condition": cond, "s_sem_final": result["s_sem_final"],
                              "decision": result["decision"], "n_parsed": result["n_parsed"]}, default=str),
                  flush=True)


def _labels():
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return {r["patch_id"]: (r["ground_truth_label"], r["project"], r["bug_id"]) for r in csv.DictReader(f)}


def _s_sem_c(pid):
    d = json.loads((SEMANTIC_RUNS_C / f"{pid}.json").read_text())
    return d.get("s_sem_final")


def _s_sem_ab(pid, cond):
    p = ABLATION_DIR / f"{pid}__{cond}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("s_sem_final")


def summarize():
    import metrics
    labels = _labels()
    patch_ids = pilot_patch_ids()
    per_cond = {}
    for cond in ("A", "B", "C"):
        y, pred, score, pids = [], [], [], []
        for pid in patch_ids:
            gt = labels.get(pid, (None,))[0]
            if gt not in ("overfitting", "correct"):
                continue
            s = _s_sem_c(pid) if cond == "C" else _s_sem_ab(pid, cond)
            if s is None:
                continue
            y.append(1 if gt == "overfitting" else 0)
            pred.append(1 if s < 0.5 else 0)          # M3 rule
            score.append(1.0 - s)                      # overfitting-likelihood proxy for AUROC
            pids.append(pid)
        m = metrics.detection_metrics(y, pred, score) if y else {}
        m["n_scored"] = len(y)
        per_cond[cond] = m
    out = {"NOTE": "PRELIMINARY ENGINEERING PILOT -- context ablation on 48 patches, M3 rule (S_sem<0.5), "
                   "positive class = overfitting. Condition C is the pilot's primary result.",
           "model": MODEL, "rule": "predict overfitting iff s_sem_final < 0.5",
           "conditions": per_cond}
    SUMMARY.write_text(json.dumps(out, indent=2, default=str))
    for cond in ("A", "B", "C"):
        m = per_cond[cond]
        print(f"[{cond}] n={m.get('n_scored')} F1={m.get('f1'):.3f} MCC={m.get('mcc'):.3f} "
              f"prec={m.get('precision'):.3f} rec={m.get('recall'):.3f} "
              f"AUROC={m.get('auroc')} retention={m.get('correct_patch_retention'):.3f} "
              f"conf={m.get('confusion')}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    if args.run:
        run([s for s in args.only.split(",") if s.strip()] if args.only else None)
    if args.summarize:
        summarize()
    if not (args.run or args.summarize):
        ap.error("choose --run and/or --summarize")


if __name__ == "__main__":
    main()
