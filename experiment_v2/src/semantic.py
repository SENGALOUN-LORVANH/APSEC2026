"""Semantic evaluation pipeline (Steps 11-12): assemble context, build the guarded LLM request, send it,
and compute S_sem from the structured judgement. The only module besides oracle code that touches an LLM
response for scoring purposes.

Usage:
  python src/semantic.py --patch <patch_id> --dry-run          # build request, no API call
  python src/semantic.py --patch <patch_id> --model <model>    # real run: semantic_runs_per_patch calls
"""
import argparse
import csv
import json
import re
from pathlib import Path

import context
import d4j
import dataset
import llm_client
import request_builders
import scores
import workspaces

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
SEMANTIC_RESULTS = ROOT / "results" / "semantic_results.csv"
FAILURE_MSG_PER_CHARS = 2000
FAILURE_MSG_TOTAL_CHARS = 8000
SEMANTIC_RUNS_PER_PATCH = 3  # protocol.yaml llm.semantic_runs_per_patch


def load_manifest_row(patch_id):
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["patch_id"] == patch_id:
                return row
    raise KeyError(f"patch_id not in manifest: {patch_id}")


def load_d4j_status(bug_id):
    with open(d4j.D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["bug_id"] == bug_id:
                return row
    raise KeyError(f"bug_id not in d4j_status.csv (run `d4j.py --bug {bug_id}` first): {bug_id}")


def read_failure_messages(bug_id, per_message_chars=FAILURE_MSG_PER_CHARS, total_chars=FAILURE_MSG_TOTAL_CHARS):
    """workspaces/buggy/<P_N>/failing_tests, per-test and total char caps (protocol.yaml failure_message_caps)."""
    f = workspaces.buggy_dir(bug_id) / "failing_tests"
    if not f.exists():
        return ""
    content = f.read_text(encoding="utf-8", errors="replace")
    sections = re.split(r"(?m)^--- ", content)[1:]
    parts, total = [], 0
    for sec in sections:
        lines = sec.splitlines()
        if not lines:
            continue
        name, body = lines[0].strip(), "\n".join(lines[1:]).strip()
        msg = f"{name}\n{body[:per_message_chars]}"
        if total + len(msg) > total_chars:
            msg = msg[:max(total_chars - total, 0)]
        if msg:
            parts.append(msg)
            total += len(msg)
        if total >= total_chars:
            break
    return "\n\n".join(parts)


def build_request(patch_id, condition="C"):
    """-> (LLMRequest, debug_info). No API call. Raises leakage_guard.LeakageError if the guard rejects it."""
    row = load_manifest_row(patch_id)
    bug_id = row["bug_id"]
    d4j_row = load_d4j_status(bug_id)
    trigger_tests = d4j_row["trigger_tests"].split(";") if d4j_row["trigger_tests"] else []

    diff_path = ROOT / row["normalized_patch_location"]
    with open(diff_path, encoding="utf-8", errors="replace", newline="") as f:
        candidate_diff = f.read().replace("\r\n", "\n")

    failure_messages = read_failure_messages(bug_id) if condition in ("B", "C") else ""
    context_items, context_errors = [], []
    if condition == "C":
        buggy_dir = workspaces.buggy_dir(bug_id)
        src_classes_rel = d4j_row["dir_src_classes"]
        context_items, context_errors = context.extract(buggy_dir, src_classes_rel, candidate_diff)

    patch_meta = {"patch_id": row["patch_id"], "APR_tool": row["APR_tool"],
                  "original_dataset_location": row["original_dataset_location"]}
    req = request_builders.build_semantic_request(
        patch_meta, condition, candidate_diff,
        failing_tests=";".join(trigger_tests), failure_messages=failure_messages,
        context_items=context_items, known_tools=dataset.known_apr_tools(),
        fingerprint_hashes=d4j.load_fingerprint(patch_id),
        allowed_source_text=candidate_diff)
    return req, {"context_errors": context_errors, "trigger_tests": trigger_tests}


def parse_response(resp):
    """Anthropic structured-output (json_schema) response -> dict matching prompts/semantic_v2.txt schema."""
    return json.loads(llm_client.response_text(resp))


def run_semantic(patch_id, condition="C", model="claude-haiku-4-5", n_runs=SEMANTIC_RUNS_PER_PATCH):
    import anthropic
    client = anthropic.Anthropic()
    req, debug = build_request(patch_id, condition)

    runs = []
    for i in range(n_runs):
        resp, latency, attempts, settings, err = llm_client.send(client, req, model)
        row = {"run": i, "latency_s": latency, "attempts": attempts, "error": err}
        if resp is not None:
            usage = getattr(resp, "usage", None)
            if usage is not None:
                row["input_tokens"] = getattr(usage, "input_tokens", None)
                row["output_tokens"] = getattr(usage, "output_tokens", None)
            try:
                parsed = parse_response(resp)
                s_sem, clipped = scores.s_sem_run(parsed["judgement"], parsed["confidence"])
                row.update(parsed=parsed, s_sem=s_sem, confidence_clipped=clipped)
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                row["error"] = f"parse failure: {type(e).__name__}: {e}"
        runs.append(row)

    s_values = [r["s_sem"] for r in runs if "s_sem" in r]
    s_final, decision = scores.s_sem_final(s_values)
    result = {"patch_id": patch_id, "condition": condition, "model": model, "n_runs": n_runs,
              "n_parsed": len(s_values), "s_sem_final": s_final, "decision": decision,
              "ground_truth_label": None, "context_errors": debug["context_errors"], "runs": runs}
    return result


def _write_result(result):
    SEMANTIC_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    row = {"patch_id": result["patch_id"], "condition": result["condition"], "model": result["model"],
           "n_runs": result["n_runs"], "n_parsed": result["n_parsed"], "s_sem_final": result["s_sem_final"],
           "decision": result["decision"]}
    existing = []
    if SEMANTIC_RESULTS.exists():
        with open(SEMANTIC_RESULTS, newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["patch_id"] != result["patch_id"]]
    existing.append(row)
    with open(SEMANTIC_RESULTS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerows(existing)
    # full per-run detail (raw judgements) kept alongside for audit, not just the summary row
    detail_dir = ROOT / "results" / "semantic_runs"
    detail_dir.mkdir(parents=True, exist_ok=True)
    (detail_dir / f"{result['patch_id']}.json").write_text(json.dumps(result, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True)
    ap.add_argument("--condition", default="C", choices=["A", "B", "C"])
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        req, debug = build_request(args.patch, args.condition)
        print(json.dumps({"system_chars": len(req.system), "user_chars": len(req.user),
                          "prompt_sha256": req.prompt_sha256, "context_sha256": req.context_sha256,
                          "context_log": req.context_log, "debug": debug}, indent=2))
    else:
        result = run_semantic(args.patch, args.condition, args.model)
        _write_result(result)
        print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2, default=str))
        for r in result["runs"]:
            print("run", r["run"], "error:", r.get("error"), "s_sem:", r.get("s_sem"))


if __name__ == "__main__":
    main()
