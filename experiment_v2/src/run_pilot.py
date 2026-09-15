"""50-patch pilot orchestrator (Step 17, protocol.yaml staging.stage2). Extends run_smoke_test.py's pattern:
skips checkout for bugs already successfully processed (11 patches reused from the smoke test), runs semantic
evaluation with BOTH candidate models (comparison data for the selected_model decision) but counterexample/
oracle/vuln/edit/PVS* with only the primary model (PILOT_MODEL) -- a deliberate time-scoping decision
documented in reports/PILOT_SAMPLE.md. Every stage's success/failure is recorded, never silently dropped.
"""
import csv
import json
import time
import traceback
from pathlib import Path

import assemble_pvs
import d4j
import memorization
import oracle_runner
import semantic

ROOT = Path(__file__).resolve().parents[1]
PILOT_SAMPLE_CSV = ROOT / "results" / "pilot_sample.csv"
PILOT_LOG = ROOT / "results" / "pilot_log.json"
MODEL_COMPARISON_DIR = ROOT / "results" / "model_comparison"
PILOT_MODEL = "claude-haiku-4-5"
COMPARISON_MODEL = "claude-sonnet-5"


def _stage(log, name, fn, *args):
    t0 = time.perf_counter()
    try:
        result = fn(*args)
        log["stages"][name] = {"ok": True, "seconds": time.perf_counter() - t0}
        return result
    except Exception as e:  # noqa: BLE001 - recorded, never hidden
        log["stages"][name] = {"ok": False, "seconds": time.perf_counter() - t0,
                               "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
        return None


def _bug_already_ok(bug_id):
    if not d4j.D4J_STATUS_CSV.exists():
        return False
    with open(d4j.D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["bug_id"] == bug_id:
                return row["buggy_checkout_available"] == "True" and row["fixed_checkout_available"] == "True"
    return False


def _apply_patch(patch_id, bug_id):
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    trigger = d4j.trigger_tests_for(bug_id)
    diff_path = d4j.ROOT / row["normalized_patch_location"]
    result = d4j.apply_candidate(patch_id, bug_id, diff_path, trigger)
    d4j._write_status_csv(d4j.PATCH_STATUS_CSV, [result], d4j.PATCH_FIELDS)
    return result


def _compute_fingerprint(patch_id, bug_id):
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    diff_path = d4j.ROOT / row["normalized_patch_location"]
    return d4j.compute_fingerprint(patch_id, bug_id, diff_path)


def _comparison_semantic(patch_id):
    """Sonnet run for model-selection comparison, stored separately -- never touches the shared
    semantic_results.csv (which holds the primary/PILOT_MODEL result that PVS* is assembled from)."""
    result = semantic.run_semantic(patch_id, "C", COMPARISON_MODEL)
    MODEL_COMPARISON_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = patch_id.replace("/", "_")
    (MODEL_COMPARISON_DIR / f"{safe_name}__{COMPARISON_MODEL}.json").write_text(
        json.dumps(result, indent=2, default=str))
    return result


def run_one(bug_id, patch_id):
    log = {"bug_id": bug_id, "patch_id": patch_id, "stages": {}}

    if _bug_already_ok(bug_id):
        log["stages"]["checkout_bug"] = {"ok": True, "seconds": 0, "reused": True}
    else:
        bug_status = _stage(log, "checkout_bug", d4j.process_bug, bug_id)
        if bug_status is not None:
            d4j._write_status_csv(d4j.D4J_STATUS_CSV, [bug_status], d4j.BUG_FIELDS)
        if bug_status is None or not bug_status.get("buggy_checkout_available") or not bug_status.get("fixed_checkout_available"):
            log["stopped_after"] = "checkout_bug"
            return log

    patch_status = _stage(log, "apply_patch", _apply_patch, patch_id, bug_id)
    if patch_status is None or not patch_status.get("patch_applies"):
        log["stopped_after"] = "apply_patch"
        return log

    _stage(log, "fingerprint", _compute_fingerprint, patch_id, bug_id)

    semantic_result = _stage(log, "semantic_primary", semantic.run_semantic, patch_id, "C", PILOT_MODEL)
    if semantic_result:
        _stage(log, "write_semantic_primary", semantic._write_result, semantic_result)

    _stage(log, "semantic_comparison", _comparison_semantic, patch_id)

    cex_result = _stage(log, "counterexample", oracle_runner.run_counterexamples, patch_id, PILOT_MODEL)
    if cex_result:
        _stage(log, "write_counterexample", oracle_runner._write_result, cex_result)

    probe_result = _stage(log, "memorization_probe", memorization.run_probe, patch_id, PILOT_MODEL)
    if probe_result:
        _stage(log, "write_probe", memorization._write_result, probe_result)

    pvs_row = _stage(log, "assemble_pvs", assemble_pvs.assemble, patch_id, bug_id)
    if pvs_row:
        _stage(log, "write_pvs", assemble_pvs._write_row, pvs_row)
        log["pvs_row"] = {k: v for k, v in pvs_row.items() if k != "context_errors"}

    log["stopped_after"] = None
    return log


def load_sample():
    with open(PILOT_SAMPLE_CSV, newline="", encoding="utf-8") as f:
        return [(r["bug_id"], r["patch_id"]) for r in csv.DictReader(f)]


def main():
    sample = load_sample()
    results = json.loads(PILOT_LOG.read_text()) if PILOT_LOG.exists() else []
    done_patches = {r["patch_id"] for r in results if r.get("stopped_after") is None}
    for bug_id, patch_id in sample:
        if patch_id in done_patches:
            print(f"=== SKIP (already done) {bug_id} / {patch_id} ===", flush=True)
            continue
        print(f"=== {bug_id} / {patch_id} ===", flush=True)
        results = [r for r in results if r["patch_id"] != patch_id]
        log = run_one(bug_id, patch_id)
        results.append(log)
        print(json.dumps({"bug_id": bug_id, "stopped_after": log["stopped_after"],
                          "stage_ok": {k: v["ok"] for k, v in log["stages"].items()}}), flush=True)
        PILOT_LOG.write_text(json.dumps(results, indent=2, default=str))
    print("done, total in log:", len(results))


if __name__ == "__main__":
    main()
