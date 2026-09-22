# Pre-Flight Report v2 (Step 17-18) — 50-Patch Engineering Pilot

> **PRELIMINARY ENGINEERING PILOT — NOT FINAL PAPER RESULTS.** Every performance number in this report is
> from a 48-of-50 patch engineering pilot run whose only purpose is to decide whether the full experiment is
> worth running. The sample is tiny, LOPO folds are single-digit per project, and PVS* weights are
> un-calibrated placeholders. No number here may be cited as a finding about the method's accuracy.

Generated 2026-09-21. Selected model, deviations, and all methodology changes: `protocol/protocol.yaml`,
`protocol/DEVIATIONS.md`. Machine-readable source of every number below: `results/pilot_evaluation.json`,
`results/stage2b_features.csv`, `results/environment.json`.

---

## Recommendation: GO_FULL (with a narrowed RQ1 and honest scope)

The pilot clears the bar for the full 899-patch run, for four reasons:
1. **The pipeline runs end-to-end on real, diverse data** — checkout, patch apply/compile, context (0 errors),
   semantic (both models 100% parse), counterexample generation + empirical oracle, GumTree S_edit (48/48),
   SootUp CFG/dataflow (45/48 DATAFLOW), and changed-class SpotBugs. No blocking engineering issue remains.
2. **The core signal is real and honest.** M3 semantic significantly beats the majority baseline (MCC paired
   CI excludes 0; recall 0.917, AUROC 0.766). Combining with SootUp static features (M7) gives the best point
   estimate of any method (MCC 0.462, F1 0.745). These are far below the manuscript's fabricated 0.81 — exactly
   the corrected, measured picture the project exists to produce.
3. **Cost is negligible** (~$12–20 API for the full run) and the selected model (haiku) is decided on
   label-free pilot evidence.
4. **The full n is needed to resolve the one open statistical question**: whether M7 (sem+static) genuinely
   beats M3 (its +0.195 MCC CI just includes 0 at n=48). Only the full corpus has the power to settle it.

**Conditions the full run must carry (already reflected in the protocol/DEVIATIONS):**
- **RQ1 narrows** to the semantic (+static) arm. The **counterexample arm is designed-but-weak** — 2/106
  discriminating tests, S_cex missing on 65% — and must be reported as such, never as a working dual-verifier.
  Adding it hurts detection (M6, M9). This matches the handover's RQ1 reconciliation.
- **PDG is not computed** (analysis ceiling DATAFLOW); the paper must say CFG/dataflow, not PDG.
- **S_vuln contributes almost nothing** (3/48); the static signal that helps is the CFG/dataflow deltas.
- All full-run numbers remain PRELIMINARY until the frozen protocol's bootstrap CIs are computed on the full n;
  PVS* stays ranking-only until real human preferences (RQ2) exist.

This is **not** GO for the paper's original claims; it is GO to measure the narrowed, honest version at scale.

---

## 1. Environment
- Authoritative machine: WSL2 Ubuntu 22.04.5 LTS inside the `qc-v2` Docker container (`in_docker=True`).
- Defects4J **v2.0.1**, commit `a83e47921152721569cb95d6d7b91c4be277d940` (matches `protocol.yaml defects4j.commit`).
- JDK 21 (analysis tools), JDK 8 available for project builds; SpotBugs 4.9.3 + FindSecBugs 1.14.0; Maven 3.6.3.
- Full record: `results/environment.json` / `.txt`. Recorded via `record_environment.py --authoritative`.

## 2. Dataset
- Source: Zenodo 3730599 `Patches.zip`, archive MD5 `11203b88…` verified; manifest SHA256 pinned in `protocol.yaml`.
- Full labelled corpus: **908 patches** (Math 350, Closure 240, Chart 159, Lang 153, Time 6); labels 654
  overfitting / 245 correct / 9 unlabelled → **899 labelled** (the full-run size). Base rate 73% overfitting.
- Two label policies (primary + sensitivity) and duplicate handling per `protocol.yaml dataset`.

## 3. Pilot sample & Defects4J coverage
- Stratified **50-patch** pilot (project × label × size); **48 scored** (2 not scored — see §Failures).
- Composition: Chart 7, Closure 12, Lang 14, Math 13, Time 4; **24 correct / 26 overfitting**; size terciles
  small 29 / large 21. Deliberately balanced (52% overfitting) unlike the full corpus (73%).
- All sampled bugs checked out (buggy + fixed_oracle) and candidates applied+compiled; workspaces intact.

## 4. Context-extraction success
- **0 / 48** patches had context-extraction errors (condition C: changed methods, signatures, class decl,
  imports, failing tests, failure messages). Constructor-context bug found in the smoke test is fixed.

## 5. Leakage audit
- Every LLM request is produced by `request_builders`, guarded by `leakage_guard`, and carries a receipt that
  `llm_client.verify_receipt` checks against the request's dynamic content — an unguarded request cannot be sent.
- **0 real leakage aborts** across the 48 pilot patches. The `LEAKAGE_ABORT` entries in `logs/errors.jsonl`
  are all from the guard's unit-test fixture (patch `Math-80-Kali`, not in the pilot), demonstrating the guard
  blocks archive-folder tokens (`Doverfitting`), dataset filename suffixes, APR-tool identifiers, and
  `ground_truth_label` metadata.

## 6. Model selection (no labels) — Step 7
Frozen hierarchy applied to the pilot **without ground-truth agreement**:

| Criterion | claude-haiku-4-5 | claude-sonnet-5 | Decides |
|---|---|---|---|
| Parse success (excl. billing) | 1.00 (144/144) | 1.00 (144/144) | tie |
| Token-limit failure rate | 0.00 | 0.00 | tie |
| Run-to-run judgement stability | **1.00** | 0.979 | **haiku** |
| Median latency (s) | 3.42 | 6.79 | haiku (corrob.) |
| Cost (pilot, USD) | 0.65 | 2.28 | haiku (corrob.) |

**Selected: `claude-haiku-4-5`.** Recorded in `protocol.yaml` + `DEVIATIONS.md #8`.

## 7. Parse rate & stability
- Both models: parse-success (excl. billing) = 1.00; token-limit failures = 0.00.
- Stability (fraction of runs agreeing with the modal judgement): haiku 1.00, sonnet 0.979.
- All 33 billing-failed runs/model + 1 connection error were re-issued after the credit top-up (Step 2); both
  models now have 144/144 OK runs. Billing errors are classified separately from parse failures everywhere.

## 8. Detection metrics — per method (positive class = overfitting, n=48, base rate 0.50)
Detection is reported **per method** per `protocol.yaml evaluation.methods`. The earlier placeholder rule
`PVS*<0.5` (F1 0.214) was **removed** — it was never pre-registered and inflated PVS* on missing-S_sem patches
(`DEVIATIONS #3`). PVS* is ranking-only.

| Method | Precision | Recall | F1 | MCC | AUROC | Confusion (tp/fp/tn/fn) |
|---|---|---|---|---|---|---|
| M0 majority | 0.421 | 0.333 | 0.372 | −0.128 | — | 8/11/13/16 |
| M1 random stratified | 0.500 | 0.542 | 0.520 | 0.000 | — | 13/13/11/11 |
| M2 diff-feature (S_edit) | 0.433 | 0.542 | 0.481 | −0.172 | 0.313 | 13/17/7/11 |
| **M3 semantic (S_sem<0.5, frozen)** | **0.564** | **0.917** | **0.698** | **0.267** | **0.766** | 22/17/7/2 |
| M4 counterexample (binary, avail=17) | 0.500 | 0.143 | 0.222 | — | 0.529 | — |
| M6 sem+cex (LR, LOPO) | 0.545 | 0.750 | 0.632 | 0.135 | 0.636 | 18/15/9/6 |
| M5 static (LR) | 0.667 | 0.667 | 0.667 | 0.333 | 0.736 | — |
| **M7 sem+static (LR)** | **0.704** | **0.792** | **0.745** | **0.462** | 0.737 | — |
| M8 cex+static (LR) | 0.524 | 0.458 | 0.489 | 0.042 | 0.595 | — |
| M9 sem+cex+static (LR) | 0.625 | 0.625 | 0.625 | 0.250 | 0.687 | — |
| M10 full PVS (human prefs) | PENDING — no human preference data |

Static features (M5/M7/M8/M9): `[s_vuln_changed, d_cyclomatic, d_branch_points, d_stmts, d_defuse_pairs]`
(SootUp CFG/dataflow deltas + changed-class S_vuln), mean-imputed in-fold with missingness indicators.

Paired cluster-bootstrap (MCC, improvement iff 95% CI excludes 0):
- M3 vs M0 majority: +0.395, CI [0.008, 0.765] → **improves**.
- M3 vs M2 diff-feature: +0.310, CI [−0.092, 0.686] → not significant.
- M6 (sem+cex) vs M3: −0.132, CI [−0.308, 0.054] → **no improvement** (sparse S_cex dilutes).
- **M7 (sem+static) vs M3: +0.195, CI [−0.050, 0.436] → best point estimate, CI just includes 0.**
- M9 (sem+cex+static) vs M3: −0.017, CI [−0.271, 0.254] → no improvement (cex again dilutes).

**Read:** the semantic signal (M3) carries detection and **significantly beats the baselines** (recall 0.917,
AUROC 0.766, MCC vs majority CI excludes 0). Adding SootUp CFG/dataflow + S_vuln (M7) gives the best point
estimate of all methods (MCC 0.462, F1 0.745) — a real, complementary static signal — but at n=48 the
improvement over M3 is not yet significant (CI lower bound −0.05). The counterexample arm consistently fails to
help (M6, M9). All values are far from the manuscript's fabricated 0.81 F1 — the correct, honest outcome.

## 9. Correct-patch retention
- M3 semantic specificity / correct-patch retention = **0.292** (tn 7 / (tn 7 + fp 17)): M3 flags many correct
  patches as overfitting (high recall, low precision). M7 (sem+static) improves precision to 0.704.

## 10. Counterexample funnel & rates
Per-test attrition (summed over 48 patches):

| generated | compiled | fixed_pass | buggy_fail | stable_bug_revealing | candidate_discriminating |
|---|---|---|---|---|---|
| 106 | 71 | 64 | 24 | 24 | **2** |

- Only **2** candidate-discriminating tests across the whole pilot → the counterexample arm is very sparse.

## 11. S_cex availability
- **31/48 (64.6%) patches have NO valid counterexample** (S_cex = NA, never imputed). Missingness by
  project/label/size in `pilot_evaluation.json → s_cex_missingness`. This is why M4/M6 are weak.

## 12. CFG / PDG / DATAFLOW / CFG_AST coverage (Stage 2B)
- Achieved analysis level per candidate: **DATAFLOW 45 / 48, FAILED 3 / 48** (SootUp Jimple CFG + def/use built
  for the changed methods, buggy vs candidate). GumTree S_edit succeeded on **48/48**.
- The 3 FAILED are changes in constructors of inner classes / non-method locations the name-based bytecode
  matcher does not resolve; recorded as MISSING, never 0.
- Analysis-level ceiling is **DATAFLOW** (CFG + def/use). **PDG (control-dependence) is not computed** — no
  candidate is labelled PDG (`DEVIATIONS #10`). CFG features aggregate over same-name overloads.

## 13. SpotBugs / FindSecBugs coverage (Stage 2B, changed classes)
- S_vuln computed (buggy vs candidate, **changed classes only**) on **48/48** patches; **new warning on only
  3/48**. Restricting to changed classes (vs whole-project in the smoke test, which gave all-zeros) surfaces a
  little signal but S_vuln remains near-zero — an open question about whether it contributes at this scale.
- Weighted severity scheme (SpotBugs H/M/L priority; weights HIGH 1.0 / MED 0.5 / LOW 0.25) remains primary.

## 14. S_edit / S_vuln / PVS* distributions (n=48)
- **S_edit** (GumTree AST, primary; method=`ast` for all 48): min 0.006, median 0.056, mean 0.138, max 1.000.
  LOC version retained as `S_edit_loc` (sensitivity).
- **S_vuln** (changed-class): median 0.000, mean 0.042, max 1.000; 3/48 nonzero.
- **PVS\*** (ranking only, placeholder equal weights): min 0.208, median 0.697, mean 0.707; **0 missing**
  (all 48 have S_sem after the Step-2 reruns; the S_sem-missing PVS* inflation is gone).

## 15. Complementarity overlap (RQ3)
- Semantic vs counterexample (among the 17 with S_cex): see `pilot_evaluation.json → complementarity.sem_vs_cex`.
- **Counterexample vs static** (n=17 with both available; static flag = new SpotBugs warning): among
  overfitting — cex_only 0, static_only 0, both 1, neither 6; among wrongly-flagged-correct — cex_only 1,
  static_only 1, both 0. Both signals are too sparse here to establish complementarity; the semantic signal is
  the one doing the work.

## 16. Ranking — conditional & end-to-end P@1 (PVS*)
- 5 bugs have ≥2 candidate patches in the pilot. **Conditional P@1 = 0.70** (CI [0.30, 1.00]), MRR 0.85,
  Top-3 1.00, random-expected P@1 0.35. End-to-end and theoretical-max in `pilot_evaluation.json → ranking`.
- Tiny n (5 bugs); indicative only.

## 17. Sensitivity analyses
- **Label policy** (primary vs sensitivity labels), evaluated with the M3 rule: `pilot_evaluation.json →
  sensitivity.label_policy`.
- **Duplicate collapse**: `sensitivity.duplicates`.
- **Context condition** (A/B/C): primary condition C used throughout; A/B not re-run in this pilot (noted as
  future sensitivity).

## 18. Runtime by component, tokens, cost
- Runtime per patch and per stage: `pilot_evaluation.json → runtime`.
- Tokens (successful runs): haiku mean 3664 in / 172 out; sonnet 4855 in / 614 out.
- **Cost** (Anthropic list pricing, recorded 2026-09-21: Haiku $1/$5, Sonnet $2/$10 per 1M in/out):
  semantic haiku $0.65, semantic sonnet (comparison) $2.28, **pilot total ≈ $2.93**. Counterexample calls do
  not yet log tokens (additive-logging gap) → their API cost is not captured; a small underestimate.
- Full-run projection (899 labelled patches, selected model haiku, semantic 3 runs): 899×3 ≈ 2697 calls at the
  pilot's ~$0.0045/call ≈ **$12** for the semantic arm. Counterexample generation (~899 haiku calls, larger
  outputs, tokens not yet logged) + memorization probe add an unmeasured but small amount; total API cost is
  very likely **under $20**. Defects4J execution is CPU time, not API cost.

## 19. Memorization diagnostic
- Probe over 48 patches: **0 recognized** (37 "not recognised", 11 NA/errored). No evidence the model recalls
  the specific Defects4J bug identities → low memorization risk for the semantic judgement.

## 20. Failures
- 2/50 patches not scored (stopped early in the pipeline) — detail in `pilot_evaluation.json → failures`.
- Stage 2B analyzer failures (CFG `FAILED`, S_vuln/S_edit missing) are recorded as MISSING, never 0.

## 21. Open questions
- Counterexample generation almost never yields a discriminating test (2/106); is the K=3 budget or the
  prompt the bottleneck, or is empirical counterexample generation simply hard at this scope?
- S_vuln is nearly always zero (3/48 nonzero) even on changed classes — does it ever contribute signal, or is
  SpotBugs too coarse even at class scope? (The static *CFG/dataflow* deltas, not S_vuln, drive M5/M7.)
- M3 semantic recall is high but precision/retention low (many correct patches flagged). Is a calibrated
  threshold (not 0.5) or the preference-weighted PVS the answer? (Requires the RQ2 human-preference data.)
- The full corpus is 73% overfitting vs the balanced pilot; the detection operating point will shift.

---

*All numbers above are PRELIMINARY ENGINEERING PILOT values — NOT FINAL PAPER RESULTS.*
