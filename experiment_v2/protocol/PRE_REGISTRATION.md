# Pre-Registration — DRAFT (becomes binding at the protocol freeze commit)

## Research questions and hypotheses (hypotheses, not claims)
| RQ | Question | Hypothesis to test | Primary endpoint |
|---|---|---|---|
| RQ1 | Does semantic + counterexample verification (M6) improve detection of overfitting plausible patches over simpler baselines (M0–M3)? | M6 differs from M2 and M3 | Paired cluster-bootstrap difference in MCC; also correct-patch retention, PR-AUC |
| RQ2 | Does preference-calibrated multi-criteria ranking improve the chance a known-correct patch is ranked first? | PVS ranking (M10) > random ranking | Conditional P@1 — PENDING human preferences |
| RQ3 | Do counterexamples (M4) and static analysis (M5) provide complementary signals? | Combined (M8) differs from each alone; error overlap is not total | Paired difference in MCC; overlap matrices |
| RQ4 | What runtime and monetary cost does the pipeline add, and which stages dominate? | — (descriptive) | Per-stage median, p90, p95 time; USD per patch |

The manuscript's statement "counterexamples favor recall, static analysis favors precision, combination best" is
treated as a hypothesis under RQ3, not as an expected result.

## Primary analysis
Primary label policy, all duplicates retained, context condition C, LOPO split, selected LLM, 3 runs, K = 3.

## Sensitivity analyses (all pre-specified)
Sensitivity label policy · duplicate collapse · GroupKFold by bug · context conditions A and B · missing-S_cex
indicator model · LOC-based S_edit.

## Decision rules fixed in advance
- Semantic threshold 0.5 on S_sem_final; classifier threshold 0.5; no tuning.
- Improvement claimed only when the 95% paired cluster-bootstrap CI excludes zero.
- LLM model chosen by the selection rule in protocol.yaml without label agreement.
- Failed, unparsable, leakage-aborted, or non-compiling cases are reported, never dropped silently.

## Exploratory (labelled as such)
Patch-level McNemar tests · exploratory supervised PVS calibration · memorization probe.
