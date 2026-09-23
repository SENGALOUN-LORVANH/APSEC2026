"""Memorization probe (ported from experiment/src/memorization_probe.py, v1) to the v2 request-builder
architecture. For a patch, shows the model only the candidate diff (no filename, tests, tool, or label) and
asks it to recall the Defects4J bug and any published correctness label. A correct bug-id guess is evidence
the item is memorized, not reasoned about.

Usage: python src/memorization.py --patch <patch_id> [--model claude-haiku-4-5]
"""
import argparse
import csv
import json
from pathlib import Path

import d4j
import dataset
import llm_client
import request_builders

ROOT = Path(__file__).resolve().parents[1]
PROBE_RESULTS = ROOT / "results" / "memorization_probe.csv"


def run_probe(patch_id, model="claude-haiku-4-5"):
    import anthropic
    client = anthropic.Anthropic()

    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    diff_path = ROOT / row["normalized_patch_location"]
    with open(diff_path, encoding="utf-8", errors="replace", newline="") as f:
        candidate_diff = f.read().replace("\r\n", "\n")

    patch_meta = {"patch_id": row["patch_id"], "APR_tool": row["APR_tool"],
                  "original_dataset_location": row["original_dataset_location"]}
    req = request_builders.build_probe_request(patch_meta, candidate_diff, known_tools=dataset.known_apr_tools(),
                                               fingerprint_hashes=d4j.load_fingerprint(patch_id),
                                               allowed_source_text=candidate_diff)
    resp, latency, attempts, settings, err = llm_client.send(client, req, model)
    result = {"patch_id": patch_id, "true_project": row["project"], "true_bug_number": row["bug_number"],
              "model": model, "error": err, "input_tokens": None, "output_tokens": None}
    if resp is not None:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result["input_tokens"] = getattr(usage, "input_tokens", None)
            result["output_tokens"] = getattr(usage, "output_tokens", None)
        try:
            parsed = json.loads(llm_client.response_text(resp))
            result.update(parsed)
            result["recognized"] = (str(parsed.get("bug_number")) == row["bug_number"]
                                    and parsed.get("project") == row["project"])
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            result["error"] = f"parse failure: {type(e).__name__}: {e}"
    return result


def _write_result(result):
    PROBE_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if PROBE_RESULTS.exists():
        with open(PROBE_RESULTS, newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["patch_id"] != result["patch_id"]]
    existing.append(result)
    fieldnames = ["patch_id", "true_project", "true_bug_number", "model", "project", "bug_number",
                  "recalled_label", "recognized", "error"]
    with open(PROBE_RESULTS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in existing:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True)
    ap.add_argument("--model", default="claude-haiku-4-5")
    args = ap.parse_args()
    result = run_probe(args.patch, args.model)
    _write_result(result)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
