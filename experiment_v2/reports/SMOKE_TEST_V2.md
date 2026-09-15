# 10-Patch Smoke Test (Step 14-15) — Engineering Report

**PRELIMINARY ENGINEERING SMOKE TEST — NOT PAPER RESULTS.** This validates that the pipeline runs end-to-end
on real, diverse data and surfaces bugs. No number below should be interpreted as a finding about the method's
accuracy; the sample is 10 patches, not stratified for statistical inference, and PVS weights are unfitted
placeholders (see `reports/PVS_ASSEMBLY_NOTES.md`).

## Sample

See `reports/SMOKE_TEST_SAMPLE.md`: 5 projects (Chart, Closure, Lang, Math, Time), both labels (5 correct /
5 overfitting), diff size range 1-379 lines, one duplicate-group member (Math-28), selected by structural
criteria only, never by outcome.

## Result: 10/10 patches completed the full pipeline

Environment -> Defects4J checkout (buggy + fixed_oracle) -> candidate patch application -> compile ->
developer-fix fingerprinting -> source-context extraction (JavaParser) -> semantic LLM evaluation (3 runs) ->
counterexample generation (1 LLM call, K=3) + empirical oracle validation -> SpotBugs+FindSecBugs `S_vuln` ->
LOC-based `S_edit` -> `PVS*` assembly. Every stage recorded per-patch in `results/smoke_test_log.json`
(`ok`/timing per stage; nothing silently dropped).

Total wall-clock: ~40 minutes for 10 patches (`results/smoke_test_log.json`), min 108s (Lang-58) to 611s
(Time-11, joda-time's SpotBugs pass was slow). Closure patches ran 5-6 min each (large project, slow compile).

## Four real bugs found and fixed during this run (not hypothetical)

1. **Git "dubious ownership" for Defects4J's own project-repo mirrors.** `git config --global --add
   safe.directory /work` (set during Step 2/3) only wrote `/root/.gitconfig`, which a non-root `--user` container
   run never reads. This didn't surface until this batch touched *git*-based Defects4J projects (Closure, Lang,
   Math, Time) — Chart uses SVN, which has no such check, so the earlier single-patch validation never hit it.
   4/10 patches failed checkout outright. Fixed: `git config --system --add safe.directory '*'` in the
   Dockerfile (`/etc/gitconfig`, UID-independent).
2. **`ContextExtractor.java` only searched `MethodDeclaration` nodes**, missing bugs located in constructors
   entirely (confirmed: Chart-12's real bug is in `MultiplePiePlot`'s constructor). Fixed by also searching
   `ConstructorDeclaration`.
3. **A fourth source-root prefix.** The three prefixes in `PC_HANDOFF.md` (`/source/`, `/src/main/java/`,
   `/src/java/`) don't cover Closure, whose diffs use a bare `/src/` (`dir.src.classes` = `"src"`). Added, ordered
   after the more specific prefixes so it doesn't shadow them.
4. **Missing trailing newline on one archive diff file** (Math-53's) made GNU `patch` reject an otherwise-valid
   hunk with "unexpectedly ends in middle of line". Fixed by appending a newline if absent before invoking `patch`
   — not a content change, purely a formatting technicality `patch` is strict about.

Combined with the three bugs found during single-patch development (`D4J_DRIVER_NOTES.md`, `ORACLE_RUNNER_NOTES.md`,
`CONTEXT_EXTRACTOR_NOTES.md`), this smoke test's purpose — finding what a single hand-picked example doesn't
exercise — worked exactly as intended.

## Component coverage across the 10 patches (`results/patch_scores.csv`)

| Component | Present | Missing (NA) |
|---|---|---|
| S_sem | 10/10 | 0 |
| S_cex | 4/10 | 6/10 |
| S_edit | 10/10 | 0 |
| S_vuln | 10/10 (all 0 — see below) | 0 |

- **S_cex missing on 6/10**: in every case, the LLM's K=3 generated tests were `VALID_NON_DISCRIMINATING` (pass
  on both buggy and fixed) rather than `VALID_BUG_REVEALING`, i.e. genuinely 0 valid counterexamples — not a
  pipeline failure. Correctly reported as NA per protocol (`zero_valid: NA, never imputed`), not as 0.
- **S_vuln = 0 for all 10**: plausible given every sampled patch is a small, localized diff (max 379 lines) —
  SpotBugs scans the whole compiled-classes directory each time, and small semantic changes rarely flip a
  bytecode-level warning. Not evidence the S_vuln pipeline is broken (validated correctly detecting real,
  class-specific warnings during development — `PVS_ASSEMBLY_NOTES.md`); worth watching once real preference
  data exists whether this component ever contributes signal at this scale, or whether project-wide SpotBugs
  scanning is too coarse for candidate-vs-buggy diffing and needs restricting to only the changed classes.

## Deferred (thin-pass scope, unchanged from earlier reports)

- Referenced fields / direct helper methods in context extraction (protocol `context_priority` items 5-6).
- GumTree AST-based `S_edit` (LOC fallback used throughout).
- CFG/PDG extraction (SootUp) — not attempted; no PVS component currently depends on it.
- PVS weights are placeholder equal weights (0.25 each), not calibrated — RQ2 human-preference collection is
  still pending.

## Recommendation

**GO** to protocol freeze (Step 16) and the ~50-patch pilot (Step 17), on the current fixed pipeline. No
blocking issues found; all four bugs found here are fixed and covered by the diffs in this commit. The
S_vuln-always-0 pattern is worth explicit attention in the pilot's larger, more diverse sample before drawing
any conclusion about the component itself.
