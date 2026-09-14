# Experimental Protocol v2 — DRAFT (not frozen)

The machine-readable source of truth is `protocol/protocol.yaml`. This document explains it.
Status values: **DRAFT** until the freeze commit is tagged `protocol-v2-frozen`.

## 1. Principle
The experiment measures what the proposed method does. Historical manuscript numbers are not targets.
No threshold, prompt, weight, split, seed, or policy is chosen by looking at evaluation performance.

## 2. Machine
All official runs (smoke test onward that produce reported numbers, pilot, full run) execute on the lab PC under
Ubuntu (native or WSL2), inside the pinned Docker image. `results/environment.json` is recorded on that machine.

## 3. Data
- Source: Wang et al. ASE'20, Zenodo 3730599 `Patches.zip` (MD5 verified). Provenance: `data/DATASET_PROVENANCE.md`.
- Two label policies, both run: primary (apply dataset-author corrections) and sensitivity (exclude questioned patches).
- Duplicates: primary retains all candidates; sensitivity collapses byte-identical normalized diffs within a bug.
- Label-leak controls: prompts never contain labels, tool names, archive paths, filename suffixes, or fixed-version
  content; enforced by `src/leakage_guard.py` before every request.

## 4. Pipeline stages
| Stage | Component | Output |
|---|---|---|
| 0 | Defects4J buggy / fixed_oracle checkouts; candidate = buggy + patch | checkout, apply, compile, trigger-test status |
| 1 | Semantic assessment (context C primary; A, B ablations), 3 runs | `semantic_runs.jsonl`, `semantic_scores.csv` |
| 2A | Counterexample generation (K = 3), compile, fixed-oracle validation, buggy and candidate execution | `counterexample_validation.csv`, `counterexample_scores.csv` |
| 2B | CFG / PDG features (SootUp), AST edit (GumTree), warnings (SpotBugs + FindSecBugs) | `cfg_features.csv`, `pdg_features.csv`, `vulnerability_findings.csv`, `edit_scores.csv` |
| 3 | PVS components and score; ranking | `patch_scores.csv`, `ranking_metrics.csv` |
| 4 | Runtime and cost per stage | `latency.csv`, `cost.csv` |

## 5. Scores (see protocol.yaml for exact definitions)
- **S_sem** = mean over runs of (confidence if CORRECT else 1 − confidence); CORRECT iff ≥ 0.5.
- **S_cex** = passed / valid bug-revealing counterexamples; NA if none valid.
- **S_edit** = GumTree actions / AST nodes of changed buggy methods (LOC fallback), clipped to [0,1].
- **S_vuln** = min(1, Σ severity weights of newly introduced warnings).
- **PVS** = α·S_sem + β·S_cex − γ·S_edit − δ·S_vuln, weights ≥ 0 summing to 1. Missing-S_cex strategy: **decision
  required at freeze** (options in protocol.yaml; the shifted renormalization is recommended because the directive's
  renormalized formula is on a different scale from the full PVS).

## 6. Counterexample status definitions
| Status | Condition |
|---|---|
| INVALID_COMPILE | test does not compile against the buggy classpath |
| INVALID_ORACLE | fails on the developer-fixed version (any repetition) |
| VALID_BUG_REVEALING | fixed PASS and buggy FAIL in all repetitions |
| VALID_NON_DISCRIMINATING | fixed PASS and buggy PASS in all repetitions |
| FLAKY | inconsistent outcome across repetitions on fixed or buggy |
| TIMEOUT | exceeds the per-execution timeout on fixed or buggy |

Only VALID_BUG_REVEALING tests are executed on the candidate and enter S_cex.

## 7. Developer-fixed version rule
The fixed version is an offline oracle only: used to validate generated tests and to build the leakage fingerprint.
It never enters any prompt, feature, score, ranking input, or example. Enforced by workspace typing, path checks,
content fingerprints, and tests with canary strings.

## 8. Evaluation
- Positive class: overfitting. Headline metrics include specificity / correct-patch retention, balanced accuracy,
  MCC, AUROC, average precision, macro-F1 — never F1 alone.
- Primary split LOPO; secondary GroupKFold by bug. Nothing from a held-out fold influences fitting, scaling,
  thresholds, or weights. Fold sizes reported (Time has 6 patches).
- Cluster bootstrap by bug, 10,000 resamples, seed 2026; paired bootstrap for differences; improvement claimed only
  if the 95% CI excludes zero. Patch-level McNemar is exploratory.
- Ranking: conditional P@1 (primary), end-to-end P@1, theoretical max, random expectation, MRR, Top-3.
- RQ2 in its paper-faithful form stays PENDING until real human preferences exist.

## 9. Staging and stop rule
Unit tests → 10-patch smoke test → protocol freeze → ~50-patch pre-flight pilot → `PRE_FLIGHT_REPORT_V2.md` → STOP.
The full run requires written author approval.
