"""Stage 2B static analysis (Step 6), run on the 48 pilot patches -- NO new LLM calls.

Per patch, on the already-checked-out buggy and candidate workspaces:
  - S_edit (GumTree AST-diff, primary)          -> gumtree_edit.s_edit_gumtree
  - S_vuln (SpotBugs/FindSecBugs, CHANGED classes only, buggy vs candidate) -> vuln.compute_s_vuln_changed_classes
  - CFG / dataflow features for each changed method, buggy vs candidate (SootUp) -> apsec.CfgFeatures
    with the analysis-level hierarchy stored per candidate (DATAFLOW / CFG_AST / FAILED; PDG not computed by
    this tool, so DATAFLOW is the ceiling here -- Level 3 (CFG_AST) is never called PDG).

Analyzer failures are recorded as MISSING (None), never 0 (protocol analyzer_failure policy). Writes
results/stage2b/<patch_id>.json and results/stage2b_features.csv.
"""
import csv
import json
import subprocess
from pathlib import Path

import d4j
import gumtree_edit
import vuln
import workspaces

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "tools" / "java" / "target" / "context-extractor.jar"
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
PILOT_SAMPLE = ROOT / "results" / "pilot_sample.csv"
STAGE2B_DIR = ROOT / "results" / "stage2b"
FEATURES_CSV = ROOT / "results" / "stage2b_features.csv"
LEVEL_ORDER = {"FAILED": 0, "CFG_AST": 1, "DATAFLOW": 2, "PDG": 3}


def _dsrc(bug_id):
    with open(d4j.D4J_STATUS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bug_id"] == bug_id:
                return r["dir_src_classes"]
    return ""


def rel_class_path(rel_source_path, dir_src_classes):
    """'source/org/jfree/.../CategoryPlot.java' + dir_src_classes 'source' -> 'org/jfree/.../CategoryPlot'."""
    p = rel_source_path
    prefix = dir_src_classes.strip("/") + "/" if dir_src_classes else ""
    if prefix and p.startswith(prefix):
        p = p[len(prefix):]
    return p[:-5] if p.endswith(".java") else p


def cfg_features(bin_dir, fq_dotted, method, timeout=120):
    try:
        p = subprocess.run(["java", "-cp", str(JAR), "apsec.CfgFeatures", str(bin_dir), fq_dotted, method],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"analysis_level": "FAILED", "error": f"cfg timed out after {timeout}s"}
    out = p.stdout.strip()
    if not out:
        return {"analysis_level": "FAILED", "error": f"cfg no output: {p.stderr.strip()[:150]}"}
    try:
        return json.loads(out.splitlines()[-1])
    except json.JSONDecodeError as e:
        return {"analysis_level": "FAILED", "error": f"cfg unparseable: {e}"}


def _agg_cfg(bin_dir, methods_by_class):
    """Sum CFG features over changed methods; analysis_level = min level achieved (worst case)."""
    agg = {"stmts": 0, "cfg_edges": 0, "branch_points": 0, "cyclomatic_complexity": 0,
           "def_count": 0, "use_count": 0, "defuse_pairs": 0}
    level = "PDG"
    per_method, any_ok = [], False
    for fq_dotted, methods in methods_by_class.items():
        for method in methods:
            r = cfg_features(bin_dir, fq_dotted, method)
            per_method.append({"class": fq_dotted, "method": method, **r})
            lvl = r.get("analysis_level", "FAILED")
            level = lvl if LEVEL_ORDER[lvl] < LEVEL_ORDER[level] else level
            if lvl != "FAILED":
                any_ok = True
                for k in agg:
                    agg[k] += r.get(k, 0) or 0
    if not per_method:
        return {"analysis_level": "FAILED", "per_method": []}
    return {"analysis_level": level if any_ok else "FAILED", **agg, "per_method": per_method}


def run_one(patch_id, bug_id):
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    diff_text = (ROOT / row["normalized_patch_location"]).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    dir_src = _dsrc(bug_id)
    by_file = gumtree_edit.changed_buggy_lines_by_file(diff_text)

    # S_edit (GumTree, primary) -- also yields the changed method names per file
    edit = gumtree_edit.s_edit_gumtree(patch_id, bug_id)
    methods_by_class = {}
    changed_rel_classes = []
    for fentry in edit.get("files", []):
        rel_cls = rel_class_path(fentry["file"], dir_src)
        changed_rel_classes.append(rel_cls)
        methods_by_class[rel_cls.replace("/", ".")] = fentry.get("changed_methods", [])
    # files GumTree couldn't process still count as changed classes for SpotBugs scope
    for rel in by_file:
        rc = rel_class_path(rel, dir_src)
        if rc not in changed_rel_classes:
            changed_rel_classes.append(rc)

    buggy_dir = workspaces.buggy_dir(bug_id)
    cand_dir = workspaces.candidate_dir(patch_id)

    # S_vuln on changed classes only
    svuln = vuln.compute_s_vuln_changed_classes(buggy_dir, cand_dir, changed_rel_classes)

    # CFG features buggy vs candidate
    buggy_bin = d4j.export(buggy_dir, "dir.bin.classes")
    cand_bin = d4j.export(cand_dir, "dir.bin.classes")
    cfg_buggy = _agg_cfg(Path(buggy_dir) / buggy_bin, methods_by_class) if buggy_bin else {"analysis_level": "FAILED", "error": "no bin dir"}
    cfg_cand = _agg_cfg(Path(cand_dir) / cand_bin, methods_by_class) if cand_bin else {"analysis_level": "FAILED", "error": "no bin dir"}

    def d(k):
        if cfg_buggy.get("analysis_level") == "FAILED" or cfg_cand.get("analysis_level") == "FAILED":
            return None
        return cfg_cand.get(k, 0) - cfg_buggy.get(k, 0)

    result = {
        "patch_id": patch_id, "bug_id": bug_id,
        "s_edit_ast": edit.get("s_edit_ast"), "s_edit_ast_actions": edit.get("edit_actions"),
        "s_edit_ast_nodes": edit.get("ast_nodes"), "s_edit_error": edit.get("error"),
        "s_vuln_changed": svuln.get("s_vuln"), "s_vuln_new_warning_count": len(svuln.get("new_warnings", [])),
        "s_vuln_buggy_error": svuln.get("buggy_error"), "s_vuln_candidate_error": svuln.get("candidate_error"),
        "changed_classes": changed_rel_classes,
        "analysis_level": min([cfg_buggy.get("analysis_level", "FAILED"), cfg_cand.get("analysis_level", "FAILED")],
                              key=lambda x: LEVEL_ORDER[x]),
        "cfg_buggy": cfg_buggy, "cfg_candidate": cfg_cand,
        "d_cyclomatic": d("cyclomatic_complexity"), "d_stmts": d("stmts"),
        "d_branch_points": d("branch_points"), "d_cfg_edges": d("cfg_edges"), "d_defuse_pairs": d("defuse_pairs"),
        "vuln_detail": svuln,
    }
    return result


CSV_FIELDS = ["patch_id", "bug_id", "s_edit_ast", "s_edit_ast_actions", "s_edit_ast_nodes",
              "s_vuln_changed", "s_vuln_new_warning_count", "analysis_level",
              "d_cyclomatic", "d_stmts", "d_branch_points", "d_cfg_edges", "d_defuse_pairs",
              "s_edit_error", "s_vuln_buggy_error", "s_vuln_candidate_error"]


def _write(result):
    STAGE2B_DIR.mkdir(parents=True, exist_ok=True)
    (STAGE2B_DIR / f"{result['patch_id']}.json").write_text(json.dumps(result, indent=2, default=str))
    row = {k: result.get(k) for k in CSV_FIELDS}
    existing = []
    if FEATURES_CSV.exists():
        with open(FEATURES_CSV, newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["patch_id"] != result["patch_id"]]
    existing.append(row)
    with open(FEATURES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(existing)


def main():
    import sys
    if len(sys.argv) == 3:
        r = run_one(sys.argv[1], sys.argv[2]); _write(r)
        print(json.dumps({k: r.get(k) for k in CSV_FIELDS}, default=str)); return
    with open(PILOT_SAMPLE, newline="", encoding="utf-8") as f:
        sample = [(r["patch_id"], r["bug_id"]) for r in csv.DictReader(f)]
    for i, (pid, bug) in enumerate(sample, 1):
        try:
            r = run_one(pid, bug); _write(r)
            print(f"[{i}/{len(sample)}] {pid}: S_edit={r['s_edit_ast']} S_vuln={r['s_vuln_changed']} "
                  f"level={r['analysis_level']} d_cyc={r['d_cyclomatic']}", flush=True)
        except Exception as e:  # noqa: BLE001 - recorded, never hidden
            print(f"[{i}/{len(sample)}] {pid}: ERROR {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    main()
