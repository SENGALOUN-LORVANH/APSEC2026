"""Rerun the memorization-probe entries that failed with an API error (the 11 credit-balance
BadRequestError rows from the pilot, which predate the Step-2 credit top-up). A blank bug_number with an
EMPTY error is a genuine "not recognised" result and is left untouched; only rows with a non-empty error are
re-issued, so the diagnostic becomes a complete 48/48.

Usage (inside the qc-v2 container, so the environment matches the original probe run):
  python src/rerun_memorization_na.py            # rerun every errored row
  python src/rerun_memorization_na.py --dry-run  # list what would be rerun
"""
import argparse
import csv
import json
from pathlib import Path

import memorization

ROOT = Path(__file__).resolve().parents[1]
PROBE_RESULTS = ROOT / "results" / "memorization_probe.csv"


def errored_patch_ids():
    with open(PROBE_RESULTS, newline="", encoding="utf-8") as f:
        return [r["patch_id"] for r in csv.DictReader(f) if (r.get("error") or "").strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    patch_ids = errored_patch_ids()
    print(f"{len(patch_ids)} errored probe rows to rerun:", flush=True)
    for pid in patch_ids:
        print("  ", pid, flush=True)
    if args.dry_run:
        return

    for pid in patch_ids:
        result = memorization.run_probe(pid, args.model)
        memorization._write_result(result)
        print(json.dumps({"patch_id": pid, "error": result.get("error"),
                          "recognized": result.get("recognized"),
                          "recalled_label": result.get("recalled_label")}, default=str), flush=True)


if __name__ == "__main__":
    main()
