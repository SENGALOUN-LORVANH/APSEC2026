# Experiment Status Report — "Beyond Passing Tests" (APSEC 2026)

**Date:** 2026-09-14 · **Repo commit at writing:** `b204460` · **Status:** pilot complete; full run not started

> Internal engineering report for the authors. It records what was built, what was measured, and what is still
> undecided. It is **not paper text**: the analysis, claims, and prose in the paper must be written by the authors
> (APSEC 2026 AI policy). Every number below comes from a file in `experiment/` (named in each section).
> Pilot numbers (n = 20) are sanity checks, not results.

---

## 1. Why this experiment exists

The current `poster.tex` reports results (F1 0.81, Precision@1 0.75, 34 s, 612 patches, 240 preferences, ablation
table) that no experiment produced. This experiment produces real measurements for the parts of the framework that
can be evaluated now, while keeping the professor's concept unchanged (title, four-stage framework, PVS, four
criteria, RQ1–RQ4).

| RQ | What is measurable now | Status |
|---|---|---|
| RQ1 detection | Stage 1 LLM semantic assessment vs baselines (counterexample arm not implemented) | Pipeline ready; baselines measured |
| RQ2 top-1 selection | Precision@1 per bug with ceiling and random expectation | Pipeline ready; baselines measured |
| RQ3 complementary signals | LLM only / diff features only / combined | Pipeline ready |
| RQ4 latency & cost | Wall-clock and USD per call / patch | Measured in pilot |

---

## 2. Dataset

**Source:** Wang et al., "Automated Patch Correctness Assessment: How Far are We?", ASE 2020 —
Zenodo record 3730599, `Patches.zip` (MD5 `11203b88e6ae8a657757c6b5842d5a46`, verified).
All patches are plausible (pass the project tests) and carry a human correctness label.

**After exclusions** (`data/dataset_stats.json`):

| | Patches | Correct | Overfitting | Overfitting rate | Bugs |
|---|---|---|---|---|---|
| **All** | **887** | 245 | 642 | **0.724** | 200 |
| Chart | 157 | 55 | 102 | 0.650 | 22 |
| Closure | 238 | 44 | 194 | 0.815 | 73 |
| Lang | 142 | 43 | 99 | 0.697 | 34 |
| Math | 344 | 101 | 243 | 0.706 | 66 |
| Time | 6 | 2 | 4 | 0.667 | 5 |

- 21 APR tools. 95 groups of byte-identical diffs (0 with conflicting labels).
- Ranking setting: 136 bugs have ≥ 2 candidate patches; 62 of them have ≥ 1 correct patch.
- The handover brief said 131 bugs; the measured number is **200**.

**Exclusions — 21 patches** (`data/excluded.csv`, `data/zenodo_exclusion_matches.csv`):
- 20 match the dataset authors' own notes on Zenodo: 12 mistakenly labeled, 3 borderline, 5 failing the plausibility
  check (the 6th listed ID, `Kali-Closure-133`, and both Mockito patches are not in `Patches.zip`).
- 1 patch in the source's unlabeled `Error` folder (`patch1-Closure-106-SimFix-plausible`).
- Current policy: mislabeled and borderline patches are **excluded**, not relabeled (authors to confirm, §8).

**Failing-test information:** Defects4J trigger tests (test names + failure messages, stack frames removed),
fetched for 200/200 bugs from `rjust/defects4j` commit `8c16da8230843cdc918eaf4ddb449637f02b83c6`
(`data/trigger_tests.json`).

---

## 3. Data-quality findings (label leakage)

These were found during preprocessing and handled before any model saw the data.

1. **Filename leaks the label.** In the ICSE subset the `-plausible` filename suffix appears on all 500 overfitting
   patches and on 0 correct ones. APR tool name is also strongly label-correlated (e.g. SOFix 21 correct / 1
   overfitting; Kali 3 / 60). → The LLM never sees filename, path, tool, or suffix; none are used as features.
2. **Trailing-whitespace noise is label-correlated.** 66 diffs contained changes that are whitespace-only;
   **64 of the 66 are overfitting** (`data/normalization_check.json`). Example: one diff showed 7,614 changed lines
   for a 4-line change. → Those 66 diffs were rebuilt ignoring trailing whitespace (Java-semantics-neutral); the other
   821 are byte-identical to the source. An automated check applying each rebuilt diff to the original found
   **0 mismatches** (`src/check_normalization.py`).

---

## 4. Pipeline

```
Patches.zip ─► parse_dataset.py ─► data/patches.jsonl (887)          check_normalization.py
                     │                                                 (0 mismatches)
fetch_trigger_tests.py ─► data/trigger_tests.json
                     │
     ┌───────────────┴───────────────┐
diff_features.py (Signal B, S_edit)   llm_review.py (Signal A, S_sem)   memorization_probe.py
     └───────────────┬───────────────┘
               evaluate.py
  LOPO logistic regression · 5 methods · bug-level bootstrap (10,000) · McNemar · Precision@1
  → metrics.json, predictions.csv, precision_at_1.csv, cost_and_latency.json, table1_main.tex, table2_ablation.tex
```

**Signal B — diff features** (`results/patch_features.csv`): lines added/removed/total (log1p), code lines
added/removed, hunks, files, only-deletes, adds-conditional-guard, literal-from-failing-test-message
(proxy: Defects4J provides failure messages, not test source).

**Evaluation design** (`src/evaluate.py`):
- Positive class = OVERFITTING.
- Leave-one-project-out CV; metrics pooled over all out-of-fold predictions (so the 6-patch Time fold does not
  distort the overall metrics; per-project numbers report n).
- Methods: majority class, random (stratified), diff features only, LLM only, combined (LR on features + LLM).
- 95% CIs by bootstrap over **bugs** (10,000 resamples, seed 2026); exact McNemar tests; Precision@1 with ceiling
  and random-ranking expectation; ties handled by expected value.

---

## 5. The review prompt (verbatim, **DRAFT — requires author approval**)

File: `prompts/review_v1_DRAFT.txt` · prompt SHA-256 (first 16 hex): `3e2d5a78c73c90a7`
Checklist copied verbatim from the handover brief §4.4; it reflects the four ranking criteria (correctness,
readability, minimality, security). The full run is blocked by the script until the file is approved and renamed.

### System prompt
```
You are reviewing a candidate patch for a Java bug.

Input: the bug's failing-test information, the original code, and the patch diff.

Answer each question, then give a final judgement.
1. Does the patch address the general cause of the bug, or only the specific
   failing input? (general / specific-only / unclear)
2. Does the patch delete or weaken functionality instead of fixing it?
3. Does the patch change behaviour outside what the bug requires?
4. Is the patch minimal for what it claims to fix?
5. Does the patch introduce a readability or maintainability problem?
6. Does the patch introduce a possible security or robustness problem
   (null handling, bounds, resource handling)?

Final: is this patch CORRECT or OVERFITTING?
Also give a confidence between 0.0 and 1.0.

Return strict JSON:
{"q1": "...", "q2": "...", "q3": "...", "q4": "...", "q5": "...", "q6": "...",
 "judgement": "CORRECT" | "OVERFITTING", "confidence": 0.0}
```

### User message template
```
Failing test(s) that the patch makes pass:
{failing_tests}

Failure message(s) on the buggy version:
{failure_messages}

Patch diff (context lines show the original code around the change):
{diff}
```

### Implementation details the authors should review
- "The original code" is limited to the ~3 context lines inside the diff; the dataset has no full source files.
- Failure messages are capped at 2,000 characters each and 8,000 in total; every cut is marked in the prompt
  (`[... truncated N characters ...]`) and flagged in the log.
- Output is constrained by a JSON schema (`output_config.format`): `q1`–`q6` strings, `judgement` ∈
  {CORRECT, OVERFITTING}, `confidence` number.
- `max_tokens` = 16,000 (4,096 truncated 2/20 Sonnet pilot responses).
- Haiku 4.5: `temperature = 0` (sent via `extra_body`; SDK 1.x removed the argument).
- Sonnet 5: temperature is rejected by the API, so runs are not deterministic → 3 runs per patch planned.
- Every call logged in full (raw response, latency, tokens, request id, settings); cached by
  (model, prompt SHA, settings, patch, run); parse failures retried.

### Memorization probe prompt (`src/memorization_probe.py`, `probe_v1`)
Input: the same diff the reviewer sees (no tests, filename, tool, or label).
```
You will see a code diff from a Java project. Answer from memory only.
1. Which Defects4J project is it from (Chart, Closure, Lang, Math, Time, or another)?
2. Which Defects4J bug number is it? Use null if you do not know; do not guess.
3. Have you seen this exact patch in a published automated-program-repair patch dataset? If so, was it labeled CORRECT or OVERFITTING there? Use UNKNOWN if you do not recall.
```
Schema: `project` string, `bug_number` integer or null, `recalled_label` ∈ {CORRECT, OVERFITTING, UNKNOWN}.

---

## 6. Measured so far

### 6.1 Baselines without the LLM (full dataset, n = 887)
Source: `results/metrics.json` (generated at commit `1a57473`; inputs unchanged since).
Base rate (overfitting) = 0.724.

| Method | Precision | Recall | F1 [95% CI] | Accuracy | Correct patches kept | AUC |
|---|---|---|---|---|---|---|
| Majority class | 0.724 | 1.000 | 0.840 [0.800, 0.876] | 0.724 | 0.000 | 0.427* |
| Random (stratified) | 0.722 | 0.692 | 0.706 [0.666, 0.744] | 0.584 | 0.302 | 0.490 |
| Diff features only | 0.727 | 0.984 | 0.837 [0.797, 0.873] | 0.722 | 0.033 | 0.611 |

\*Majority uses the constant training base rate as its score, which differs slightly across folds.

- Diff features vs majority: ΔF1 −0.003 [−0.009, 0.002], McNemar p = 0.81 (8 vs 10 discordant).
- Diff features vs random: ΔF1 +0.130 [0.106, 0.157], McNemar p = 2.0 × 10⁻¹³.
- Because the positive class is 72% of the data, predicting "overfitting" for everything already gives F1 0.84.
  Specificity ("correct patches kept") and AUC should be reported alongside F1.

**Precision@1** (136 bugs with ≥ 2 patches; `results/precision_at_1.csv`):

| Method | P@1 [95% CI] | P@1 among bugs with a correct patch |
|---|---|---|
| Random ranking (expected) | 0.249 | — |
| Majority class (all tied) | 0.249 [0.193, 0.307] | 0.545 |
| Random (stratified) | 0.243 [0.177, 0.316] | 0.532 |
| Diff features only | 0.272 [0.203, 0.346] | 0.596 |
| **Ceiling** (fraction of bugs with any correct patch) | **0.456** | 1.000 |

### 6.2 LLM pilot (n = 20: 10 correct, 10 overfitting; seed 2026)
Sources: `results/raw_llm_responses_{haiku,sonnet}_pilot.jsonl`, `data/pilot_ids_n20_seed2026.txt`.
Prices: Anthropic list prices (Haiku 4.5 $1/$5, Sonnet 5 $2/$10 per 1M input/output tokens) — verify before publishing.

| Model / settings | Calls | Parsed | Latency mean / median / max (s) | Tokens in / out (mean) | Cost | Label match† |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5`, temp 0, max 4,096 | 20 | 20 | 2.69 / 2.10 / 6.22 | 1,003 / 63 | $0.027 | 13/20 |
| `claude-sonnet-5`, default effort, max 4,096 | 20 | 18 | 14.82 / 9.91 / 46.06 | 1,259 / 1,233 | $0.297 | 15/18 |
| `claude-sonnet-5`, default effort, max 16,000 (retry of 2) | 2 | 1 | 94.2 mean; max 146.8 | 1,173 / 9,818 | $0.201 | 0/1 |
| `claude-sonnet-5`, effort medium, max 16,000 (1 patch) | 1 | 1 | 34.67 | 1,107 / 3,252 | $0.035 | 0/1 |

†Sanity check only (n = 20); not a result.

- One patch (`patch1-Lang-12-SimFix-plausible`) made Sonnet at default effort think until the token limit twice
  (4,096 and 16,000 tokens, no answer). `effort = medium` answered in 3,252 tokens.
- Final per-patch answers (latest parsed call per patch): Haiku and Sonnet agree on **14/20**.
- Haiku's q1–q6 answers are one-word; Sonnet returns a thinking block plus the JSON.
- **Projected full-run cost** (887 patches × 3 runs, from default-setting pilot means): Haiku ≈ **$3.52**;
  Sonnet (default effort) ≈ **$39.53**. Sonnet at medium effort needs its own pilot for a reliable estimate.
- Total spend on review pilots: ≈ $0.56 (probe calls not included).

### 6.3 Memorization probe pilot (same 20 patches)
Sources: `results/memorization_probe_claude-{haiku-4-5,sonnet-5}_pilot.jsonl`.

| Model | Project correct | Bug number given | **Bug ID correct** | Label "recalled" | Recalled label correct |
|---|---|---|---|---|---|
| Haiku 4.5 | 20/20 | 13 | **0/20** | 13 | 9/13 |
| Sonnet 5 | 20/20 | 18 | **0/20** | 8 | 6/8 |

- Project identification is trivial (the file path in the diff names the package).
- Neither model identified any bug ID. With 20 patches this is not conclusive; the full probe covers all 887.

---

## 7. Reference verification (for `poster.tex`)

| Key in draft | Problem | Verified entry |
|---|---|---|
| `lee2024survey` | Wrong authors, subtitle, venue, year | B. Yang, Z. Cai, F. Liu, B. Le, L. Zhang, T. F. Bissyandé, Y. Liu, H. Tian, "A Survey of LLM-based Automated Program Repair: Taxonomies, Design Paradigms, and Applications," arXiv:2506.23749, 2025 |
| `zhang2023llm4patchcorrect` | Wrong authors, title, venue | X. Zhou, B. Xu, K. Kim, D. Han, H. H. Nguyen, T. Le-Cong, J. He, B. Le, D. Lo, "Leveraging Large Language Model for Automatic Patch Correctness Assessment," IEEE TSE, 2024, doi:10.1109/TSE.2024.3452252 |
| `wang2024entropy` | No such ASE 2024 paper found | Closest real work: A. Z. H. Yang, S. Kolak, V. J. Hellendoorn, R. Martins, C. Le Goues, "Revisiting Unnaturalness for Automated Program Repair in the Era of Large Language Models" (entropy-delta ranking); arXiv:2404.15236; listed in ICSE 2025 proceedings — confirm venue |
| `zhao2025prism` | Wrong authors, title, venue | D. Song, H. Oh, "Enhancing APR with PRISM: A Semantic-Based Approach to Overfitting Patch Detection," Proc. ACM Program. Lang. 9(OOPSLA2), Art. 392, Oct. 2025, doi:10.1145/3763170 |
| `xia2023chatrepair` | Wrong year | C. S. Xia, L. Zhang, "Automated Program Repair via Conversation: Fixing 162 out of 337 Bugs for $0.42 Each using ChatGPT," ISSTA 2024, doi:10.1145/3650212.3680323 |
| `park2024security` | Not found; never cited in text | Delete |
| `legoues2012genprog` | Never cited in text | Cite or delete |
| `fraser2011evosuite` | Cited as "ODS"; EvoSuite is a test generator, ODS is a different system | Fix attribution |

Not yet re-verified: `liu2019tbar`, `xia2022alpharepair`, `just2014defects4j`, `fraser2011evosuite` metadata.

Other draft issues (handover §8): broken TBar sentence; "use on identical hardware"; "Automatic" vs "Automated";
abstract "slightly exceeding" vs RQ4 "narrowly missing" 30 s; unsourced 30 s target; Fig. 1 "RLHF" label;
readability promised but absent from PVS; author block if double-blind; template `.tex` with placeholder title in
the submission folder.

---

## 8. Decisions needed from the authors

1. **Model for the full run:** Haiku 4.5 (≈ $3.5, fast, shallow answers) or Sonnet 5 at `effort = medium`
   (needs a 20-patch re-pilot at that setting; ≈ tens of dollars).
2. **Approve or edit the review prompt** (§5), including the failure-message caps.
3. **Exclusion policy:** keep excluding the 12 mislabeled + 3 borderline patches, or relabel per the dataset notes.
4. **Candidate novelty components** (author's choice under the APSEC AI policy):
   memorization probe (full run) · context ablation (diff-only vs diff + failing tests) · the label-leak finding
   (§3) · PVS weights learned from LOPO logistic regression · self-consistency / calibration over 3 runs.
5. **Venue questions** (handover §9): which deadline, page limit, double-blind?; Prof. Ko informed?; original
   scripts/data from co-author?

---

## 9. Reproduce

```bash
cd experiment
python3 -m venv .venv && .venv/bin/pip install anthropic pandas numpy scikit-learn scipy tqdm
# put ANTHROPIC_API_KEY=... in experiment/.env (gitignored)
.venv/bin/python src/parse_dataset.py
.venv/bin/python src/check_normalization.py
.venv/bin/python src/fetch_trigger_tests.py
.venv/bin/python src/diff_features.py
.venv/bin/python src/llm_review.py --model claude-haiku-4-5 --pilot 20 --log results/raw_llm_responses_haiku.jsonl
.venv/bin/python src/memorization_probe.py --model claude-haiku-4-5 --pilot 20
.venv/bin/python src/evaluate.py            # add --llm main=results/raw_llm_responses.jsonl after the full run
```

`data/raw/` (downloaded source data) is not committed; everything else is under git.
