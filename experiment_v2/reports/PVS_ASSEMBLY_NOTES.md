# S_edit, S_vuln, and PVS* Assembly (Steps 18-19, 22) — thin pass

## S_edit (`src/edit.py`)
LOC fallback only (protocol.yaml `S_edit.fallback`): `changed_exec_loc / method_exec_loc`, both counting only
non-blank, non-comment-only lines. GumTree AST-diff (primary) is **not** wired up — deferred, same as CFG/PDG.

## S_vuln (`src/vuln.py`)
Runs real SpotBugs + FindSecBugs (`spotbugs analyze -textui -low`) against the whole `dir.bin.classes` output
(analyzing a single class file left inherited/interface types unresolvable — confirmed directly: `Could not
find XClass object for org/jfree/chart/plot/Plot`; analyzing the whole compiled-classes dir fixed it).

**Severity mapping decision** (protocol.yaml requires inspecting real output before deciding): SpotBugs's own
priority letter (H/M/L, printed by `-textui`) is used directly as HIGH/MEDIUM/LOW. This is a native SpotBugs
classification (not something we invented) — the weighted scheme is adopted as primary, per the decision rule.
FindSecBugs' own internal-class warnings (a classpath artifact where the plugin's own classes get analyzed
too) are filtered out (`h3xstream/findsecbugs` in the class/description).

Warning identity key: `(bug_type, class, method)` — protocol.yaml's 4-field key also wants
field/variable disambiguation; deferred (thin pass).

## PVS* assembly (`src/assemble_pvs.py`)
Reads S_sem/S_cex from their already-computed results CSVs (no extra LLM calls), computes S_edit/S_vuln
locally, calls `src/pvs.py`'s `score_row` (shifted-renormalized strategy, per protocol's approved choice).

**Placeholder weights: alpha=beta=gamma=delta=0.25**, clearly not calibrated — RQ2's Bradley-Terry weight
calibration from real human preferences is still PENDING (`preferences.status: PENDING until real human data
exist`). Exists only so the full PVS* pipeline can be exercised end-to-end before real weights exist. Any
number produced with these weights is an engineering value, never a paper result.

## Validated end-to-end on real data (Chart-19 / patch1-Chart-19-ACS)
All four components computed for real: S_sem=0.05, S_cex=1.0, S_edit=0.286 (LOC), S_vuln=0 (no new warnings).
PVS* (shifted, placeholder weights) = 0.691; the complete-only paper formula = 0.191 (all four components were
present, so both are computable). `ground_truth_label` from the manifest is carried alongside for later
comparison, never fed into scoring.

This closes out Steps 5-13 + 18/19/22 for one patch: environment -> Defects4J checkout/patch -> context
extraction -> semantic LLM call -> counterexample LLM call + oracle -> S_vuln -> S_edit -> PVS*, entirely on
real data, with three real bugs found and fixed along the way (documented in the earlier D4J_DRIVER_NOTES.md
and ORACLE_RUNNER_NOTES.md). Next: scale from 1 patch to the 10-patch smoke test (Step 14).
