# 50-Patch Pilot Sample (Step 17)

Selected by structural criteria only, never by outcome, from `included_primary` manifest rows.

## Composition
- **11 patches reused from the smoke test** (already checked out/compiled/scored; saves redundant Defects4J
  work) covering Chart-12, Chart-15, Chart-19, Closure-115, Closure-117, Lang-43, Lang-58, Math-28, Math-53,
  Time-15, Time-11.
- **6 "ranking bugs"** (Closure-14, Closure-31, Lang-24, Lang-39, Math-35, Math-4), each contributing 2-4
  patches spanning **both** ground-truth labels for the same bug -- required for `conditional_precision_at_1`
  / MRR / Top-3, which need multiple candidates competing per bug. Up to 2 per project, chosen from the 50
  bugs in the corpus that have mixed-label patches.
- **Remaining slots filled by single patches**, stratified by (project x label x size tercile), excluding
  bugs already used.

## Final composition
- 50 patches, 39 unique bugs
- Projects: Lang 14, Math 13, Closure 12, Chart 7, Time 4
- Labels: overfitting 26, correct 24
- Size tercile: the 33rd and 67th percentile of diff-line-count both land on 2 (the corpus is heavily
  skewed toward tiny diffs -- median is 2 lines, see `reports/SMOKE_TEST_SAMPLE.md`), so the "medium" tercile
  is empty by construction: small 29, large 21. This is a real property of the corpus, not a sampling defect.

Full patch list: `results/pilot_sample.csv`.

## What this pilot additionally runs, beyond the smoke test's single-model pipeline

- **Semantic evaluation with both candidate models** (`claude-haiku-4-5` and `claude-sonnet-5`) on all 50
  patches, to gather the comparative data `protocol.yaml`'s `selected_model` selection_rule requires (parse
  success, stability across the 3 repeated runs, latency, cost). This is the direct evidence `selected_model`
  gets filled in from.
- **Counterexample generation + oracle + S_vuln/S_edit/PVS\*** run with `claude-haiku-4-5` only (not
  dual-model), a deliberate scoping decision given time: doubling the oracle-validation stage (which includes
  real Defects4J compiles, the slow part) across both models would roughly double total pilot wall-clock time
  for a signal the selection_rule doesn't primarily depend on (the rule's stability criterion is measured via
  the semantic stage's 3 repeated runs). Documented here rather than silently narrowed.
- Memorization probe on a subset of the pilot sample.
