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
2. **A measurable semantic signal exists, but no advantage is yet established.** M3 semantic reaches recall
   0.917 and AUROC 0.766, and M7 (semantic + SootUp CFG/dataflow) has the best point estimates of any method
   (MCC 0.462, F1 0.745). Against the meaningful baselines (M1 random, M2 corrected diff-feature) **none of
   these differences has a CI excluding 0 at n=48** (§8). These values are far below the manuscript's
   unsupported 0.81 — the corrected, measured picture the project exists to produce.
3. **Cost is negligible** (~$12–20 API for the full run) and the selected model (haiku) is decided on
   label-free pilot evidence.
4. **The full n is needed to resolve the open statistical questions**: whether M3 beats the corrected M2/M1
   baselines at all, and whether M7 (sem+static) beats M3 — every relevant CI includes 0 at n=48, and the
   imputed and complete-case static analyses disagree (§8). Only the full corpus has the power to settle this.

**Conditions the full run must carry (already reflected in the protocol/DEVIATIONS):**
- **RQ1 narrows** to the semantic (+static) arm. The **counterexample arm is designed-but-weak** — 2/106
  discriminating tests, S_cex missing on 65% — and must be reported as such, never as a working dual-verifier.
  Adding it hurts detection (M6, M9). This matches the handover's RQ1 reconciliation.
- **PDG is not computed** (analysis ceiling DATAFLOW); the paper must say CFG/dataflow, not PDG.
- **S_vuln contributes almost nothing** (3/48); within the static block the CFG/dataflow deltas carry what
  little signal there is — and that block's contribution is itself not yet established (§8).
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
- Archive: **908 patch files** parsed (Math 350, Closure 240, Chart 159, Lang 153, Time 6). Under the primary
  label policy **899 are included** (654 overfitting / 245 correct; base rate 73%) and **9 are excluded**:
  3 borderline, 5 failed-plausibility (dataset-author notes) and 1 in the unlabeled `Error` folder — exclusions,
  not "unlabelled" patches. 12 labels are corrected per the dataset authors (`results/corrected_labels.csv`).
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
| **M2 diff-feature (v1 handcrafted, LR)** | 0.556 | 0.417 | 0.476 | 0.086 | 0.519 | 10/8/16/14 |
| M2b S_edit only (LR) | 0.471 | 0.333 | 0.390 | −0.044 | 0.457 | 8/9/15/16 |
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
- M3 vs M0 majority: +0.395, CI [0.008, 0.765] → excludes 0, **but see the baseline caveat below**.
- M3 vs M1 random stratified: +0.267, CI [−0.050, 0.578] → **not established**.
- M3 vs M2 diff-feature (corrected baseline): +0.181, CI [−0.166, 0.526] → **not established**.
- M3 vs M2b S_edit only: +0.310, CI [−0.092, 0.686] → not established.
- M6 (sem+cex) vs M3: −0.132, CI [−0.308, 0.054] → **no improvement** (sparse S_cex dilutes).
- M7 (sem+static) vs M3: +0.195, CI [−0.050, 0.436] → **not established** (best point estimate of any method).
- M9 (sem+cex+static) vs M3: −0.017, CI [−0.271, 0.254] → no improvement (cex again dilutes).

**Baseline caveat (DEVIATIONS #12):** M0 "majority" is degenerate in this deliberately balanced pilot (52%
overfitting): the training-fold majority class flips between LOPO folds, so M0 behaves like a near-random
classifier (MCC −0.128) rather than an all-one-class baseline. The M0 comparison therefore cannot carry a claim.
Against the meaningful baselines (M1 random, M2 diff-feature) **no method's advantage is established at n=48.**

**Read:** M3 semantic has the highest recall (0.917) and a mid AUROC (0.766); M7 (semantic + SootUp
CFG/dataflow + S_vuln) has the best point estimates of all methods (MCC 0.462, F1 0.745). **None of these
advantages is statistically established at n=48** against M1/M2 — that is precisely what the full run is for.
The counterexample arm consistently fails to help (M6, M9). All values are far from the manuscript's unsupported
0.81 F1.

**Static-feature imputation sensitivity (DEVIATIONS #11).** The static models are primary with in-fold mean
imputation + missingness indicators. A complete-case re-fit (no imputation; n=45 after dropping 3 rows with a
missing static feature) gives M3 MCC 0.243, M5 0.377, M7 0.514, and M7 vs M3 = +0.271, CI [0.030, 0.513],
which excludes 0. The **primary (imputed) analysis does not establish the improvement**; the complete-case
result is reported as a sensitivity analysis only, and both are in
`pilot_evaluation.json → detection.static_complete_case_sensitivity`.

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
Per-stage wall-clock over the 48 pilot patches (seconds; full table in `pilot_evaluation.json → runtime`):

| Stage | median | p90 | max |
|---|---|---|---|
| assemble_pvs (Stage 2B: GumTree + SootUp + SpotBugs) | 49.9 | — | — |
| counterexample (1 LLM call + compile + oracle runs) | 45.6 | — | — |
| checkout_bug (buggy + fixed_oracle) | 28.0 | — | — |
| semantic_comparison (sonnet, 3 runs) | 18.7 | — | — |
| apply_patch + compile | 11.4 | — | — |
| semantic_primary (haiku, 3 runs) | 10.4 | — | — |

- Per patch: mean **849 s**, median and p90 in `runtime.per_patch_seconds`.
- **Full-run projection** (899 patches at the pilot's mean): **212 h sequential**; 106 h with 2 workers,
  **53 h with 4**, 35 h with 6, 27 h with 8. The PC has 10 physical cores / 20 threads, so 4–6 workers is the
  realistic range for Java builds. A resumable, checkpointed parallel runner is **still to be implemented**
  (the pilot runner is sequential, and the machine has already powered off mid-run once).
- Tokens (successful runs): semantic haiku mean 3664 in / 172 out; sonnet 4855 in / 614 out. **Counterexample
  haiku (now logged) mean 3478 in / 1489 out** — the K=3 test-generation output is ~9× the semantic output,
  which is why the counterexample arm dominates per-call cost.
- **Cost** (Anthropic list pricing, recorded 2026-09-21: Haiku $1/$5, Sonnet $2/$10 per 1M in/out): semantic
  haiku $0.65, semantic sonnet (comparison) $2.28, **counterexample haiku $0.48** (44/48 calls re-issued to
  measure tokens; see DEVIATIONS #14), **pilot total ≈ $3.41** (was $2.93 before the counterexample arm was
  measured). 4 counterexample calls could not be re-measured (2 API `400`, 2 API `500`), so the cex figure is a
  lower bound over 44 calls.
- Full-run projection (899 patches, haiku, from the pilot's **measured** per-call cost): semantic 899×3 ≈ 2697
  calls × $0.00452 ≈ **$12.2**; counterexample 899 calls × $0.0109 ≈ **$9.8**; memorization 899 short calls
  (now logged, tiny output) ≈ **$2–3**. **Total API ≈ $24–25** — above the earlier "under $20" guess, because
  the counterexample output tokens (previously unlogged) are large. Defects4J execution is CPU time, not API
  cost. A resumable, checkpointed 4-worker parallel runner (`src/run_full.py`) is now implemented; at the
  pilot's mean per-patch time the full run is ≈ **53 h at 4 workers**.

## 19. Memorization diagnostic
- Probe over **48/48 patches: 0 recognized** (all 48 returned a real judgement; the 11 rows that had failed
  with a credit-balance error during the pilot were re-run after the top-up — see DEVIATIONS-adjacent gap B2).
  No evidence the model recalls the specific Defects4J bug identities → low memorization risk for the semantic
  judgement.

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
- Imputed and complete-case static analyses disagree on whether M7 beats M3 (§8). Which is right is an
  n-problem, not a modelling preference; the full run decides it with the primary (imputed) model.

## 22. Still outstanding before the full run
1. ~~Context ablation A / B not run~~ **CLOSED (B1):** A/B/C reported side by side in §23. Adding failing
   tests (A→B) lifts the decisions; extracted context (B→C) sharpens ranking (AUROC 0.714→0.766).
2. ~~11 memorization-probe entries errored/NA~~ **CLOSED (B2):** re-run after the credit top-up; the probe is
   now a complete **48/48, 0 recognized** (§19).
3. ~~Counterexample calls do not log tokens~~ **CLOSED (B3):** `oracle_runner` now records usage; pilot cex
   cost measured at **$0.48** (44/48 re-issued), pilot total **$3.41** (§18, DEVIATIONS #14).
4. ~~No resumable parallel runner~~ **CLOSED (B4):** `src/run_full.py` — checkpointed, per-bug parallel
   (default 4 workers, `--workers`), safe to kill/resume; consolidation in `src/consolidate_full.py`.
Items 2–4 do not change any pilot number above; they are gaps in the pilot's own coverage now closed.

## 23. Context ablation A / B / C (B1)
The pre-registered context conditions run on the **same 48 pilot patches**, claude-haiku-4-5, 3 runs each,
scored with the identical M3 rule (positive = overfitting, predict overfitting iff `s_sem_final < 0.5`).
A = candidate diff + patch metadata only; B = A + failing-test names + failure messages; C = B + extracted
changed-method/signature/class context (**C is the pilot's primary condition**). Source:
`src/context_ablation.py`; per-condition results in `results/context_ablation/` (A/B) and
`results/semantic_runs/` (C); summary `results/context_ablation_summary.json`.

| Condition | F1 | MCC | Precision | Recall | AUROC | Correct-patch retention | Confusion (tp/fp/tn/fn) |
|---|---|---|---|---|---|---|---|
| A (diff only) | 0.667 | 0.192 | 0.556 | 0.833 | 0.705 | 0.333 | 20/16/8/4 |
| B (+ failing tests + messages) | 0.698 | 0.267 | 0.564 | 0.917 | 0.714 | 0.292 | 22/17/7/2 |
| **C (+ extracted context) — primary** | **0.698** | **0.267** | **0.564** | **0.917** | **0.766** | 0.292 | 22/17/7/2 |

**Read (PRELIMINARY, n=48, point estimates only — no CIs computed for the ablation):**
- The **failing-test information (A→B)** is what moves the 0.5-threshold decisions: recall 0.833→0.917, MCC
  0.192→0.267, two more true overfitting catches (fn 4→2).
- The **extracted code context (B→C)** does **not** change any binary decision on these 48 (identical
  confusion) but **improves ranking** (AUROC 0.714→0.766) — it sharpens the score separation without moving
  the operating point. Whether that ranking gain is worth the extraction cost is an open question the full run
  (with CIs and the 73%-overfitting base rate) is better placed to judge.
- The C row reproduces §8's M3 numbers exactly (F1 0.698, MCC 0.267, AUROC 0.766), confirming the ablation
  harness scores identically to the primary evaluation.

---

*All numbers above are PRELIMINARY ENGINEERING PILOT values — NOT FINAL PAPER RESULTS.*
