"""Summarize pilot logs: reliability, latency, tokens, measured cost, projected full-run cost.

The 20-patch judgement/label agreement printed here is a sanity check only, not a result.

Usage: python src/pilot_summary.py results/raw_llm_responses_haiku_pilot.jsonl [...]
Output: results/pilot_summary.json
"""
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# USD per 1M tokens (input, output), Anthropic first-party list prices.
# Source: Claude API reference bundled with Claude Code, cached 2026-06-24. Re-check the pricing page before publishing.
PRICES = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5": (2.00, 10.00)}
N_PATCHES = sum(1 for _ in open(ROOT / "data" / "patches.jsonl"))
LABELS = {json.loads(l)["patch_id"]: json.loads(l)["label"] for l in open(ROOT / "data" / "patches.jsonl")}


def summarize(path):
    entries = [json.loads(l) for l in open(path)]
    ok = [e for e in entries if e["status"] == "ok"]
    model = entries[0]["model"]
    pin, pout = PRICES[model]
    tin = [e["usage"]["input_tokens"] + (e["usage"].get("cache_read_input_tokens") or 0)
           + (e["usage"].get("cache_creation_input_tokens") or 0) for e in ok]
    tout = [e["usage"]["output_tokens"] for e in ok]
    cost = [(i * pin + o * pout) / 1e6 for i, o in zip(tin, tout)]
    parsed = [e for e in ok if e.get("parsed")]
    agree = sum((e["parsed"]["judgement"] == "OVERFITTING") == (LABELS[e["patch_id"]] == "overfitting") for e in parsed)
    lat = [e["latency_s"] for e in ok]
    return {
        "log": str(path), "model": model, "response_models": sorted({e["response_model"] for e in ok}),
        "request_settings": ok[0]["request_settings"] if ok else None,
        "calls": len(entries), "ok": len(ok), "errors": len(entries) - len(ok),
        "parse_failures": len(ok) - len(parsed),
        "stop_reasons": {s: sum(e["stop_reason"] == s for e in ok) for s in {e["stop_reason"] for e in ok}},
        "latency_s": {"mean": round(st.mean(lat), 2), "median": round(st.median(lat), 2), "max": round(max(lat), 2)},
        "input_tokens_mean": round(st.mean(tin)), "output_tokens_mean": round(st.mean(tout)),
        "cost_usd_total_pilot": round(sum(cost), 4), "cost_usd_per_call_mean": round(st.mean(cost), 5),
        "projected_cost_usd_full_1_run": round(st.mean(cost) * N_PATCHES, 2),
        "projected_cost_usd_full_3_runs": round(st.mean(cost) * N_PATCHES * 3, 2),
        "sanity_agreement_with_labels": f"{agree}/{len(parsed)}",
        "price_source": "Claude API skill model table cached 2026-06-24; verify before publishing",
    }


def main():
    out = [summarize(Path(p)) for p in sys.argv[1:]]
    (ROOT / "results" / "pilot_summary.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
