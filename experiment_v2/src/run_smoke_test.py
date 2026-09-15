"""10-patch smoke test orchestrator (Step 14-15, protocol.yaml staging.stage1). Runs the full pipeline
(checkout -> patch -> context -> semantic -> counterexample/oracle -> vuln -> edit -> PVS*) for each patch in
SAMPLE, never stopping on a single patch's failure -- every failure is recorded, never silently dropped.
"""
import json
import time
import traceback
from pathlib import Path

import assemble_pvs
import d4j
import oracle_runner
import semantic

ROOT = Path(__file__).resolve().parents[1]
SMOKE_LOG = ROOT / "results" / "smoke_test_log.json"

SAMPLE = [
    ("Chart-12", "Patches_ICSE__Ddifferent__Arja__Chart__patch1-Chart-12-Arja"),
    ("Chart-15", "Patches_ICSE__Doverfitting__AVATAR__Chart__patch1-Chart-15-AVATAR-plausible"),
    ("Closure-115", "Patches_ICSE__Ddifferent__Arja__Closure__patch1-Closure-115-Arja"),
    ("Closure-117", "Patches_ICSE__Doverfitting__Arja__Closure__patch1-Closure-117-Arja-plausible"),
    ("Lang-43", "Patches_ICSE__Dsame__SimFix__Lang__patch1-Lang-43-SimFix"),
    ("Lang-58", "Patches_ICSE__Doverfitting__AVATAR__Lang__patch1-Lang-58-AVATAR-plausible"),
    ("Math-53", "Patches_others__Dcorrect__CapGen__Math__patch1-Math-53-CapGen"),
    ("Math-28", "Patches_ICSE__Doverfitting__Arja__Math__patch1-Math-28-Arja-plausible"),
    ("Time-15", "Patches_ICSE__Dsame__ACS__Time__patch1-Time-15-ACS"),
    ("Time-11", "Patches_ICSE__Doverfitting__FixMiner__Time__patch1-Time-11-FixMiner-plausible"),
]


def _stage(log, name, fn, *args):
    t0 = time.perf_counter()
    try:
        result = fn(*args)
        log["stages"][name] = {"ok": True, "seconds": time.perf_counter() - t0}
        return result
    except Exception as e:  # noqa: BLE001 - recorded, never hidden (protocol: record every failure)
        log["stages"][name] = {"ok": False, "seconds": time.perf_counter() - t0,
                               "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
        return None


def run_one(bug_id, patch_id):
    log = {"bug_id": bug_id, "patch_id": patch_id, "stages": {}}

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

    semantic_result = _stage(log, "semantic", semantic.run_semantic, patch_id, "C", "claude-haiku-4-5")
    if semantic_result:
        _stage(log, "write_semantic", semantic._write_result, semantic_result)

    cex_result = _stage(log, "counterexample", oracle_runner.run_counterexamples, patch_id, "claude-haiku-4-5")
    if cex_result:
        _stage(log, "write_counterexample", oracle_runner._write_result, cex_result)

    pvs_row = _stage(log, "assemble_pvs", assemble_pvs.assemble, patch_id, bug_id)
    if pvs_row:
        _stage(log, "write_pvs", assemble_pvs._write_row, pvs_row)
        log["pvs_row"] = {k: v for k, v in pvs_row.items() if k not in ("context_errors",)}

    log["stopped_after"] = None
    return log


def _apply_patch(patch_id, bug_id):
    import csv
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    trigger = d4j.trigger_tests_for(bug_id)
    diff_path = d4j.ROOT / row["normalized_patch_location"]
    result = d4j.apply_candidate(patch_id, bug_id, diff_path, trigger)
    d4j._write_status_csv(d4j.PATCH_STATUS_CSV, [result], d4j.PATCH_FIELDS)
    return result


def _compute_fingerprint(patch_id, bug_id):
    import csv
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    diff_path = d4j.ROOT / row["normalized_patch_location"]
    return d4j.compute_fingerprint(patch_id, bug_id, diff_path)


def main():
    results = []
    for bug_id, patch_id in SAMPLE:
        print(f"=== {bug_id} / {patch_id} ===", flush=True)
        log = run_one(bug_id, patch_id)
        results.append(log)
        print(json.dumps({"bug_id": bug_id, "stopped_after": log["stopped_after"],
                          "stage_ok": {k: v["ok"] for k, v in log["stages"].items()}}), flush=True)
        SMOKE_LOG.parent.mkdir(parents=True, exist_ok=True)
        SMOKE_LOG.write_text(json.dumps(results, indent=2, default=str))
    print("done, wrote", SMOKE_LOG)


if __name__ == "__main__":
    main()
