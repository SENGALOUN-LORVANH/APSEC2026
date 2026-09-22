"""GumTree AST-based S_edit (protocol.yaml scores.S_edit.primary), Stage 2B.

For each source file changed by the candidate diff, run the GumTree tool (tools/java) on the buggy vs
candidate file, passing the PRECISE changed buggy line numbers (not the padded hunk range) so the AST-node
denominator counts only the methods the patch actually touches. S_edit_ast = min(1, sum(edit_actions) /
sum(ast_nodes_of_changed_buggy_methods)). Tool/parse failure -> None (MISSING), never 0 (protocol
analyzer_failure policy).
"""
import csv
import json
import re
import subprocess
from pathlib import Path

import d4j
import workspaces

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "tools" / "java" / "target" / "context-extractor.jar"
MANIFEST = ROOT / "data" / "dataset_manifest.csv"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def changed_buggy_lines_by_file(diff_text):
    """-> {relative_file_path: sorted set of buggy line numbers touched}. A '-' line is the buggy line it
    removes; a '+' line (pure insertion) is attributed to the buggy line just before the insertion point."""
    files = {}
    cur, buggy_ln = None, 0
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            path = line[4:].strip()
            cur = path[1:] if path.startswith("/") else path
            files.setdefault(cur, set())
            continue
        if line.startswith("+++"):
            continue
        m = HUNK_RE.match(line)
        if m:
            buggy_ln = int(m.group(1))
            continue
        if cur is None:
            continue
        if line.startswith("-"):
            files[cur].add(buggy_ln)
            buggy_ln += 1
        elif line.startswith("+"):
            files[cur].add(max(buggy_ln - 1, 1))  # insertion: attribute to preceding buggy line
        else:  # context line
            buggy_ln += 1
    return {f: sorted(v) for f, v in files.items() if v}


def _ranges_csv(lines):
    return ",".join(f"{n}-{n}" for n in lines)


def _run_tool(buggy_file, candidate_file, ranges_csv, timeout=120):
    try:
        p = subprocess.run(["java", "-cp", str(JAR), "apsec.GumTreeEdit",
                            str(buggy_file), str(candidate_file), ranges_csv],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"gumtree timed out after {timeout}s"
    out = p.stdout.strip()
    if not out:
        return None, f"gumtree no output (exit {p.returncode}): {p.stderr.strip()[:200]}"
    try:
        d = json.loads(out.splitlines()[-1])
    except json.JSONDecodeError as e:
        return None, f"gumtree unparseable output: {e}: {out[:200]}"
    if "error" in d:
        return None, f"gumtree: {d['error']}"
    return d, None


def s_edit_gumtree(patch_id, bug_id):
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["patch_id"] == patch_id)
    diff_path = ROOT / row["normalized_patch_location"]
    diff_text = diff_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    by_file = changed_buggy_lines_by_file(diff_text)
    if not by_file:
        return {"s_edit_ast": None, "error": "no changed source lines parsed from diff", "files": []}

    buggy_root = workspaces.buggy_dir(bug_id)
    cand_root = workspaces.candidate_dir(patch_id)
    total_actions, total_nodes, per_file, errors = 0, 0, [], []
    for rel, lines in by_file.items():
        buggy_file = buggy_root / rel
        cand_file = cand_root / rel
        if not buggy_file.exists() or not cand_file.exists():
            errors.append(f"{rel}: file missing (buggy={buggy_file.exists()} cand={cand_file.exists()})")
            continue
        d, err = _run_tool(buggy_file, cand_file, _ranges_csv(lines))
        if err:
            errors.append(f"{rel}: {err}")
            continue
        per_file.append({"file": rel, **d})
        total_actions += d.get("edit_actions", 0)
        total_nodes += d.get("ast_nodes_changed_methods", 0)

    if total_nodes == 0:
        return {"s_edit_ast": None, "edit_actions": total_actions, "ast_nodes": total_nodes,
                "files": per_file, "error": "; ".join(errors) if errors else "no changed-method AST nodes found"}
    return {"s_edit_ast": min(1.0, total_actions / total_nodes), "edit_actions": total_actions,
            "ast_nodes": total_nodes, "files": per_file, "error": "; ".join(errors) if errors else None}


if __name__ == "__main__":
    import sys
    print(json.dumps(s_edit_gumtree(sys.argv[1], sys.argv[2]), indent=2))
