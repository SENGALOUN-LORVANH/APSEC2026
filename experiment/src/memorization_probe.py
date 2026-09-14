"""Memorization probe: does the model recognize the benchmark item it is judging?

For each patch the model sees exactly the diff it sees in the review (no tests, no filename, no tool, no label)
and is asked (a) which Defects4J bug it is and (b) whether it recalls a published correctness label.
A correct bug-id answer is evidence the item is memorized. evaluate_probe() reports the recognition rate and
review accuracy split by recognized / not recognized.

Usage:
  python src/memorization_probe.py --model claude-haiku-4-5 [--pilot 20]
Log: results/memorization_probe_<model>[_pilot].jsonl
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from llm_review import MODEL_SETTINGS, ROOT, call, load_dotenv  # noqa: E402

PROBE_VERSION = "probe_v1"
SYSTEM = ("You will see a code diff from a Java project. Answer from memory only.\n"
          "1. Which Defects4J project is it from (Chart, Closure, Lang, Math, Time, or another)?\n"
          "2. Which Defects4J bug number is it? Use null if you do not know; do not guess.\n"
          "3. Have you seen this exact patch in a published automated-program-repair patch dataset? If so, was it "
          "labeled CORRECT or OVERFITTING there? Use UNKNOWN if you do not recall.")
SCHEMA = {
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "bug_number": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "recalled_label": {"type": "string", "enum": ["CORRECT", "OVERFITTING", "UNKNOWN"]},
    },
    "required": ["project", "bug_number", "recalled_label"],
    "additionalProperties": False,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(MODEL_SETTINGS))
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    records = [json.loads(l) for l in open(ROOT / "data" / "patches.jsonl")]
    suffix = ""
    if args.pilot:
        ids = set((ROOT / "data" / f"pilot_ids_n{args.pilot}_seed{args.seed}.txt").read_text().split())
        records, suffix = [r for r in records if r["patch_id"] in ids], "_pilot"
    log_path = ROOT / "results" / f"memorization_probe_{args.model}{suffix}.jsonl"
    done = set()
    if log_path.exists():
        done = {json.loads(l)["patch_id"] for l in open(log_path) if json.loads(l)["status"] == "ok"}
    jobs = [r for r in records if r["patch_id"] not in done]
    print(f"{len(records)} patches; {len(jobs)} calls to make; log -> {log_path}")

    for p in (ROOT / ".env", ROOT.parent / ".env"):
        load_dotenv(p)
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.exit("No API key: expected a line 'ANTHROPIC_API_KEY=...' in experiment/.env")
    client, lock = anthropic.Anthropic(max_retries=2), threading.Lock()

    def work(rec):
        resp, latency, attempts, settings, err = call(client, args.model, SYSTEM, rec["diff_for_model"], schema=SCHEMA)
        e = {"timestamp": datetime.now(timezone.utc).isoformat(), "probe_version": PROBE_VERSION,
             "model": args.model, "patch_id": rec["patch_id"], "bug_id": rec["bug_id"],
             "request_settings": settings, "latency_s": latency, "attempts": attempts}
        if err:
            e.update(status="error", error=err)
        else:
            text = next((b.text for b in resp.content if b.type == "text"), "")
            e.update(status="ok", response_model=resp.model, request_id=resp._request_id, stop_reason=resp.stop_reason,
                     usage=resp.usage.to_dict(), text=text)
            try:
                parsed = json.loads(text)
                project, number = rec["bug_id"].rsplit("-", 1)
                e.update(parsed=parsed,
                         project_match=parsed["project"].strip().lower() == project.lower(),
                         bug_id_match=parsed["bug_number"] is not None and str(parsed["bug_number"]) == number)
            except (json.JSONDecodeError, KeyError) as ex:
                e.update(parsed=None, parse_error=str(ex))
        with lock, open(log_path, "a") as f:
            f.write(json.dumps(e) + "\n")
        return e

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = [f.result() for f in as_completed([pool.submit(work, r) for r in jobs])]
    ok = [e for e in results if e["status"] == "ok" and e.get("parsed")]
    print(f"done: {len(ok)} ok/parsed of {len(results)}; bug-id matches: {sum(e['bug_id_match'] for e in ok)}")


if __name__ == "__main__":
    main()
