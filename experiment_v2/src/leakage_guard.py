"""Pre-request leakage guard. Every LLM request is built by `request_builders.py`, which calls `check_request`;
`llm_client.send` refuses any request without a matching guard receipt.

The guard targets METADATA leakage, not ordinary words. "correct", "incorrect", "OVERFITTING" etc. may legitimately
occur in comments, identifiers, exception messages, or bug information and are NOT rejected on their own.

Rejected (in dynamic, data-derived prompt content):
  1. label metadata fields/annotations: ground_truth_label, original_label, correctness_label, "label: correct" ...
  2. archive folder names that encode labels (Dsame, Ddifferent, Dcorrect, Doverfitting, Patches_ICSE, Patches_others)
  3. dataset filename suffix "<name>-plausible" / "-plusible"
  4. APR tool identifiers from dataset metadata (unless the token also occurs in the buggy source / candidate diff)
  5. the patch's dataset path or patch_id
  6. fixed-oracle paths
  7. developer-fix fingerprint: hashes of non-trivial lines present only in the developer-fixed version

On any hit: LeakageError + entry in logs/errors.jsonl. Nothing is sanitized.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS = ROOT / "logs" / "errors.jsonl"

ARCHIVE_TOKENS = ("Dsame", "Ddifferent", "Dcorrect", "Doverfitting", "Patches_ICSE", "Patches_others")
METADATA_RES = [
    re.compile(r"\b(ground[_ -]?truth[_ -]?label|original_label|label_sensitivity|correctness[_ -]?label)\b", re.I),
    re.compile(r"\b(correction_status|included_primary|included_sensitivity)\b"),
    re.compile(r"\b(ground[_ -]?truth|label(?:ed)?)\s*[:=]\s*[\"']?(correct|overfitting|incorrect)\b", re.I),
]
SUFFIX_RE = re.compile(r"[A-Za-z0-9]-pl(?:a)?usible\b")
FIXED_ORACLE_RE = re.compile(r"fixed_oracle")
MIN_FINGERPRINT_CHARS = 12


class LeakageError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuardReceipt:
    patch_id: str
    purpose: str
    dynamic_sha256: str


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_line(line):
    return re.sub(r"\s+", " ", line).strip()


def _nontrivial(line):
    if len(line) < MIN_FINGERPRINT_CHARS or line.startswith(("//", "/*", "*", "import ", "package ")):
        return False
    return bool(re.search(r"[A-Za-z0-9]", line))


def line_hash(line):
    return sha256(normalize_line(line))


def developer_fix_fingerprint(buggy_source: str, fixed_source: str, candidate_diff: str) -> set:
    """Hashes of lines present only in the developer-fixed file. Called ONLY by oracle-side code.

    Lines also present in the buggy source or the candidate diff are excluded, so a candidate textually identical
    to the developer fix does not trigger the guard (its text comes from the candidate).
    """
    buggy = {normalize_line(l) for l in buggy_source.splitlines()}
    cand = {normalize_line(l[1:]) for l in candidate_diff.splitlines() if l[:1] in ("+", "-", " ")}
    return {line_hash(l) for l in (normalize_line(x) for x in fixed_source.splitlines())
            if _nontrivial(l) and l not in buggy and l not in cand}


def _word_re(token):
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])")


def find_leaks(dynamic_text, patch_meta, known_tools, fingerprint_hashes=frozenset(), allowed_source_text=""):
    reasons = []
    for rx in METADATA_RES:
        if m := rx.search(dynamic_text):
            reasons.append(f"label metadata: {m.group(0)!r}")
    for tok in ARCHIVE_TOKENS:
        if _word_re(tok).search(dynamic_text):
            reasons.append(f"archive folder token: {tok!r}")
    if m := SUFFIX_RE.search(dynamic_text):
        reasons.append(f"dataset filename suffix: {m.group(0)!r}")
    for tool in sorted((set(known_tools) | {patch_meta.get("APR_tool") or ""}) - {""}):
        rx = _word_re(tool)
        if rx.search(dynamic_text) and not rx.search(allowed_source_text):
            reasons.append(f"APR tool identifier: {tool!r}")
    for key in ("patch_id", "original_dataset_location", "normalized_patch_location"):
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


def check_request(dynamic_text, patch_meta, known_tools, fingerprint_hashes=frozenset(), purpose="unspecified",
                  allowed_source_text="", errors_path=ERRORS) -> GuardReceipt:
    reasons = find_leaks(dynamic_text, patch_meta, known_tools, fingerprint_hashes, allowed_source_text)
    if reasons:
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        with open(errors_path, "a") as f:
            f.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "type": "LEAKAGE_ABORT",
                                "purpose": purpose, "patch_id": patch_meta.get("patch_id"),
                                "reasons": reasons}) + "\n")
        raise LeakageError(f"{patch_meta.get('patch_id')}: {reasons}")
    return GuardReceipt(patch_meta.get("patch_id"), purpose, sha256(dynamic_text))
