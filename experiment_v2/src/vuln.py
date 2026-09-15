"""SpotBugs + FindSecBugs S_vuln computation (Steps 18-19).

Severity mapping decision (protocol.yaml scores.S_vuln.decision_rule, made after inspecting real output on
Chart-19): SpotBugs's own priority letter (H/M/L, printed by `-textui`) is used directly as the HIGH/MEDIUM/LOW
mapping. This is a native, defensible severity signal (SpotBugs's own classification), simpler than parsing
the 1-20 numeric rank from XML output but equally legitimate -> the WEIGHTED scheme is primary, not the equal-
weight sensitivity fallback.
"""
import os
import re
import subprocess
from pathlib import Path

import d4j
import scores

JDK21 = os.environ.get("JDK21", "/usr/lib/jvm/java-21-openjdk-amd64")
SPOTBUGS_PLUGIN = "/opt/spotbugs/plugin/findsecbugs-plugin-1.14.0.jar"
WARNING_RE = re.compile(r"^([HML])\s+(\w)\s+(\w+):\s+(.*?)\s+At\s+(\S+):\[(.*)\]\s*$")
PRIORITY_TO_SEVERITY = {"H": "HIGH", "M": "MEDIUM", "L": "LOW"}
SEVERITY_WEIGHTS = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.25}  # protocol.yaml provisional primary weights

# Method name best-effort extraction from the human-readable description, used only as a dedup key
# (protocol.yaml record_fields wants (bug_type, class, method_signature, field_or_variable); this thin pass
# uses (bug_type, class, method) -- field/variable disambiguation deferred).
METHOD_RE = re.compile(r"([\w.$]+)\.([\w<>]+)\(")


def _env():
    e = os.environ.copy()
    e["JAVA_HOME"] = JDK21
    e["PATH"] = f"{JDK21}/bin:" + e.get("PATH", "")
    return e


def parse_warnings(output):
    """-> list of warning dicts. Skips FindSecBugs' own internal-class warnings (a known classpath artifact:
    the plugin jar's classes get analyzed too unless excluded; identifiable by their h3xstream package)."""
    warnings = []
    for line in output.splitlines():
        m = WARNING_RE.match(line)
        if not m:
            continue
        priority, category, wtype, desc, location, lines = m.groups()
        if "h3xstream.findsecbugs" in desc or "h3xstream/findsecbugs" in location:
            continue
        cls = location.rsplit(".java", 1)[0].replace("/", ".")
        mm = METHOD_RE.search(desc)
        method = mm.group(2) if mm else ""
        warnings.append({"bug_type": wtype, "category": category, "priority": priority,
                         "severity": PRIORITY_TO_SEVERITY.get(priority, "LOW"),
                         "class": cls, "method": method, "location": f"{location}:{lines}",
                         "description": desc})
    return warnings


def run_spotbugs(workdir, timeout=180):
    """-> (warnings, error). error is None on success; warnings is [] (not None) only on a genuine empty
    result, never conflated with an analyzer failure (protocol.yaml analyzer_failure: missing, never zero)."""
    dir_bin_classes = d4j.export(workdir, "dir.bin.classes")
    cp_compile = d4j.export(workdir, "cp.compile")
    if not dir_bin_classes:
        return None, "export dir.bin.classes failed"
    target = Path(workdir) / dir_bin_classes
    if not target.exists():
        return None, f"compiled classes dir not found: {target}"
    try:
        p = subprocess.run(["spotbugs", "analyze", "-textui", "-low", "-auxclasspath", cp_compile or "",
                           "-pluginList", SPOTBUGS_PLUGIN, str(target)],
                           capture_output=True, text=True, env=_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"spotbugs timed out after {timeout}s"
    return parse_warnings(p.stdout + p.stderr), None


def warning_key(w):
    return (w["bug_type"], w["class"], w["method"])


def compute_s_vuln(buggy_dir, candidate_dir):
    """-> dict with new_warnings, severities, s_vuln, and per-side analyzer errors."""
    buggy_warnings, buggy_err = run_spotbugs(buggy_dir)
    cand_warnings, cand_err = run_spotbugs(candidate_dir)
    if buggy_err or cand_err:
        return {"s_vuln": None, "new_warnings": [], "buggy_error": buggy_err, "candidate_error": cand_err}

    buggy_keys = [warning_key(w) for w in buggy_warnings]
    cand_by_key = {warning_key(w): w for w in cand_warnings}
    cand_keys = list(cand_by_key.keys())
    new_keys = scores.new_warnings(buggy_keys, cand_keys)
    new_severities = [cand_by_key[k]["severity"] for k in new_keys if k in cand_by_key]
    s_vuln = scores.s_vuln(new_severities, SEVERITY_WEIGHTS)
    return {"s_vuln": s_vuln, "new_warnings": [dict(cand_by_key[k]) for k in new_keys if k in cand_by_key],
            "n_buggy_warnings": len(buggy_warnings), "n_candidate_warnings": len(cand_warnings),
            "buggy_error": None, "candidate_error": None}
