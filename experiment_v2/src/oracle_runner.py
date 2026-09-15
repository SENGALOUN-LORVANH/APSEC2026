"""Counterexample generation + empirical oracle execution (Step 13). One LLM call returns K candidate tests
(prompts/counterexample_v2.txt); each is judged only by running it, per protocol.yaml's validation_sequence:
  compile -> fail: INVALID_COMPILE, stop.
  run once on fixed_oracle -> fail/timeout: INVALID_ORACLE / TIMEOUT, stop.
  run once on buggy -> pass: VALID_NON_DISCRIMINATING, stop.
  (only if fixed PASS + buggy FAIL) run reps 2,3 on both -> unstable: FLAKY.
  stable -> VALID_BUG_REVEALING -> run once on the candidate -> PASS / FAIL / TIMEOUT.
The model's own stated expectations are never trusted; this module is an ORACLE_MODULE (workspaces.py) and is
the only place besides d4j.py allowed to read fixed_oracle/ content -- to execute the generated test, not to
show it to any LLM.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import context
import d4j
import dataset
import llm_client
import request_builders
import scores
import workspaces

ROOT = Path(__file__).resolve().parents[1]
COUNTEREXAMPLE_RESULTS = ROOT / "results" / "counterexample_results.csv"
CEX_RUNS_DIR = ROOT / "results" / "counterexample_runs"
JDK8 = os.environ.get("JDK8", "/usr/lib/jvm/java-8-openjdk-amd64")
TEST_TIMEOUT_SECONDS = 60  # protocol.yaml defects4j.test_timeout_seconds
K = 3  # protocol.yaml scores.S_cex.K

CLASS_RE = re.compile(r"\bclass\s+(\w+)")
JUNIT3_RE = re.compile(r"extends\s+(?:junit\.framework\.)?TestCase\b")


def extract_class_name(java_source):
    m = CLASS_RE.search(java_source)
    return m.group(1) if m else None


def detect_test_style(buggy_dir, trigger_test_fqcn):
    """-> (test_package, junit_style_instruction, runner_class). Inspects one real existing test file so the
    generated tests match the project's actual JUnit version instead of guessing."""
    class_fqcn = trigger_test_fqcn.split("::")[0]
    package = class_fqcn.rsplit(".", 1)[0] if "." in class_fqcn else ""
    dir_src_tests = d4j.export(buggy_dir, "dir.src.tests")
    test_file = Path(buggy_dir) / (dir_src_tests or "") / (class_fqcn.replace(".", "/") + ".java")
    is_junit3 = test_file.exists() and JUNIT3_RE.search(
        test_file.read_text(encoding="utf-8", errors="replace"))
    if is_junit3:
        style = ("JUnit 3 style: the test class must extend junit.framework.TestCase, test method names start "
                 "with \"test\" and take no arguments, use assertEquals/assertTrue/assertNull etc. (inherited "
                 "from TestCase), no @Test annotations")
        runner = "junit.textui.TestRunner"
    else:
        style = "JUnit 4: annotate test methods with @Test from org.junit.Test; use org.junit.Assert static methods"
        runner = "org.junit.runner.JUnitCore"
    return package, style, runner


def _run_class(workdir, dir_bin_tests, cp_test, fqcn, runner_class, timeout=TEST_TIMEOUT_SECONDS):
    cp = f"{workdir}/{dir_bin_tests}:{cp_test}"
    env = os.environ.copy()
    env["JAVA_HOME"] = JDK8
    env["PATH"] = f"{JDK8}/bin:" + env.get("PATH", "")
    try:
        p = subprocess.run(["java", "-cp", cp, runner_class, fqcn], capture_output=True, text=True,
                           env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    return ("PASS" if p.returncode == 0 else "FAIL"), (p.stdout + p.stderr)[-2000:]


def _prepare_run_dir(source_dir: Path, scratch_dir: Path):
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    shutil.copytree(source_dir, scratch_dir, symlinks=True)
    return scratch_dir


def _inject_and_compile(run_dir: Path, dir_src_tests, class_fqcn, junit_code):
    rel = class_fqcn.replace(".", "/") + ".java"
    target = run_dir / dir_src_tests / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(junit_code, encoding="utf-8")
    return d4j.compile_workdir(run_dir)


def validate_one_test(patch_id, bug_id, test_item, package, runner_class, candidate_dir):
    """Full validation_sequence for one generated test. Returns a result dict; never raises on tool failure."""
    class_name = extract_class_name(test_item["junit_code"])
    result = {"name": test_item.get("name"), "target_class": test_item.get("target_class"),
              "target_method": test_item.get("target_method"), "class_name": class_name,
              "status": None, "candidate_pass": None, "log": ""}
    if not class_name:
        result["status"] = "INVALID_COMPILE"
        result["log"] = "could not find a class declaration in junit_code"
        return result
    class_fqcn = f"{package}.{class_name}" if package else class_name

    buggy_dir = workspaces.buggy_dir(bug_id)
    fixed_dir = workspaces.fixed_oracle_dir(bug_id)
    dir_src_tests = d4j.export(buggy_dir, "dir.src.tests")
    scratch = workspaces.gen_tests_dir(patch_id) / class_name

    # Each workspace (fixed/buggy/candidate) gets its OWN dir.bin.tests/cp.test export, computed right after
    # that workspace's own compile. defects4j export bakes ABSOLUTE paths into cp.test pointing at that specific
    # checkout's compiled classes; reusing one workspace's export for another silently links against the wrong
    # compiled CategoryPlot.class (confirmed directly: reusing fixed's cp.test for the buggy run made the buggy
    # execution actually load fixed's compiled classes, masking a real FAIL as a false PASS).
    fixed_run = _prepare_run_dir(fixed_dir, scratch / "fixed")
    ok, log = _inject_and_compile(fixed_run, dir_src_tests, class_fqcn, test_item["junit_code"])
    if not ok:
        result["status"] = "INVALID_COMPILE"
        result["log"] = log[-2000:]
        return result
    fixed_bin_tests, fixed_cp = d4j.export(fixed_run, "dir.bin.tests"), d4j.export(fixed_run, "cp.test")

    fixed_runs = [_run_class(fixed_run, fixed_bin_tests, fixed_cp, class_fqcn, runner_class)]
    if fixed_runs[0][0] == "TIMEOUT":
        result["status"] = "TIMEOUT"
        return result
    if fixed_runs[0][0] != "PASS":
        result["status"] = "INVALID_ORACLE"
        result["log"] = fixed_runs[0][1]
        return result

    buggy_run_dir = _prepare_run_dir(buggy_dir, scratch / "buggy")
    ok, log = _inject_and_compile(buggy_run_dir, dir_src_tests, class_fqcn, test_item["junit_code"])
    if not ok:
        # compiled against fixed but not buggy (e.g. references a symbol only the fix introduces) -> treat as
        # an invalid oracle, not our failure: the test cannot even run against the unpatched code.
        result["status"] = "INVALID_ORACLE"
        result["log"] = f"compiled on fixed but not on buggy: {log[-1000:]}"
        return result
    buggy_bin_tests, buggy_cp = d4j.export(buggy_run_dir, "dir.bin.tests"), d4j.export(buggy_run_dir, "cp.test")

    buggy_runs = [_run_class(buggy_run_dir, buggy_bin_tests, buggy_cp, class_fqcn, runner_class)]
    if buggy_runs[0][0] == "TIMEOUT":
        result["status"] = "TIMEOUT"
        return result
    if buggy_runs[0][0] == "PASS":
        result["status"] = "VALID_NON_DISCRIMINATING"
        result["log"] = buggy_runs[0][1]
        return result

    # fixed PASS + buggy FAIL: two more repetitions each (protocol.yaml repetitions_per_execution: 3 total)
    for _ in range(2):
        fixed_runs.append(_run_class(fixed_run, fixed_bin_tests, fixed_cp, class_fqcn, runner_class))
        buggy_runs.append(_run_class(buggy_run_dir, buggy_bin_tests, buggy_cp, class_fqcn, runner_class))

    status = scores.counterexample_status(True, [r[0] for r in fixed_runs], [r[0] for r in buggy_runs])
    result["status"] = status
    if status != scores.VALID_BUG_REVEALING:
        result["log"] = f"fixed={[r[0] for r in fixed_runs]} buggy={[r[0] for r in buggy_runs]}"
        return result

    cand_run = _prepare_run_dir(candidate_dir, scratch / "candidate")
    ok, log = _inject_and_compile(cand_run, dir_src_tests, class_fqcn, test_item["junit_code"])
    if not ok:
        result["candidate_pass"] = None  # missing, never imputed 0/1 (protocol.yaml zero_valid: NA)
        result["log"] = f"stable bug-revealing test did not compile against candidate: {log[-1000:]}"
        return result
    cand_bin_tests, cand_cp = d4j.export(cand_run, "dir.bin.tests"), d4j.export(cand_run, "cp.test")
    cand_status, cand_log = _run_class(cand_run, cand_bin_tests, cand_cp, class_fqcn, runner_class)
    result["candidate_pass"] = (cand_status == "PASS") if cand_status != "TIMEOUT" else False  # timeout = not passed
    result["log"] = cand_log
    return result


def run_counterexamples(patch_id, model="claude-haiku-4-5", k=K):
    import anthropic
    client = anthropic.Anthropic()

    with open(d4j.MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    bug_id = row["bug_id"]

    with open(d4j.D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
        d4j_row = next(r for r in csv.DictReader(f) if r["bug_id"] == bug_id)
    trigger_tests = d4j_row["trigger_tests"].split(";") if d4j_row["trigger_tests"] else []
    if not trigger_tests:
        raise RuntimeError(f"no trigger tests recorded for {bug_id}; run d4j.py --bug first")

    buggy_dir = workspaces.buggy_dir(bug_id)
    diff_path = ROOT / row["normalized_patch_location"]
    with open(diff_path, encoding="utf-8", errors="replace", newline="") as f:
        candidate_diff = f.read().replace("\r\n", "\n")

    package, junit_style, runner_class = detect_test_style(buggy_dir, trigger_tests[0])
    context_items, context_errors = context.extract(buggy_dir, d4j_row["dir_src_classes"], candidate_diff)

    import semantic  # reuse the same failure-message reader/caps
    failure_messages = semantic.read_failure_messages(bug_id)
    patch_meta = {"patch_id": patch_id, "APR_tool": row["APR_tool"],
                  "original_dataset_location": row["original_dataset_location"]}
    req = request_builders.build_counterexample_request(
        patch_meta, candidate_diff, ";".join(trigger_tests), failure_messages, context_items,
        test_package=package, junit_style=junit_style, k=k, known_tools=dataset.known_apr_tools(),
        fingerprint_hashes=d4j.load_fingerprint(patch_id), allowed_source_text=candidate_diff)

    resp, latency, attempts, settings, err = llm_client.send(client, req, model)
    result = {"patch_id": patch_id, "bug_id": bug_id, "model": model, "latency_s": latency, "error": err,
              "context_errors": context_errors, "tests": []}
    if resp is None:
        return result

    generated = json.loads(resp.content[0].text)["tests"]
    candidate_dir = workspaces.candidate_dir(patch_id)
    if not candidate_dir.exists():
        result["error"] = "candidate workspace missing; run d4j.py --patch first"
        return result

    for item in generated:
        result["tests"].append(validate_one_test(patch_id, bug_id, item, package, runner_class, candidate_dir))

    s_cex, n_valid, n_passed = scores.s_cex(result["tests"])
    result["s_cex"] = s_cex
    result["n_valid"] = n_valid
    result["n_passed"] = n_passed
    return result


def _write_result(result):
    COUNTEREXAMPLE_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    row = {"patch_id": result["patch_id"], "bug_id": result["bug_id"], "model": result["model"],
           "s_cex": result.get("s_cex"), "n_valid": result.get("n_valid"), "n_passed": result.get("n_passed"),
           "n_generated": len(result["tests"]), "error": result["error"]}
    existing = []
    if COUNTEREXAMPLE_RESULTS.exists():
        with open(COUNTEREXAMPLE_RESULTS, newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["patch_id"] != result["patch_id"]]
    existing.append(row)
    with open(COUNTEREXAMPLE_RESULTS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerows(existing)
    CEX_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (CEX_RUNS_DIR / f"{result['patch_id']}.json").write_text(json.dumps(result, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True)
    ap.add_argument("--model", default="claude-haiku-4-5")
    args = ap.parse_args()
    result = run_counterexamples(args.patch, args.model)
    _write_result(result)
    print(json.dumps({k: v for k, v in result.items() if k != "tests"}, indent=2, default=str))
    for t in result["tests"]:
        print(t["name"], "->", t["status"], "candidate_pass:", t["candidate_pass"])


if __name__ == "__main__":
    main()
