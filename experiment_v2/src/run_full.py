"""Resumable, checkpointed, parallel full-run orchestrator (work order C).

Runs the frozen v2 pipeline over every primary-policy patch (manifest included_primary == True: 899 patches
across 202 bugs), model claude-haiku-4-5, semantic condition C (3 runs), K=3 counterexamples, and Stage 2B --
NO model-comparison arm (the model is already selected). Design for a ~53 h run that must survive kills and
reboots:

  * Unit of parallel work is a BUG. All of a bug's patches run sequentially inside one worker, so no two
    workers ever touch the same buggy/ or fixed_oracle/ checkout. Different bugs are independent directories,
    so N bugs run concurrently (default 4, --workers).
  * Per-patch checkpoint results/full_run/checkpoints/<patch_id>.json is written atomically (tmp + os.replace)
    ONLY when the patch's pipeline finishes. A kill mid-patch leaves no checkpoint, so that patch is simply
    redone on resume; completed patches are skipped. Safe to Ctrl-C / docker kill / reboot at any time.
  * Workers never do a read-modify-write on a shared results CSV (that would race). They write only per-patch
    files (checkpoint + semantic_runs/ counterexample_runs/ stage2b/ under results/full_run/, plus the
    inherently per-patch fingerprints/). The two shared status CSVs (d4j_status.csv, patch_d4j_status.csv) are
    written under STATUS_LOCK and atomically, so lock-free readers in other workers always see a whole file.
  * PVS* assembly and all corpus-level CSVs are built in a separate single-threaded pass (`--consolidate`),
    never during the parallel run.

Per-stage timings are preserved in each checkpoint (log["stages"][name]["seconds"]).

Usage (inside the qc-v2 container, workspaces mounted):
  python src/run_full.py                       # run/resume with 4 workers
  python src/run_full.py --workers 6
  python src/run_full.py --only PATCH1,PATCH2   # restrict to specific patches (used by the kill/resume test)
  python src/run_full.py --consolidate          # build results/full_run/*.csv from the checkpoints
  python src/run_full.py --status               # print progress counts and exit
"""
import argparse
import csv
import json
import os
import threading
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import d4j
import memorization
import oracle_runner
import semantic
import stage2b
import workspaces

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
FULL_DIR = ROOT / "results" / "full_run"
CKPT_DIR = FULL_DIR / "checkpoints"
SEM_DIR = FULL_DIR / "semantic_runs"
CEX_DIR = FULL_DIR / "counterexample_runs"
S2B_DIR = FULL_DIR / "stage2b"
MODEL = "claude-haiku-4-5"

STATUS_LOCK = threading.Lock()   # serialize read-modify-write of the two shared status CSVs
PROGRESS_LOCK = threading.Lock()
_progress = {"done": 0, "failed": 0, "total": 0}


# ----------------------------------------------------------------- helpers
def _truthy(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def load_primary_patches():
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if _truthy(r.get("included_primary", ""))]


def ckpt_path(patch_id):
    return CKPT_DIR / f"{patch_id}.json"


def is_done(patch_id):
    p = ckpt_path(patch_id)
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
    except Exception:
        return False  # corrupt/partial checkpoint -> redo
    return bool(d.get("complete")) or d.get("terminal_failure") is not None


def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(obj, indent=2, default=str))
    os.replace(tmp, path)


def _load_bug_row(bug_id):
    if not d4j.D4J_STATUS_CSV.exists():
        return None
    with open(d4j.D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bug_id"] == bug_id:
                return r
    return None


def _record_bug_status(status):
    with STATUS_LOCK:
        d4j._write_status_csv(d4j.D4J_STATUS_CSV, [status], d4j.BUG_FIELDS)


def _record_patch_status(status):
    with STATUS_LOCK:
        d4j._write_status_csv(d4j.PATCH_STATUS_CSV, [status], d4j.PATCH_FIELDS)


def _manifest_row(patch_id):
    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        return next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)


# ----------------------------------------------------------------- per-bug / per-patch
def ensure_bug_checked_out(bug_id):
    """Reuse an existing checkout (from the pilot or a prior full-run pass) when buggy+fixed are both present
    and recorded available; otherwise check out now. Returns (ok, status_row_or_dict)."""
    row = _load_bug_row(bug_id)
    buggy_dir = workspaces.buggy_dir(bug_id)
    if (row and _truthy(row.get("buggy_checkout_available")) and _truthy(row.get("fixed_checkout_available"))
            and buggy_dir.exists()):
        return True, row
    status = d4j.process_bug(bug_id)
    _record_bug_status(status)
    ok = bool(status.get("buggy_checkout_available") and status.get("fixed_checkout_available"))
    return ok, status


def _apply_patch(patch_id, bug_id):
    row = _manifest_row(patch_id)
    trigger = d4j.trigger_tests_for(bug_id)
    diff_path = d4j.ROOT / row["normalized_patch_location"]
    result = d4j.apply_candidate(patch_id, bug_id, diff_path, trigger)
    _record_patch_status(result)
    return result


def _stage(log, name, fn, *args):
    t0 = time.perf_counter()
    try:
        result = fn(*args)
        log["stages"][name] = {"ok": True, "seconds": round(time.perf_counter() - t0, 3)}
        return result
    except Exception as e:  # noqa: BLE001 - recorded, never hidden
        log["stages"][name] = {"ok": False, "seconds": round(time.perf_counter() - t0, 3),
                               "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
        return None


def run_one_patch(bug_id, patch_id):
    """Full per-patch pipeline. Writes per-patch detail files + returns the checkpoint log. Does NOT touch any
    shared results CSV (consolidation does that) and does NOT call assemble_pvs (PVS* is ranking-only, built at
    consolidation/evaluation time)."""
    log = {"patch_id": patch_id, "bug_id": bug_id, "model": MODEL, "stages": {},
           "complete": False, "terminal_failure": None,
           "semantic": None, "counterexample": None, "memorization": None, "stage2b": None}

    patch_status = _stage(log, "apply_patch", _apply_patch, patch_id, bug_id)
    log["patch_status"] = patch_status
    if patch_status is None or not patch_status.get("patch_applies"):
        log["terminal_failure"] = "apply_patch"
        return log

    _stage(log, "fingerprint", d4j.compute_fingerprint, patch_id, bug_id,
           d4j.ROOT / _manifest_row(patch_id)["normalized_patch_location"])

    sem = _stage(log, "semantic", semantic.run_semantic, patch_id, "C", MODEL)
    if sem is not None:
        log["semantic"] = sem
        _atomic_write_json(SEM_DIR / f"{patch_id}.json", sem)

    cex = _stage(log, "counterexample", oracle_runner.run_counterexamples, patch_id, MODEL)
    if cex is not None:
        log["counterexample"] = cex
        _atomic_write_json(CEX_DIR / f"{patch_id}.json", cex)

    probe = _stage(log, "memorization", memorization.run_probe, patch_id, MODEL)
    if probe is not None:
        log["memorization"] = probe

    s2b = _stage(log, "stage2b", stage2b.run_one, patch_id, bug_id)
    if s2b is not None:
        log["stage2b"] = s2b
        _atomic_write_json(S2B_DIR / f"{patch_id}.json", s2b)

    # "complete" == every stage ran to a value. A stage that errored (e.g. transient API) leaves complete False
    # so a rerun with --retry-errors can redo it; a hard apply failure is terminal above.
    log["complete"] = all(v.get("ok") for v in log["stages"].values())
    return log


def process_bug_group(bug_id, patches, retry_errors):
    """Checkout once, then run each not-yet-done patch of the bug sequentially."""
    to_do = [p for p in patches if not is_done(p) or (retry_errors and _has_stage_error(p))]
    if not to_do:
        return
    ok, status = ensure_bug_checked_out(bug_id)
    if not ok:
        for patch_id in to_do:
            log = {"patch_id": patch_id, "bug_id": bug_id, "model": MODEL, "stages": {},
                   "complete": False, "terminal_failure": "checkout_bug",
                   "checkout_error": (status.get("error") if isinstance(status, dict) else "checkout unavailable")}
            _atomic_write_json(ckpt_path(patch_id), log)
            _bump("failed")
            print(f"[FAIL checkout] {bug_id} :: {patch_id}", flush=True)
        return
    for patch_id in to_do:
        t0 = time.perf_counter()
        log = run_one_patch(bug_id, patch_id)
        _atomic_write_json(ckpt_path(patch_id), log)
        if log["complete"]:
            _bump("done")
            tag = "OK"
        else:
            _bump("failed")
            tag = f"INCOMPLETE({log.get('terminal_failure') or 'stage-error'})"
        secs = round(time.perf_counter() - t0, 1)
        sem = (log.get("semantic") or {})
        print(f"[{tag} {secs}s] {patch_id} "
              f"S_sem={sem.get('s_sem_final')} decision={sem.get('decision')}", flush=True)
        _maybe_progress_summary()


def _has_stage_error(patch_id):
    p = ckpt_path(patch_id)
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
    except Exception:
        return True
    return any(not v.get("ok") for v in d.get("stages", {}).values())


def _bump(key):
    with PROGRESS_LOCK:
        _progress[key] += 1


def _maybe_progress_summary():
    with PROGRESS_LOCK:
        n = _progress["done"] + _progress["failed"]
        if n % 100 == 0 and n > 0:
            print(f"=== PROGRESS {n}/{_progress['total']} (done={_progress['done']} "
                  f"failed/incomplete={_progress['failed']}) ===", flush=True)


# ----------------------------------------------------------------- drivers
def run(workers, only, retry_errors):
    for d in (CKPT_DIR, SEM_DIR, CEX_DIR, S2B_DIR):
        d.mkdir(parents=True, exist_ok=True)
    patches = load_primary_patches()
    if only:
        only_set = set(only)
        patches = [r for r in patches if r["patch_id"] in only_set]
    by_bug = defaultdict(list)
    for r in patches:
        by_bug[r["bug_id"]].append(r["patch_id"])

    total = len(patches)
    already = sum(1 for r in patches if is_done(r["patch_id"]) and not (retry_errors and _has_stage_error(r["patch_id"])))
    with PROGRESS_LOCK:
        _progress["total"] = total
        _progress["done"] = already
    print(f"full run: {total} primary patches over {len(by_bug)} bugs; {already} already done; "
          f"{workers} workers; retry_errors={retry_errors}", flush=True)

    # Order bugs by remaining work descending so long bugs start first (better tail balance).
    bugs = sorted(by_bug.items(),
                  key=lambda kv: -sum(1 for p in kv[1] if not is_done(p)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process_bug_group, bug_id, pl, retry_errors): bug_id for bug_id, pl in bugs}
        for fut in as_completed(futs):
            bug_id = futs[fut]
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[BUG-ERROR] {bug_id}: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
    with PROGRESS_LOCK:
        print(f"\nFULL RUN PASS COMPLETE: done={_progress['done']} failed/incomplete={_progress['failed']} "
              f"of {total}", flush=True)


def status():
    patches = load_primary_patches()
    done = complete = incomplete = terminal = 0
    for r in patches:
        p = ckpt_path(r["patch_id"])
        if not p.exists():
            continue
        done += 1
        try:
            d = json.loads(p.read_text())
        except Exception:
            incomplete += 1
            continue
        if d.get("complete"):
            complete += 1
        elif d.get("terminal_failure"):
            terminal += 1
        else:
            incomplete += 1
    print(json.dumps({"total_primary": len(patches), "checkpoints": done, "complete": complete,
                      "terminal_failure": terminal, "incomplete_stage_error": incomplete,
                      "remaining": len(patches) - done}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", default="", help="comma-separated patch_ids to restrict to")
    ap.add_argument("--retry-errors", action="store_true", help="also redo checkpoints that have a stage error")
    ap.add_argument("--consolidate", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        status()
        return
    if args.consolidate:
        import consolidate_full
        consolidate_full.consolidate()
        return
    only = [s for s in args.only.split(",") if s.strip()] if args.only else None
    run(args.workers, only, args.retry_errors)


if __name__ == "__main__":
    main()
