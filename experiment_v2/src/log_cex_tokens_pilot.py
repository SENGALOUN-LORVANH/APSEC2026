"""Backfill input/output token counts for the pilot's counterexample calls.

The pilot's counterexample runs predate counterexample token logging (oracle_runner now records usage, but the
48 pilot run JSONs were written before that). To recompute the pilot cost from REAL measured tokens -- never an
estimate -- this re-issues the byte-identical guarded generation request (oracle_runner.build_cex_request, the
same request_builders -> leakage_guard -> llm_client path the pilot used) once per patch and records the usage.
It does NOT re-run the Java oracle validation: only the LLM generation call is repeated, and only the
input_tokens/output_tokens fields are merged into each existing results/counterexample_runs/<patch>.json. Input
tokens are exact (identical prompt); output tokens are a fresh sample of the same K=3 generation. This is
recorded in protocol/DEVIATIONS.md.

Usage (inside the qc-v2 container, workspaces mounted -- context.extract needs the buggy checkout):
  python src/log_cex_tokens_pilot.py            # backfill every pilot counterexample run
  python src/log_cex_tokens_pilot.py --dry-run  # list patches, no API calls
"""
import argparse
import json
from pathlib import Path

import oracle_runner
import llm_client

ROOT = Path(__file__).resolve().parents[1]
CEX_RUNS_DIR = ROOT / "results" / "counterexample_runs"
MODEL = "claude-haiku-4-5"  # counterexample arm uses the primary model


def backfill_one(client, path):
    data = json.loads(path.read_text())
    patch_id = data["patch_id"]
    req, _ctx = oracle_runner.build_cex_request(patch_id)
    resp, latency, attempts, settings, err = llm_client.send(client, req, MODEL)
    if resp is None:
        return {"patch_id": patch_id, "error": err, "input_tokens": None, "output_tokens": None}
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "input_tokens", None) if usage is not None else None
    out_tok = getattr(usage, "output_tokens", None) if usage is not None else None
    data["input_tokens"] = in_tok
    data["output_tokens"] = out_tok
    data["tokens_backfilled"] = True  # provenance: usage measured by re-issuing the identical request post-hoc
    path.write_text(json.dumps(data, indent=2, default=str))
    return {"patch_id": patch_id, "error": None, "input_tokens": in_tok, "output_tokens": out_tok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-issue even for runs already backfilled")
    args = ap.parse_args()

    paths = sorted(CEX_RUNS_DIR.glob("*.json"))
    if not args.force:
        paths = [p for p in paths if not json.loads(p.read_text()).get("tokens_backfilled")]
    print(f"{len(paths)} counterexample run JSONs", flush=True)
    if args.dry_run:
        for p in paths:
            print("  ", p.name, flush=True)
        return

    import anthropic
    client = anthropic.Anthropic()
    tin = tout = n = 0
    for p in paths:
        r = backfill_one(client, p)
        if r["input_tokens"] is not None:
            tin += r["input_tokens"]; tout += r["output_tokens"] or 0; n += 1
        print(json.dumps(r, default=str), flush=True)
    print(f"\nbackfilled {n}/{len(paths)} with tokens; total in={tin} out={tout}", flush=True)


if __name__ == "__main__":
    main()
