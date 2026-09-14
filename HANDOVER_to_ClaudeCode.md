# HANDOVER BRIEF — APSEC 2026 paper "Beyond Passing Tests"
## For a fresh Claude Code session on the Lab PC

**Written:** 14 Sep 2026
**Deadline:** Wednesday 16 Sep 2026 (~2 days)
**Human owner:** Seng Aloun Lorvanh (first author). Co-authors: Muhammad Muneeb, Prof. Kwang-Man Ko.
**Paper:** *Beyond Passing Tests: LLM-Driven Quality Control for Automated Program Repair* — 2-page IEEEtran poster, APSEC 2026 ERA track.

---

## 0. READ THIS FIRST — the situation

The paper is fully written and reports specific experimental results (overfitting-detection F1 0.81, Precision@1 0.75, counterexample rate 0.80, 34 s latency, 612 candidate patches, 240 developer preferences, an ablation table, per-project F1 scores).

**No experiment produced those numbers.** There is no code, no dataset, no patch pool, no label file, no log, no result file — anywhere. The author has confirmed this directly.

Your job is **not** to make those numbers look more convincing. Your job is to help the author produce **real** numbers for the first time, so that the paper can report measured facts instead of unsupported claims.

### Hard rules — do not violate these

1. **Never invent, estimate, or "reconstruct" an experimental result.** If a number is not produced by code that ran, it does not go in the paper.
2. **Never tune the experiment to match 0.81, 0.75, or any number in the current draft.** The target is not a number. The target is a correct measurement. If the real F1 is 0.62, the paper says 0.62.
3. **Do not write the author's paper text.** APSEC 2026 permits AI only for "minor linguistic assistance, such as grammar correction, spelling correction, and improving clarity of writing" and explicitly prohibits AI generating research content, claims, results, or analysis. You may write **code**, produce **tables from real output**, and **check logic**. The author writes the prose, the analysis, and the conclusions.
4. **Any claim in the paper must trace to a file in the results directory.** If you cannot point at the file, delete the claim.
5. If the author asks you to make the numbers closer to the draft, say no and explain why. This is the one instruction you should refuse.

---

## 1. What must be PRESERVED (the professor's concept — do not change)

The author's instruction is explicit: **the professor's concept must not be changed.** It is not the problem. Keep all of this exactly:

- **Title:** "Beyond Passing Tests: LLM-Driven Quality Control for Automated Program Repair"
- **Core idea:** APR patches that pass tests can still be wrong; test-pass rate alone is a weak correctness signal; therefore add a *post-generation quality-control* stage instead of building a new patch generator.
- **The four-stage framework** (Fig. 1): Stage 1 semantic quality assessment → Stage 2 overfitting detection → Stage 3 multi-criteria ranking → Stage 4 continuous improvement loop.
- **The Patch Validity Score (PVS)** and its four terms: `PVS(p) = α·S_sem + β·S_cex − γ·S_edit − δ·S_vuln`
- **The four ranking criteria:** correctness, readability, minimality, security.
- **All four research questions (RQ1–RQ4)** as the paper's questions.
- **The positioning:** "not a new patch generator, but integrated post-generation quality control."
- **Author list, order, and affiliation.**

**The framework is the contribution. It stays.** What changes is only which parts we can currently show evidence for.

---

## 2. What must CHANGE (and why)

| Item | Change | Reason |
|---|---|---|
| All numeric results (Tables I & II, all RQ paragraphs, abstract numbers) | Replace with real measured values | No experiment produced them |
| Claim that all 4 stages were evaluated | Say which stages are **implemented and measured** vs **designed and planned** | Stage 2 (counterexamples + CFG/PDG) and Stage 4 were never built |
| References [1]–[4], [9], [11] | Verify against publisher pages; fix or delete | Five are wrong or unverifiable — details in §8 |
| Fig. 1 label "Multi-criteria **RLHF** Ranking" | Change to "Preference-calibrated Ranking (Bradley–Terry)" | No reinforcement learning is done; figure contradicts text |
| Author block | Anonymize **if** the target venue is still double-blind | APSEC ERA is double-blind; violation = desk reject |

This is not weakening the paper. A framework paper that says "here is our design; here is the part we have validated so far; here is the evaluation plan for the rest" is a **normal and respected** Early Research Achievements paper. A paper with unverifiable numbers is not.

---

## 3. The reconciliation: how the concept maps to what we can actually measure

This is the key design. Three of the four research questions can get **real** evidence in two days. One cannot.

| RQ | Paper's original scope | What we can measure by Wednesday | Status in revised paper |
|---|---|---|---|
| **RQ1** — does dual verification (semantic + counterexample) improve detection? | Both signals | Only the **semantic** half. Counterexample generation needs a correctness oracle, which is an open problem. | **Reduce scope**: report LLM semantic assessment vs baselines. Counterexample arm = designed, not yet evaluated. |
| **RQ2** — does multi-criteria ranking improve top-1 selection? | Yes | **Yes — fully.** The dataset groups multiple candidate patches per bug, so Precision@1 is directly computable. | **Measured** |
| **RQ3** — do the detection modules contribute complementary signals? | counterexample vs static | **Yes, honest version:** LLM review vs code-diff features vs combined. Same ablation shape, real numbers. | **Measured** (modules redefined) |
| **RQ4** — is latency acceptable for CI/CD? | Yes | **Yes — fully.** Measure real wall-clock and API cost per patch. | **Measured** |

So the paper keeps its structure and its four RQs. Only RQ1 narrows, and the paper says so plainly.

---

## 4. THE EXPERIMENT TO BUILD

### 4.1 Core design decision

**Do not generate patches. Do not install Defects4J. Do not run test suites.**

Use a public dataset where APR-generated patches already exist and already carry human correctness labels. This removes weeks of infrastructure from the critical path and is a completely standard methodology in the patch-correctness-assessment literature.

### 4.2 Dataset (primary)

**Wang et al., ASE 2020, "Automated Patch Correctness Assessment: How Far are We?"**
Zenodo: https://zenodo.org/records/3730599

- Download **`Patches.zip` only — 1.2 MB.** Ignore the other files (they total 1.3 GB and we do not need them).
- Coverage: Defects4J projects Chart (26 bugs), Closure (21), Lang (28), Math (50), Time (6) — 131 bugs.
- Patches come from many APR tools (Kali, Arja, SimFix, CapGen, Jaid, ACS, Nopol, jGenProg, and others), plus ~269 patches from prior research.
- Every patch is **plausible** (it passes the project's test suite) and carries a **binary human label**: correct or overfitting. This is exactly the setting the paper is about.

**Known label problems — the dataset authors document these. Exclude them and record the exclusions:**
- 12 mistakenly labeled patches
- 6 patches that fail the plausibility check
- 3 borderline cases
- 2 Mockito-only patches

Write the exclusion list to `data/excluded.csv` with a reason column. This belongs in Threats to Validity and it makes the paper look careful.

**Backup dataset if Patches.zip is unusable:** https://github.com/ASSERT-KTH/drr (Defects4J patch correctness data from the KTH/Monperrus group).

### 4.3 Pipeline to implement

```
Patches.zip
   ↓  parse
per-patch record: {bug_id, project, tool, diff, buggy_code, patched_code, label}
   ↓
   ├── Signal A: LLM review  → S_sem  (Stage 1 of the professor's framework)
   ├── Signal B: diff features → S_edit (part of PVS)
   ↓
   combine (logistic regression, leave-one-project-out CV)
   ↓
   ├── detection metrics  (RQ1, RQ3)
   ├── Precision@1 per bug (RQ2)
   └── latency + cost      (RQ4)
```

### 4.4 Signal A — LLM semantic review (this is Stage 1, `S_sem`)

One named model, one fixed prompt, temperature 0, structured JSON output.

Model: **Anthropic API** (the author has a key). Suggest `claude-haiku` class for cost, or a Sonnet-class model for quality — **run a 20-patch pilot with both and let the author choose based on measured agreement, not on which gives a nicer number.** Record the exact model ID string in the results file; the paper must name it.

The review checklist must reflect the professor's four criteria (correctness, readability, minimality, security) so it stays faithful to the concept. **Draft below — the author must review and adjust it, because the checklist is their methodology, not yours:**

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

Requirements:
- Temperature 0. Log the full raw response for every patch — the artifact must contain them.
- Retry on API error with exponential backoff; never silently drop a patch.
- Cache by patch id so a crash does not cost money twice.
- Log per-call latency (seconds) and token counts.
- Run each patch **3 times** if budget allows and report self-consistency. This directly addresses the "single seed" weakness the current draft admits to.

### 4.5 Signal B — diff features (this is `S_edit`)

Cheap, deterministic, no API. Compute from the diff:
- lines added, lines removed, total changed lines
- number of hunks
- whether the patch only deletes code (classic overfitting signal)
- whether the patch adds a conditional guard
- whether a literal from a failing test appears in the patch (classic overfitting signal)

If `javalang` or `tree-sitter-java` installs cleanly, add AST node-change count. **If it does not install in 20 minutes, skip it** and note it as future work. Do not lose a day to tooling.

### 4.6 Combination and evaluation

- **Model:** logistic regression on [LLM judgement, LLM confidence, diff features]. Simple and defensible.
- **Validation:** **leave-one-project-out cross-validation** (train on 4 projects, test on the held-out one, rotate). Use this rather than a random split — it pre-empts the "you tuned on your test set" criticism, which is a criticism the current draft is wide open to.
- **Positive class:** overfitting. State this explicitly; F1 is meaningless without it.

**Baselines (all required):**
1. Majority class
2. Random (stratified)
3. Diff-features only
4. LLM only
5. Combined (the proposed method)

**Metrics:**
- Confusion matrix, precision, recall, F1, accuracy — **plus the class base rate**, so F1 is interpretable
- **Bootstrap 95% confidence intervals**, 10,000 resamples, resampling at the *bug* level not the patch level (patches from the same bug are not independent)
- **McNemar's test** for proposed vs each baseline, with the p-value reported
- **Precision@1**: for each bug with ≥2 candidate patches, rank by score, check whether the top-1 is labeled correct. Also report the **ceiling** — the fraction of bugs that have at least one correct patch at all. Without the ceiling, Precision@1 cannot be judged.
- **Latency and cost**: mean and median seconds per patch, USD per patch, USD total

### 4.7 Required output files

```
results/
  raw_llm_responses.jsonl      # every API call, full response, latency, tokens
  patch_features.csv           # diff features per patch
  predictions.csv              # per patch: true label, each method's prediction
  metrics.json                 # all metrics + CIs + p-values
  confusion_matrices.txt
  precision_at_1.csv
  cost_and_latency.json
  table1_main.tex              # generated, not hand-typed
  table2_ablation.tex          # generated, not hand-typed
  RESULTS.md                   # plain-language summary of what was measured
data/
  excluded.csv                 # excluded patches + reason
  dataset_stats.json           # n bugs, n patches, class balance, per project
```

**Tables must be generated by script into .tex, never typed by hand.** This guarantees the paper matches the data.

---

## 5. Lab PC environment setup

No Java, no Defects4J, no GPU needed. This runs on any machine with Python and internet.

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install anthropic pandas numpy scikit-learn scipy tqdm
# optional, timebox to 20 min: pip install javalang
export ANTHROPIC_API_KEY=...    # Windows: setx ANTHROPIC_API_KEY ...
```

**Check these before starting — they are the real blockers:**
1. Does the Lab PC reach `zenodo.org`? (university firewalls sometimes block it)
2. Does it reach `api.anthropic.com`? (this is the one that kills the plan if blocked)
3. Is there credit on the API key? Estimate first with the pilot.
4. Python 3.10 or newer.

**Never commit the API key.** Add `.env` and `.venv` to `.gitignore` immediately.

**Initialize a git repository on day one.** The absence of version history is part of how this situation happened. Commit after every working step.

---

## 6. Execution order (2 days — do it in this sequence)

**Step 1 (30 min).** Download `Patches.zip`, unzip, write the parser, print dataset statistics: how many bugs, how many patches, class balance overall and per project. **Show these numbers to the author before going further.** If the class balance is extreme, F1 needs careful interpretation.

**Step 2 (45 min).** Implement diff features. These need no API and give a first honest baseline immediately. If everything else fails, a features-only result is still a real result.

**Step 3 (1 hour).** Implement the LLM reviewer. Run on **20 patches only**. Check: does the JSON parse, does the judgement look sensible, what is the cost per patch, what is the latency? Multiply by N to project the full cost. **Report the projected cost to the author and wait for approval before the full run.**

**Step 4 (30–60 min run time).** Full run. Log everything. Use a cache so a crash is not fatal.

**Step 5 (1 hour).** Metrics, bootstrap CIs, McNemar, Precision@1, generate the .tex tables, write `RESULTS.md`.

**Step 6.** Hand the real numbers to the author. **The author writes the results paragraphs themselves.** You may fix grammar afterwards.

**Step 7 (parallel, can be done any time).** The safe fixes in §8 — these are worth doing regardless of how the experiment turns out.

---

## 7. What the revised paper will honestly be able to say

Draft this structure for the author to fill in — **do not write the prose**:

- The four-stage framework: unchanged, presented as the design contribution.
- "In this early study we implement and evaluate Stage 1 (semantic assessment) and the edit-size component of the Patch Validity Score. Stage 2 (counterexample generation with CFG/PDG cross-checking) and Stage 4 (CI/CD feedback loop) are designed but not yet evaluated; Section X describes the planned evaluation."
- Real Table I: detection metrics vs 4 baselines, with CIs and p-values.
- Real Table II: ablation — LLM only / features only / combined.
- Real Precision@1 with the ceiling stated.
- Real latency and cost.
- Threats to validity, which must now include: **benchmark memorization** (these patches have been public since 2020 and may be in the model's training data — this is the single most likely reviewer attack), label noise in the source dataset, single model, single prompt, Java only, and the reduced scope of RQ1.

An honest result that shows the LLM does *poorly* is still publishable and still interesting. Do not treat a low number as a failure of the work.

---

## 8. Safe fixes — do these regardless of the experiment

These are defects in the current `poster.tex` independent of the results.

**Anonymity (if the venue is still double-blind):** remove the whole `\author{}` block, all three names, "Sangji University", "Wonju-si, South Korea", and all three ORCID numbers.

**References — five are wrong. Verify every one against the publisher page:**

| Key | Problem |
|---|---|
| `lee2024survey` | Real paper is "A Survey of LLM-based Automated Program Repair: **Taxonomies, Design Paradigms, and Applications**", arXiv 2506.23749, **2025**. Subtitle, venue and year in the draft are wrong. |
| `zhang2023llm4patchcorrect` | Real paper: "Leveraging Large Language Model for Automatic Patch Correctness Assessment", **IEEE TSE 2024**, **Xin Zhou et al.** Author, title and venue in the draft are wrong. |
| `wang2024entropy` | "Entropy-guided Patch Ranking for APR, ASE 2024" — **could not be found. Probably does not exist.** Delete or replace. |
| `zhao2025prism` | PRISM is real but published as "Enhancing APR with PRISM: A Semantic-Based Approach to Overfitting Patch Detection", **PACMPL (OOPSLA)**, not ICSE 2025. |
| `fraser2011evosuite` | Cited in the text as "test-based pass/fail (**ODS**)". EvoSuite is a test generator; ODS is a different system entirely (Ye, Martinez, Monperrus). Wrong attribution. |
| `legoues2012genprog`, `park2024security` | **Never cited in the body.** Cite them or remove them. |

Add proper related work on patch-correctness assessment — it is the closest literature and the draft barely covers it: Ye/Martinez/Monperrus (ODS), Tian et al., Wang et al. ASE'20, Invalidator, Shibboleth.

**Text fixes:**
- Section II: `"TBar~\cite{liu2019tbar} relies on manually defined repair templates without;"` — **the sentence is broken and unfinished.**
- Section IV: "All methods use on identical hardware" → "All methods run on identical hardware"
- "**Automatic** Program Repair" (abstract, intro, keywords) vs "**Automated**" (title) — use "Automated" everywhere.
- Abstract "slightly **exceeding** the 30 s target" vs RQ4 "narrowly **missing** the 30 s target" — contradictory. Also the 30 s target has no source; cite one or delete it.
- Intro citation order `~\cite{wang2024entropy}, ~\cite{zhang2023llm4patchcorrect}` — fix order and the stray space.
- "ensuring a controlled and objective comparison" — delete "objective", it is an overclaim.
- Table I header "Prior best" mixes three different systems (ODS, CR, ES) in one column — split them. "(ES)" is never defined.
- Fig. 1: relabel Stage 3 from "RLHF Ranking" to "Preference-calibrated Ranking (Bradley–Terry)". Bradley–Terry fitting is not reinforcement learning.
- The abstract promises ranking by **readability**, but PVS has no readability term. Either add one or drop the claim.
- Add a data-availability statement with an anonymous Zenodo/Figshare link to the artifact.
- Delete `IEEE-conference-template-062824.tex/.pdf` from the submission folder — it still has the placeholder title "AI Agent Baesd APR(*Placeholder)*" with the author names in it.

---

## 9. Open questions the author must answer

1. **Which venue and deadline is Wednesday actually for?** Both APSEC 2026 deadlines have passed (ERA 10 Aug, Technical 20 Jul; ERA notification 28 Sep). This changes the page limit and whether anonymity is required.
2. **Has Prof. Ko been told that the current numbers cannot be supported?** As of this handover, no. This must happen before submission, not after.
3. **Does Muhammad Muneeb have the original scripts or data anywhere?** If yes, everything in this brief may be unnecessary.
4. **What is the API budget?** The pilot will give a real estimate; get approval before the full run.

---

## 10. Definition of done

- [ ] `results/metrics.json` exists and was produced by code that ran
- [ ] Every number in the paper traces to a file in `results/`
- [ ] Tables are generated `.tex`, not hand-typed
- [ ] Confidence intervals and p-values are reported, not just point estimates
- [ ] All references verified against publisher pages
- [ ] Artifact is packaged and uploadable to anonymous Zenodo
- [ ] The paper states clearly which stages were evaluated and which were not
- [ ] Prof. Ko knows the situation
- [ ] The author wrote the analysis and conclusions themselves
