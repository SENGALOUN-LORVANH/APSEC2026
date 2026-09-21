"""Step 2: rerun ONLY the runs that failed with an API/billing/connection error, for both models.

Successful runs already on disk are the cache -- they are reused, never re-issued (so a patch where
2/3 succeeded only pays for the 1 failed run). Genuine parse failures are NOT rerun; they are a real
result and are classified separately.

Locations:
  claude-haiku-4-5  -> results/semantic_runs/<patch_id>.json      (primary; also updates semantic_results.csv)
  claude-sonnet-5   -> results/model_comparison/<patch_id>__<model>.json  (comparison only)

All LLM calls go through semantic.build_request (request_builders -> leakage_guard) and llm_client.send.
"""
import json
import glob
from pathlib import Path

import llm_client
import scores
import semantic

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_RUNS = ROOT / "results" / "semantic_runs"
MODEL_COMPARISON = ROOT / "results" / "model_comparison"


def error_class(err):
    if err is None:
        return "ok"
    e = str(err).lower()
    if "credit balance" in e or "billing" in e or "insufficient" in e:
        return "billing"
    if "apiconnection" in e or "connection error" in e or ("connection" in e and "error" in e):
        return "connection"
    if "parse failure" in e:
        return "parse"
    if "ratelimit" in e or "overloaded" in e:
        return "rate"
    return "other"


RERUNNABLE = {"billing", "connection", "rate"}


def reissue_run(client, req, model, run_index):
    """One guarded call; return a run row shaped exactly like semantic.run_semantic's rows."""
    resp, latency, attempts, _settings, err = llm_client.send(client, req, model)
    row = {"run": run_index, "latency_s": latency, "attempts": attempts, "error": err}
    if resp is not None:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            row["input_tokens"] = getattr(usage, "input_tokens", None)
            row["output_tokens"] = getattr(usage, "output_tokens", None)
        try:
            parsed = semantic.parse_response(resp)
            s_sem, clipped = scores.s_sem_run(parsed["judgement"], parsed["confidence"])
            row.update(parsed=parsed, s_sem=s_sem, confidence_clipped=clipped)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            row["error"] = f"parse failure: {type(e).__name__}: {e}"
    return row


def process_file(fp, model, client, summary):
    result = json.loads(Path(fp).read_text())
    runs = result.get("runs", [])
    to_rerun = [i for i, r in enumerate(runs) if error_class(r.get("error")) in RERUNNABLE]
    if not to_rerun:
        return False
    patch_id = result["patch_id"]
    req, debug = semantic.build_request(patch_id, result.get("condition", "C"))
    print(f"  {patch_id} [{model}]: reissuing runs {[runs[i]['run'] for i in to_rerun]} "
          f"(keeping {len(runs) - len(to_rerun)})", flush=True)
    for i in to_rerun:
        before = error_class(runs[i].get("error"))
        new_row = reissue_run(client, req, model, runs[i]["run"])
        after = error_class(new_row.get("error"))
        summary.append({"patch_id": patch_id, "model": model, "run": runs[i]["run"],
                        "was": before, "now": after})
        runs[i] = new_row
    # recompute aggregate over successful runs only
    s_values = [r["s_sem"] for r in runs if "s_sem" in r]
    s_final, decision = scores.s_sem_final(s_values)
    result.update(n_parsed=len(s_values), s_sem_final=s_final, decision=decision,
                  context_errors=debug["context_errors"], runs=runs)
    if model == "claude-haiku-4-5":
        semantic._write_result(result)  # updates semantic_results.csv + semantic_runs/<patch_id>.json
    else:
        Path(fp).write_text(json.dumps(result, indent=2, default=str))
    return True


def main():
    import anthropic
    client = anthropic.Anthropic()
    summary = []
    print("=== claude-haiku-4-5 (semantic_runs) ===", flush=True)
    for fp in sorted(glob.glob(str(SEMANTIC_RUNS / "*.json"))):
        process_file(fp, "claude-haiku-4-5", client, summary)
    print("=== claude-sonnet-5 (model_comparison) ===", flush=True)
    for fp in sorted(glob.glob(str(MODEL_COMPARISON / "*.json"))):
        model = "claude-sonnet-5"
        process_file(fp, model, client, summary)

    print("\n=== rerun summary ===")
    print(json.dumps(summary, indent=2))
    fixed = sum(1 for s in summary if s["now"] == "ok")
    still = [s for s in summary if s["now"] != "ok"]
    print(f"\nreissued={len(summary)} now_ok={fixed} still_failing={len(still)}")
    for s in still:
        print("  STILL FAILING:", s)
    (ROOT / "results" / "rerun_semantic_summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
