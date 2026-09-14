"""Pre-request leakage guard. Every LLM request must pass `check_request` before it is sent.

What is checked (dynamic, data-derived prompt content only; fixed instruction text may legitimately say
"CORRECT or OVERFITTING"):
  1. ground-truth label annotations
  2. dataset suffix "-plausible"/"-plusible"
  3. archive folder names that encode labels
  4. APR tool identifiers from dataset metadata
  5. the patch's dataset path / patch_id
  6. references to the fixed-oracle workspace
  7. developer-fix fingerprint: hashes of non-trivial lines that exist only in the developer-fixed version
     (not in the buggy source, not in the candidate diff)

On any hit the request is aborted (LeakageError) and an entry is appended to logs/errors.jsonl.
Nothing is sanitized.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS = ROOT / "logs" / "errors.jsonl"

ARCHIVE_TOKENS = ("Dsame", "Ddifferent", "Dcorrect", "Doverfitting", "Patches_ICSE", "Patches_others")
LABEL_RES = [
    re.compile(r"\b(CORRECT|OVERFITTING|INCORRECT)\b"),
    re.compile(r"\b(ground[\s_-]*truth|correctness[\s_-]*label|overfitting[\s_-]*patch|correct[\s_-]*patch)\b", re.I),
    re.compile(r"\blabel(ed)?\s*[:=]\s*(correct|overfitting|incorrect)\b", re.I),
]
SUFFIX_RE = re.compile(r"-pl(?:a)?usible\b")
FIXED_ORACLE_RE = re.compile(r"fixed_oracle", re.I)
MIN_FINGERPRINT_CHARS = 12


class LeakageError(RuntimeError):
    pass


def normalize_line(line):
    return re.sub(r"\s+", " ", line).strip()


def _nontrivial(line):
    if len(line) < MIN_FINGERPRINT_CHARS:
        return False
    if line.startswith(("//", "/*", "*", "import ", "package ")):
        return False
    return bool(re.search(r"[A-Za-z0-9]", line))


def line_hash(line):
    return hashlib.sha256(normalize_line(line).encode()).hexdigest()


def developer_fix_fingerprint(buggy_source: str, fixed_source: str, candidate_diff: str) -> set:
    """Hashes of lines present only in the developer-fixed file. Called ONLY by oracle-side code.

    Lines that also occur in the buggy source or in the candidate diff are excluded, so a candidate that is
    textually identical to the developer fix does not trigger the guard (its text comes from the candidate).
    """
    buggy = {normalize_line(l) for l in buggy_source.splitlines()}
    cand = {normalize_line(l[1:]) for l in candidate_diff.splitlines() if l[:1] in ("+", "-", " ")}
    return {line_hash(l) for l in (normalize_line(x) for x in fixed_source.splitlines())
            if _nontrivial(l) and l not in buggy and l not in cand}


def find_leaks(dynamic_text: str, patch_meta: dict, known_tools, fingerprint_hashes=frozenset()):
    reasons = []
    for rx in LABEL_RES:
        if m := rx.search(dynamic_text):
            reasons.append(f"label annotation: {m.group(0)!r}")
    if m := SUFFIX_RE.search(dynamic_text):
        reasons.append(f"dataset suffix: {m.group(0)!r}")
    for tok in ARCHIVE_TOKENS:
        if tok in dynamic_text:
            reasons.append(f"archive folder token: {tok!r}")
    for tool in sorted(set(known_tools) | {patch_meta.get("APR_tool", "")} - {""}):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])", dynamic_text):
            reasons.append(f"APR tool identifier: {tool!r}")
    for key in ("patch_id", "original_dataset_location"):
        val = patch_meta.get(key)
        if val and val in dynamic_text:
            reasons.append(f"dataset metadata {key}")
    if FIXED_ORACLE_RE.search(dynamic_text):
        reasons.append("fixed-oracle path reference")
    if fingerprint_hashes:
        hits = sum(1 for l in dynamic_text.splitlines() if line_hash(l) in fingerprint_hashes)
        if hits:
            reasons.append(f"developer-fix fingerprint: {hits} line(s)")
    return reasons


def check_request(dynamic_text: str, patch_meta: dict, known_tools, fingerprint_hashes=frozenset(),
                  purpose="unspecified", errors_path=ERRORS):
    reasons = find_leaks(dynamic_text, patch_meta, known_tools, fingerprint_hashes)
    if reasons:
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        with open(errors_path, "a") as f:
            f.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "type": "LEAKAGE_ABORT",
                                "purpose": purpose, "patch_id": patch_meta.get("patch_id"),
                                "reasons": reasons}) + "\n")
        raise LeakageError(f"{patch_meta.get('patch_id')}: {reasons}")
    return True
