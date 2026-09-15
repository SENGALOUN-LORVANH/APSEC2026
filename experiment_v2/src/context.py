"""Source-context extraction for RQ condition C (Step 9). Parses the candidate diff's changed line ranges
(buggy/old side) and calls tools/java/context-extractor.jar (JavaParser) against the buggy checkout only --
never fixed_oracle -- to find the enclosing method(s), containing class declaration, and imports.

Thin/first-pass scope: extracts changed_method, class declaration + method signatures, and imports. Does NOT
yet resolve referenced fields or direct helper methods (protocol context_priority items 5-6); see
reports/CONTEXT_EXTRACTOR_NOTES.md.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import workspaces
from context_budget import ContextItem
from d4j import _strip_src_prefix

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "tools" / "java" / "target" / "context-extractor.jar"
JDK21 = os.environ.get("JDK21", "/usr/lib/jvm/java-21-openjdk-amd64")

FILE_HEADER_RE = re.compile(r"^--- (\S+)")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def changed_ranges_by_file(diff_text):
    """-> {relpath (post-prefix-strip): [(lo, hi), ...]} using the diff's old/buggy-side line numbers."""
    ranges = {}
    current = None
    for line in diff_text.splitlines():
        m = FILE_HEADER_RE.match(line)
        if m:
            current = _strip_src_prefix(m.group(1))
            continue
        m = HUNK_RE.match(line)
        if m:
            lo = int(m.group(1))
            length = int(m.group(2)) if m.group(2) else 1
            hi = lo + max(length - 1, 0)
            ranges.setdefault(current, []).append((lo, hi))
    return ranges


def _run_extractor(java_file: Path, ranges_csv: str, timeout=60):
    env = os.environ.copy()
    env["PATH"] = f"{JDK21}/bin:" + env.get("PATH", "")
    p = subprocess.run(["java", "-jar", str(JAR), str(java_file), ranges_csv],
                        capture_output=True, text=True, env=env, timeout=timeout)
    try:
        return json.loads(p.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"error": f"bad extractor output: stdout={p.stdout[:200]!r} stderr={p.stderr[:200]!r}"}


def extract(buggy_dir, src_classes_rel, diff_text):
    """-> (items, errors). items: list[ContextItem] for condition C. Never touches fixed_oracle/."""
    items = []
    errors = []
    class_decls = []
    signatures = []
    imports = set()

    for rel, ranges in changed_ranges_by_file(diff_text).items():
        if rel is None:
            errors.append("diff header path did not match any known source-root prefix")
            continue
        java_file = Path(buggy_dir) / src_classes_rel / rel
        workspaces.assert_not_fixed_oracle(java_file)
        if not java_file.exists():
            errors.append(f"source file not found in buggy checkout: {rel}")
            continue
        ranges_csv = ",".join(f"{lo}-{hi}" for lo, hi in ranges)
        result = _run_extractor(java_file, ranges_csv)
        if "error" in result:
            errors.append(f"{rel}: {result['error']}")
            continue
        if result.get("class_declaration"):
            class_decls.append(result["class_declaration"])
        imports.update(result.get("imports", []))
        for m in result.get("methods", []):
            label = f"{m['containing_class']}.{m['signature']}"
            items.append(ContextItem("changed_method", m["source"], source_path=str(java_file), label=label))
            signatures.append(f"{m['containing_class']}: {m['signature']}")
        if not result.get("methods"):
            errors.append(f"{rel}: no enclosing method found for changed lines {ranges}")

    sig_text = "\n".join(dict.fromkeys(class_decls + signatures))
    if sig_text:
        items.append(ContextItem("signatures", sig_text, label="class+method signatures"))
    if imports:
        items.append(ContextItem("imports_types", "\n".join(sorted(imports)), label="imports"))
    return items, errors
