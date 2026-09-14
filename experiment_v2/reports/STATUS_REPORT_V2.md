# v2 Reconstruction — Status Report

**Date:** 2026-09-15 · **Commit:** `cdc88b2` · **v1 snapshot tag:** `rebuild-v1-snapshot`
**Development host:** macOS 26.6.2, Apple M2, 16 GB (coding/tests only — not the authoritative machine)
**Authoritative machine:** lab PC (Ubuntu / WSL2) — not yet used

> **No experimental results in this report.** It records infrastructure, dataset reconstruction, and design.
> Any v1 pilot number referenced is **PRELIMINARY — NOT PAPER RESULTS**.
> Every count below comes from a generated file named in the section.

---

## 1. Summary

| Area | State |
|---|---|
| v1 preserved | Done — `experiment/` untouched, tag `rebuild-v1-snapshot` |
| Dataset rebuilt from verified source, both label policies | Done (Mac); re-run on PC required |
| Leakage guard | Implemented + tested; not yet wired into request builders |
| Scores, PVS, evaluation metrics | Implemented + tested (pure Python) |
| Protocol | Drafted, **not frozen** |
| Docker environment | Defined, **not built** |
| Defects4J, counterexamples, CFG/PDG, SpotBugs, context extraction | **Not started — require the PC** |
| Human preference data | **Do not exist**; tool not yet built |
| Smoke test / pilot / full run | **Not run** |
| Unit tests | 52 passing |

---

## 2. Pre-flight gates

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | Repository inspection | PASS | `reports/IMPLEMENTATION_ASSESSMENT.md` |
| 2 | v1 preserved | PASS | tag `rebuild-v1-snapshot` |
| 3 | Environment recorded | PENDING — PC | `src/record_environment.py` refuses authoritative mode off Linux |
| 4 | Dataset reproduced from source | PASS (Mac) | `data/DATASET_PROVENANCE.md`, MD5 verified |
| 5 | Leakage guard | PARTIAL | `src/leakage_guard.py`, 12 tests; wiring pending |
| 6 | Buggy/fixed Defects4J environments | PENDING — PC | — |
| 7 | Source-context extraction | PENDING | — |
| 8 | Semantic evaluator structured output | PENDING | v2 prompt drafted |
| 9 | Counterexamples compile | PENDING — PC | — |
| 10 | Tests pass fixed / fail buggy | PENDING — PC | — |
| 11 | Candidate execution | PENDING — PC | — |
| 12 | Real CFG extraction | PENDING — PC | — |
| 13 | PDG / data-flow | PENDING — PC | — |
| 14 | Warning comparison | PENDING — PC | — |
| 15 | Component scores reproducible | PARTIAL | score functions tested; no real inputs yet |
| 16 | 10-patch end-to-end | PENDING — PC | — |
| 17 | No manuscript numbers in results | PASS so far | no generated result contains draft values |
| 18 | Protocol frozen | PENDING | `protocol/` drafts |
| 19 | 50-patch pilot | PENDING — PC | — |

**The full experiment is blocked.**

---

## 3. Dataset (sources: `results/dataset_stats.json`, `results/*.csv`)

**Source:** Wang et al., ASE 2020, Zenodo 3730599, `Patches.zip`, MD5 `11203b88e6ae8a657757c6b5842d5a46` (verified).
Patch files parsed: **908**.

### 3.1 Label policies
| | Primary | Sensitivity |
|---|---|---|
| Rule | Apply dataset-author corrections; exclude borderline, failed plausibility, unlabeled | Exclude corrected, borderline, failed plausibility, unlabeled |
| Patches | **899** | **887** |
| Correct | 245 | 245 |
| Overfitting | 654 | 642 |
| Overfitting rate | 0.728 | 0.724 |
| Bugs | 202 | 200 |
| Excluded | 9 | 21 |
| Bugs with ≥ 2 candidates | 139 | 136 |
| Patches after duplicate collapse | 791 | 779 |

The sensitivity policy reproduces v1 exactly.

### 3.2 Per project
| Project | Primary (patches / correct / overfitting / bugs) | Sensitivity |
|---|---|---|
| Chart | 157 / 55 / 102 / 22 | 157 / 55 / 102 / 22 |
| Closure | 239 / 44 / 195 / 73 | 238 / 44 / 194 / 73 |
| Lang | 148 / 43 / 105 / 35 | 142 / 43 / 99 / 34 |
| Math | 349 / 101 / 248 / 67 | 344 / 101 / 243 / 66 |
| Time | 6 / 2 / 4 / 5 | 6 / 2 / 4 / 5 |

Time contributes only 6 patches — its LOPO fold is very small.

### 3.3 Corrections and exclusions
- **12 corrected labels** (primary), all from correct folders to overfitting (`results/corrected_labels.csv`);
  the builder stops if a correction targets an already-overfitting patch.
- **Primary exclusions (9):** borderline 3 (ACS/kPAR/TBar-Lang-7), failed plausibility 5, unlabeled `Error` folder 1.
- Listed by the dataset authors but absent from the archive: Kali-Closure-133, Kali-A-Mockito-10, Arja-Mockito-10
  (`results/policy_identifier_matches.csv`).

### 3.4 Normalization and duplicates
- Trailing-whitespace normalization applied to **67** patches; verification **PASS for all 908**
  (`results/normalization_audit.csv`).
- **82** duplicate groups (byte-identical normalized diffs within a bug); **0** label conflicts under either policy
  (`results/duplicates.csv`).

### 3.5 Defects4J availability (from Defects4J `active-bugs.csv` / `deprecated-bugs.csv`)
| Version | JDK | Deprecated dataset bugs | Patches affected |
|---|---|---|---|
| v2.0.1 (`a83e479`) | 8 | Closure-63, Closure-93 | 18 |
| v3.0.1 (`6d54320`) | 11 | Closure-63, Closure-93, Lang-18 | 20 |

These will be recorded as `buggy_checkout_available = false`, not dropped. Version choice is made on the PC by
checkout/compile/trigger-test success, then frozen.

### 3.6 Label leakage findings (retained from v1)
- Filename suffix `-plausible` on all ICSE overfitting patches and no correct ones.
- APR tool identity strongly label-correlated.
- Whitespace artefacts concentrated in overfitting patches.

---

## 4. Implemented components (tested on Mac)

| Module | Function | Tests |
|---|---|---|
| `src/dataset.py` | download + checksum, parse, policies, normalization + verification, duplicates, manifest, provenance | 10 |
| `src/leakage_guard.py` | abort on label words, suffix, archive folder names, APR tool names, dataset path, fixed-oracle path, developer-fix fingerprint; logs to `logs/errors.jsonl` | 12 |
| `src/scores.py` | S_sem, stability, counterexample status classification, S_cex, S_edit, S_vuln, warning multiset difference | 18 (with `pvs.py`) |
| `src/pvs.py` | paper formula, both missing-S_cex strategies, weight validation, exported components | (in the 18 above) |
| `src/metrics.py` | precision/recall/F1/macro-F1/specificity/correct-patch retention/balanced accuracy/MCC/AUROC/AP; LOPO + GroupKFold with leakage assertions; cluster + paired bootstrap; conditional/end-to-end P@1, MRR, Top-3 with ties | 12 |
| `src/record_environment.py` | OS, CPU, RAM, GPU, CUDA, Python, pip freeze, JDK, Maven, Gradle, Defects4J commit, Docker, tools, git | manual |
| `docker/Dockerfile` | Ubuntu 22.04, JDK 8/11/21, Defects4J v2.0.1 + v3.0.1, SpotBugs 4.9.3 + FindSecBugs 1.14.0, Python env | not built |
| `configs/tools.lock` | SootUp 2.0.0, JavaParser 3.27.0, GumTree 4.0.0-beta3, WALA 1.6.10 (fallback), SpotBugs 4.9.3, FindSecBugs 1.14.0 | — |

Leakage-guard design note: a candidate patch textually identical to the developer fix does **not** trigger the
fingerprint check, because its text originates from the candidate diff, not from the fixed version.

---

## 5. Method design (draft protocol, not frozen)

| Component | Definition |
|---|---|
| S_sem | per run: confidence if CORRECT else 1 − confidence; mean of 3 runs; CORRECT iff ≥ 0.5 |
| S_cex | passed / VALID_BUG_REVEALING counterexamples (fixed PASS and buggy FAIL in all 3 repetitions); NA if none |
| S_edit | min(1, GumTree actions / AST nodes of changed buggy methods); LOC-ratio fallback |
| S_vuln | min(1, Σ weights of new SpotBugs/FindSecBugs warnings); proposed HIGH 1.0, MEDIUM 0.5, LOW 0.25 |
| PVS | α·S_sem + β·S_cex − γ·S_edit − δ·S_vuln; weights ≥ 0, sum 1 |
| CFG | SootUp Jimple StmtGraph of changed methods, buggy vs candidate |
| PDG | control dependence (post-dominance) + data dependence (reaching definitions); SootUp code-property-graph module evaluated first |
| Counterexample statuses | INVALID_COMPILE, INVALID_ORACLE, VALID_BUG_REVEALING, VALID_NON_DISCRIMINATING, FLAKY, TIMEOUT |
| Context | A diff · B + failing tests · **C + buggy method/class context (primary)** |
| Splits | LOPO primary; GroupKFold by bug (5 folds, seed 2026) secondary |
| Statistics | cluster bootstrap by bug, 10,000 resamples, seed 2026; improvement only if paired 95% CI excludes 0 |
| LLM selection | on the 50-patch pilot, without label agreement: parse rate ≥ 0.95, token-limit failures ≤ 0.02, then higher run-to-run stability, then lower cost |

### Missing S_cex — issue found in the suggested formula
`(α·S_sem − γ·S_edit − δ·S_vuln) / (α + γ + δ)` is on a different scale from the full PVS, so patches with and
without S_cex would not be comparable in one ranking.
**Recommended:** `PVS* = [α·S_sem + β·S_cex + γ(1 − S_edit) + δ(1 − S_vuln)] / Σ available weights`.
When all components exist, `PVS* = PVS + γ + δ` (a constant shift; identical ranking — verified by unit test).
**Author decision required before freeze.**

---

## 6. Draft semantic prompt (`prompts/semantic_v2_DRAFT.txt`) — requires author approval

### System prompt
```
You review a candidate patch produced by an automated program repair tool for a bug in a Java project.
The patch makes the project's existing tests pass. Your task is to judge whether it genuinely repairs the bug
or only makes the observed failing tests pass.

Assess the patch on these points:
1. generalization: does it fix the general cause of the bug ("general"), only the observed failing case
   ("specific_only"), or is this unclear ("unclear")?
2. deletes_or_weakens_functionality: does it remove or weaken existing behaviour instead of repairing it?
3. unrelated_behavior_change: does it change behaviour that the bug does not require changing?
4. minimality: how minimal is the change for what it repairs (0.0 = far larger than needed, 1.0 = minimal)?
5. readability: how readable and maintainable is the resulting code (0.0 = poor, 1.0 = good)?
6. security_robustness: how safe is the change with respect to null handling, bounds, exceptions, and resources
   (0.0 = introduces clear risk, 1.0 = no new risk)?
7. judgement: CORRECT if the patch genuinely repairs the bug, OVERFITTING otherwise.
8. confidence: your confidence in the judgement, between 0.0 and 1.0.
9. brief_reason: at most three sentences.

Use only the information provided. Respond with the JSON object required by the output schema.
```

### User message template
```
[[CONDITION_B_AND_C]]
Failing test(s) that the patch makes pass:
{failing_tests}

Failure message(s) on the unpatched version:
{failure_messages}
[[/CONDITION_B_AND_C]]
[[CONDITION_C]]
Unpatched source context (changed methods and their enclosing class):
{source_context}
[[/CONDITION_C]]

Candidate patch (unified diff against the unpatched version):
{candidate_diff}
```

### Output schema
`generalization` ∈ {general, specific_only, unclear} · `deletes_or_weakens_functionality` ∈ {true, false, unclear} ·
`unrelated_behavior_change` ∈ {true, false, unclear} · `minimality`, `readability`, `security_robustness`,
`confidence` numbers · `judgement` ∈ {CORRECT, OVERFITTING} · `brief_reason` string. All required; no extra fields.

The model is never asked to identify the Defects4J bug. Counterexample prompt: not yet drafted.

---

## 7. Paper status
- No manuscript results changed. Tracking file: `PAPER_CHANGES_PENDING.md` (unsupported claims, 8 reference
  problems, terminology fixes, possible new contributions).
- All manuscript numbers remain unsupported: F1 0.81, P@1 0.75, counterexample rate 0.80, 34 s, 150 faults /
  612 patches, 240 preferences, A100, ablation and per-project values.
- RQ2 (preference-calibrated ranking) stays PENDING until real human preferences exist.

---

## 8. Risks
1. **Deadline:** stated submission date is 2026-09-16; remaining work is ≈ 9–12 working days on the PC.
2. **PC access:** all remaining gates require the lab PC.
3. **Counterexample validity** may be low (old APIs, JUnit 3, package-private access) → S_cex often NA.
4. **Old bytecode / builds** (Closure size, Java 1.4–6 era) with SootUp.
5. **PDG differencing** is label-based and approximate.
6. **Runtime** of compile + 3 tests × 3 versions × 3 repetitions per patch.
7. **API cost** unknown until the smoke test.
8. **Human raters** needed for RQ2.

---

## 9. Decisions required from the authors
1. Missing-S_cex strategy (recommended: shifted renormalization).
2. S_vuln severity weights.
3. Approve or edit `prompts/semantic_v2_DRAFT.txt`.
4. Context-length cap for condition C.
5. Confirm the LLM selection rule.
6. Deadline / venue plan given the timeline.
7. Recruit 3 raters for 240 pairwise preferences.

---

## 10. Next steps
1. Copy `APR/APSEC2026_v2.bundle` to the PC → `git clone APSEC2026_v2.bundle APSEC2026`.
2. New API key in `experiment_v2/.env` on the PC.
3. Follow `experiment_v2/reports/PC_HANDOFF.md`: build Docker image → record environment → Defects4J checkouts
   and patch application → context extraction → semantic + counterexample pipeline → CFG/PDG/SpotBugs →
   10-patch smoke test → protocol freeze → 50-patch pilot → `PRE_FLIGHT_REPORT_V2.md` → STOP.
4. Meanwhile on the Mac (optional): preference-collection tool, Bradley–Terry calibration, counterexample prompt.
