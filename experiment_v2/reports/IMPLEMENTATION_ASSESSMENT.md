# v2 Implementation Assessment

**Date:** 2026-09-15 · **Repository HEAD:** `f2e57f5` · **Tag:** `rebuild-v1-snapshot`
**Inspection host:** macOS 26.6.2, Apple M2 (8 cores), 16 GB RAM. No JDK, no Defects4J, OrbStack Docker daemon
stopped. Per the directive this host is for coding/inspection only; it is **not** the authoritative experiment machine.

---

## 1. Repository state

| Path | Content |
|---|---|
| `HANDOVER_to_ClaudeCode.md` | Original brief |
| `APSEC_2026___Beyond_Passing_Test (1)/poster.tex` | Manuscript (2-page IEEEtran); `fig1.png`, `fig1_poster.png`; IEEE template `.tex/.pdf` with placeholder title |
| `APSEC_2026___Beyond_Passing_Test.pdf` | Compiled draft |
| `experiment/` (v1) | 8 scripts in `src/`, draft prompt, derived data, 20-patch pilot logs, features-only evaluation, `report.md` |
| `experiment/data/raw/` | Zenodo `Patches.zip` + extracted files, Defects4J trigger-test files (gitignored) |
| `experiment/.env` | API key (gitignored; not read) |

Working tree clean after committing the last v1 outputs. 12 commits.

## 2. Current commit
`f2e57f5` — tagged `rebuild-v1-snapshot`.

## 3. Working components (v1)
- Dataset reconstruction from Zenodo 3730599 (`Patches.zip` MD5 verified): 887 patches / 245 correct / 642 overfitting / 200 bugs after 21 exclusions.
- Zenodo author notes applied (exact-match audit); `Error` folder excluded.
- Label-leak audit: filename suffix, tool identity, whitespace artefact (64/66 normalized patches overfitting).
- Trailing-whitespace normalization with automated equivalence check (0 mismatches).
- Byte-identical duplicate detection (95 groups, 0 label conflicts).
- Defects4J trigger-test names + failure messages (pinned commit `8c16da8`, 200/200 bugs).
- Handcrafted diff features.
- LLM reviewer: JSON schema output, full logging, caching by config, retries, dry-run, leak-free prompt fields.
- Memorization probe.
- Evaluation: LOPO logistic regression, majority/random baselines, bug-level bootstrap, McNemar, P@1 with ceiling, generated `.tex`.
- 20-patch pilots (Haiku 4.5, Sonnet 5) and probe pilots.

## 4. Missing components (relative to the manuscript method and this directive)
- Defects4J buggy/fixed checkouts, patch application, compilation, test execution.
- Source-context extraction (v1 shows only ~3 diff context lines).
- Programmatic leakage guard (v1 relies on construction, not on a pre-request check).
- Stage 2A executable counterexamples + fixed-version oracle + S_cex.
- Stage 2B CFG / PDG / data-flow analysis.
- SpotBugs/FindSecBugs vulnerability comparison + S_vuln.
- AST-based S_edit.
- Explicit PVS with exported components; missing-S_cex strategy.
- Human preference collection tool, sampling plan, Bradley–Terry calibration.
- GroupKFold-by-bug sensitivity; macro-F1, MCC, balanced accuracy, PR-AUC, correct-patch retention in headline tables; conditional P@1, MRR, Top-3.
- Corrected-label policy (v1 excludes the 12 mislabeled patches rather than correcting them); sensitivity policy.
- Duplicate-collapse sensitivity analysis.
- Per-stage latency and cost instrumentation.
- Protocol / pre-registration / deviations documents; prompt manifest.
- Software test suite; environment capture.

## 5. Proxy components that do not match the manuscript
| v1 component | Why it is a proxy |
|---|---|
| Diff features | Line/hunk counts and regex guards — **not** CFG/PDG static analysis → "Diff-feature baseline" |
| `literal_in_failing_test_message` | Uses failure messages, not test source |
| "Original code" in prompt | ~3 diff context lines, not method/class context |
| LOPO logistic regression "Combined" | Supervised label-based fit — not preference calibration → "Exploratory supervised calibration" |
| McNemar | Patch-level; ignores within-bug correlation → exploratory only |
| Fig. 1 "RLHF" | No reinforcement learning anywhere |

**Manuscript claims without experimental support:** 150 sampled faults; 612 candidates from AlphaRepair/ChatRepair/GPT-4o-mini; overfitting F1 0.81; Precision@1 0.75; counterexample success rate 0.80; latency 34 s and the 30 s target; baseline numbers 0.61/0.75 (ODS)/0.72 (CR)/0.78 & 0.74 (entropy)/0.79 (ES); ablation table (0.68/0.86/0.76, 0.84/0.65/0.73, 0.80/0.82/0.81); per-project F1 (Math/Time 0.83, Closure 0.78); 240 pairwise preferences from 3 developers; Bradley–Terry-learned weights; A100 hardware; reimplemented entropy ranker; complementarity of counterexamples (recall) and static analysis (precision).

## 6. Recommended static-analysis tools
| Purpose | Tool | Notes |
|---|---|---|
| Changed-method localization, source context, custom AST checks | **JavaParser** (3.25+) | Parses Java 1.4–8 sources used by Defects4J; line ranges → methods |
| CFG, dominators, Jimple IR | **SootUp** (latest release on Maven Central; bytecode up to Java 21) | Analyzes compiled `.class` files from `defects4j compile`; runs on its own JDK 21, separate from the Defects4J JDK |
| PDG (data + control dependence) | Own intraprocedural implementation on SootUp Jimple (reaching definitions + post-dominance frontier) | SootUp does not ship a PDG; implementation is small, genuine, and testable |
| Fallback IR | **WALA** | Only if SootUp fails on old bytecode for a project; compatibility documented |
| AST edit distance | **GumTree** (`gumtree-spoon-ast-diff`) | Edit actions between buggy and candidate method ASTs |
| Warnings | **SpotBugs 4.8.x + FindSecBugs 1.13** | Buggy vs candidate class files, same auxclasspath |

Pinned versions (`configs/tools.lock`): SootUp 2.0.0, JavaParser 3.27.0, GumTree 4.0.0-beta3, SpotBugs 4.9.3,
FindSecBugs 1.14.0, WALA 1.6.10. SootUp 2.0.0 also ships `sootup.codepropertygraph` (AST/CFG/CDG/DDG); it is evaluated
on the PC first — if its control- and data-dependence graphs work on Defects4J bytecode they are used for the PDG,
otherwise the own reaching-definitions / post-dominance implementation is used. Versions are also recorded in
`environment.json`.

## 7. CFG extraction
1. `defects4j compile` in the buggy and candidate workspaces (candidate = buggy + candidate patch).
2. Changed methods = JavaParser method declarations whose line ranges intersect the candidate diff hunks (buggy side and candidate side separately; added/removed methods recorded).
3. Load the changed classes with SootUp `JavaView` from each workspace's `dir.bin.classes`; select methods by signature.
4. Build the exceptional `StmtGraph` per method; compute: nodes, edges, branch statements (`JIfStmt`, `JSwitchStmt` targets), cyclomatic complexity `E − N + 2`, trap/exceptional edges, return and throw statements, unreachable nodes (not reachable from entry), loop headers (back edges via dominators).
5. Compare buggy vs candidate: count deltas plus multiset differences over canonicalized statement labels (locals renamed by first occurrence) → new/removed branch edges, early returns, removed paths, changed exception paths, loop-condition changes, switch cases, null/bounds guards (`if` on `null` / comparisons with `length`/`size()`).
6. Any failure (class not found, SootUp exception, method not matched) → row with `analyzer_status` and error; never imputed.

## 8. PDG / data-flow extraction
- Same Jimple bodies. Data dependence: reaching-definitions worklist → def-use edges. Control dependence: post-dominator tree + dominance frontier on the reverse CFG.
- PDG nodes labelled by canonicalized statements; edge multisets compared buggy vs candidate → dependence edges added/removed, changed def-use pairs, new guards controlling changed statements.
- Reachability over the PDG from parameter definitions (`@parameterN`) to return values, field writes, invoke arguments, and throw statements → parameter-to-return / field / external-call / exception dependencies (buggy vs candidate).
- Graph matching is label-based and therefore approximate; this is stated in the protocol. Failures recorded, never synthesized.

## 9. Vulnerability / robustness analysis
- Run SpotBugs + FindSecBugs on the changed classes of buggy and candidate builds (auxclasspath = `cp.compile`).
- Warning identity = (bug type, class, method signature, field/variable name) — line numbers excluded so unrelated line shifts do not create "new" warnings.
- `new_warnings = candidate multiset − buggy multiset`.
- Severity from SpotBugs rank (config): rank 1–4 HIGH, 5–9 MEDIUM, 10–20 LOW.
- Custom JavaParser checks where SpotBugs is blind: removed null guard, removed/emptied catch block, removed bounds check, removed `throw` of validation exception.

## 10. Running generated JUnit tests across Defects4J
- Each generated test is written as its own class in the target class's package (package-private access) under `workspaces/gen_tests/<patch_id>/<test_id>/`.
- Compile with the Defects4J JDK against `defects4j export -p cp.test` of the **buggy** workspace (same public API), output to a per-test directory. Compile failure → `INVALID_COMPILE`.
- Execute with `java -cp <test_classes>:<version cp.test> org.junit.runner.JUnitCore <TestClass>` against fixed_oracle, buggy, and candidate builds, per-run timeout (config, default 60 s), 3 repetitions each; mixed outcomes → `FLAKY`.
- Status per directive: `INVALID_COMPILE`, `INVALID_ORACLE`, `VALID_BUG_REVEALING`, `VALID_NON_DISCRIMINATING`, `FLAKY`, plus `TIMEOUT` recorded explicitly.
- JUnit 3-style and 4-style tests both run under `JUnitCore`; the prompt states the project's JUnit version (read from the buggy test sources).
- Everything runs inside a pinned Docker image (Ubuntu 22.04, pinned JDK, pinned Defects4J commit) on the PC.

## 11. Workspace isolation
```
/data/qc_workspaces/            (outside git, on the PC)
  buggy/<Project>_<N>/          defects4j checkout -v Nb
  candidate/<patch_id>/         copy of buggy + candidate patch applied
  fixed_oracle/<Project>_<N>/   defects4j checkout -v Nf   (chmod -R a-w after build)
  gen_tests/<patch_id>/...
```
- Only `src/oracle_runner.py` knows the `fixed_oracle` root (single constant). Context extraction, prompt building, static analysis, S_edit and S_vuln take workspace objects typed `BuggyWorkspace` / `CandidateWorkspace`; constructors reject any path under `fixed_oracle/`.

## 12. Preventing fixed-code leakage
1. **Type/path guard:** prompt builders accept only buggy/candidate workspace objects; any file path under `fixed_oracle/` raises.
2. **Content guard (`leakage_guard.py`, before every request):**
   - metadata tokens for that patch: ground-truth label words from the manifest, `-plausible`/`-plusible` suffix, archive folder names (`Dsame`, `Ddifferent`, `Dcorrect`, `Doverfitting`, `Patches_ICSE`, `Patches_others`), the patch's APR tool name (word-boundary match), original dataset path;
   - **developer-fix fingerprint:** non-trivial lines added by the developer fix (buggy→fixed diff) that occur neither in the buggy source nor in the candidate diff. If any appears in the payload → abort. (Candidates syntactically identical to the developer fix are legitimate: their text originates from the candidate diff.)
   - Hit → request aborted, `errors.jsonl` entry, no silent sanitizing.
3. **Tests:** canary strings planted in fixed-oracle fixtures; assert they never reach serialized request payloads for semantic and counterexample prompts.

## 13. S_sem
Per run: `S_sem = confidence` if judgement = CORRECT, else `1 − confidence`. Final: mean over the 3 runs.
Binary: CORRECT if `S_sem_final ≥ 0.5`, else OVERFITTING. Overfitting-detection score = `1 − S_sem_final`. Frozen before the pilot.

## 14. S_cex
`S_cex = passed / n_valid_bug_revealing` over tests with status `VALID_BUG_REVEALING`; candidate `TIMEOUT` counts as not passed (to be frozen in protocol). `n_valid = 0` → `S_cex = NA` with a flag; never imputed.

## 15. S_edit
Primary: `min(1, GumTree edit actions / AST node count of the changed buggy methods)`. Comments and whitespace do not produce AST actions. Fallback (recorded per patch when AST diff fails): `min(1, changed executable LOC / executable LOC of changed buggy methods)`. Raw LOC counts kept as sensitivity features.

## 16. S_vuln
`S_vuln = min(1, Σ_{w ∈ new_warnings} weight(severity(w)))` with configured weights (proposal: HIGH 1.0, MEDIUM 0.5, LOW 0.25). Frozen in protocol before the pilot.

## 17. Missing S_cex
The directive's suggested renormalized formula divides a quantity with range `[−(γ+δ), α]` by `(α+γ+δ)`, which is not on the same scale as the full PVS (`[−(γ+δ), α+β]`), so patches with and without S_cex would not be comparable in one ranking.
**Proposed primary strategy (authors decide at freeze):**
`PVS*(p) = [α·S_sem + β·S_cex + γ·(1 − S_edit) + δ·(1 − S_vuln)] / Σ(weights of available components)`.
With all components present and `α+β+γ+δ = 1`, `PVS* = PVS + γ + δ` — a constant shift, so rankings and all threshold-free metrics are identical to the manuscript formula. When S_cex is NA, β drops from numerator and denominator; the result stays in `[0, 1]`. Sensitivity: missingness-indicator logistic model. Both reported.

## 18. v2 directory structure
```
experiment_v2/
  configs/        label policies, pipeline.yaml (timeouts, K, runs, weights), tools.lock
  data/           dataset_manifest.csv, DATASET_PROVENANCE.md, raw/ (gitignored)
  prompts/        semantic_v2.txt, counterexample_v2.txt, probe_v2.txt (immutable after freeze)
  protocol/       PROTOCOL.md, protocol.yaml, PRE_REGISTRATION.md, DEVIATIONS.md
  src/            python orchestration
  tools/java/     Maven module: context extractor, SootUp CFG/PDG, GumTree, SpotBugs runner
  docker/         Dockerfile (Ubuntu 22.04 + JDKs + Defects4J pinned + tools)
  tests/          pytest + JUnit tests for the pipeline
  results/        all machine-readable outputs listed in §BD
  logs/           run logs, errors.jsonl
  reports/        this file, SMOKE_TEST_V2.md, PRE_FLIGHT_REPORT_V2.md
  preference_tool/ local web app + sampling plan
PAPER_CHANGES_PENDING.md (repo root)
```

## 19. Main technical risks
1. **Timeline:** the stated deadline is 2026-09-16. The full reconstruction (Defects4J infrastructure, counterexample oracle, CFG/PDG, SpotBugs, PVS, preference tool, tests, smoke test, pilot) is several working days of engineering plus compute on the PC. The pre-flight report cannot honestly be produced by the deadline.
2. **Authoritative PC access:** this session runs on macOS with no route to the PC. All gates from 3 onward require running on the PC (Claude Code on the PC, or SSH access).
3. **Defects4J version:** v3.0.1 requires Java 11; v2.0.1 uses Java 8, closer to the dataset's era. Measured against the dataset: Closure-63 and Closure-93 are deprecated in both (18 patches); Lang-18 is additionally deprecated in v3.0.1 (2 more patches). These patches get `buggy_checkout_available = false` and are reported, not silently dropped. Final choice by empirical checkout + compile + trigger-test verification on the PC, then frozen.
4. **Patch application:** dataset diffs use paths like `/source/...`, `/src/main/java/...` relative to the source root; hunks may not apply cleanly to Defects4J revisions → `patch_applies` recorded, fuzz disallowed by default.
5. **Counterexample validity:** generated tests may rarely compile (old APIs, JUnit 3, package-private members) or rarely pass the fixed version → S_cex could be NA for most patches. This is a reportable result, not something to tune away.
6. **Old bytecode / build systems:** Closure (Ant, large), Time/Chart old layouts; SootUp on Java 1.4–6 class files untested for these projects.
7. **PDG differencing is approximate** (label-based matching).
8. **Runtime:** 887 patches × candidate build × K=3 tests × 3 versions × 3 repetitions; Closure test compilation is slow. Needs parallel workers on the PC.
9. **API cost:** counterexample generation with method/class context, K=3, plus 3 semantic runs × 3 context conditions — estimated only after the smoke test.
10. **Human preferences:** RQ2 (paper-faithful) needs 3 human raters and 240 comparisons; until then RQ2 is PENDING.

## 20. Development sequence (estimates assume PC access)
| Step | Work | Est. |
|---|---|---|
| 1 | v2 skeleton, environment capture, dataset manifest, label/duplicate policies, provenance, leakage guard + tests (machine-independent) | 0.5–1 d |
| 2 | Docker image on PC; Defects4J buggy/fixed checkouts; compile + trigger-test verification; patch application | 1 d |
| 3 | Java tool module: JavaParser context extraction, changed-method mapping | 0.5–1 d |
| 4 | Semantic prompt v2 (3 context conditions), S_sem | 0.5 d |
| 5 | Counterexample generation, compile, oracle, candidate runs, S_cex | 1.5–2 d |
| 6 | SootUp CFG + PDG features; GumTree S_edit; SpotBugs/FindSecBugs S_vuln | 2–3 d |
| 7 | PVS, evaluation extensions (GroupKFold, metrics, cluster bootstrap, ranking), latency/cost | 1 d |
| 8 | Preference tool, sampling plan, Bradley–Terry | 1 d |
| 9 | Test suite completion, 10-patch smoke test, fixes | 1 d |
| 10 | Protocol freeze, 50-patch pilot, PRE_FLIGHT_REPORT_V2.md, STOP | 1 d |

**Total ≈ 9–12 working days.**
