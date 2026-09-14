# Paper Changes Pending

Tracks what must change in `poster.tex` once real v2 results exist. **Do not edit manuscript results yet.**
Any pilot number is: **PRELIMINARY — NOT PAPER RESULTS**.

## 1. Unsupported claims (no experiment produced them)
| Location | Claim | Status |
|---|---|---|
| Abstract, §IV | 150 stratified Defects4J faults; 612 candidates from AlphaRepair, ChatRepair, GPT-4o-mini | Dataset differs: Wang et al. ASE'20 patches (887 after policy) |
| Abstract, §V, §VI | Overfitting F1 0.81 | Awaiting v2 |
| Abstract, §V, §VI | Precision@1 0.75 | Awaiting v2 + human preferences |
| Abstract, Table I | Counterexample success rate 0.80; ES 0.79 | Awaiting Stage 2A |
| Abstract, RQ4, Table I | 34 s latency; 30 s target; 20–90 s range; 8 s, 25 s | Awaiting per-stage timing; 30 s target has no source |
| Table I | Baseline 0.61/0.58; ODS 0.75; CR 0.72; entropy 0.78/0.74 | Baselines not run |
| Table II, RQ3 | Counterexample 0.68/0.86/0.76; static 0.84/0.65/0.73; combined 0.80/0.82/0.81 | Hypothesis only |
| RQ3 | Math/Time F1 0.83, Closure 0.78; context-slicing explanation | Awaiting v2 |
| §III Stage 3 | 240 pairwise preferences from 3 developers; Bradley–Terry-learned weights | Data do not exist; collection tool pending |
| §IV | 1×A100 40GB, 32-core CPU | Use recorded PC hardware |
| §IV | Reimplemented entropy-based ranker | Not implemented |
| Conclusion | All summary numbers | Awaiting v2 |

## 2. Claims awaiting the real experiment
- RQ1: semantic + counterexample improves detection (report precision, recall, specificity, macro-F1, MCC, PR-AUC, correct-patch retention).
- RQ2: preference-calibrated ranking — PENDING until human preferences exist.
- RQ3: complementarity of counterexamples and static analysis (overlap matrices).
- RQ4: reframe as runtime/monetary cost and dominant stages.

## 3. References needing correction (verified 2026-09-14)
| Key | Action |
|---|---|
| `lee2024survey` | → B. Yang et al., "A Survey of LLM-based Automated Program Repair: Taxonomies, Design Paradigms, and Applications," arXiv:2506.23749, 2025 |
| `zhang2023llm4patchcorrect` | → X. Zhou et al., "Leveraging Large Language Model for Automatic Patch Correctness Assessment," IEEE TSE, 2024, doi:10.1109/TSE.2024.3452252 |
| `wang2024entropy` | No such paper found. Candidate: A. Z. H. Yang et al., "Revisiting Unnaturalness for Automated Program Repair in the Era of Large Language Models" (entropy-delta); confirm venue |
| `zhao2025prism` | → D. Song, H. Oh, "Enhancing APR with PRISM: A Semantic-Based Approach to Overfitting Patch Detection," PACMPL 9(OOPSLA2), Art. 392, 2025, doi:10.1145/3763170 |
| `xia2023chatrepair` | Year → ISSTA 2024, doi:10.1145/3650212.3680323 |
| `park2024security` | Not found; uncited → delete |
| `legoues2012genprog` | Uncited → cite or delete |
| `fraser2011evosuite` | Cited as "ODS" → wrong attribution |
| `liu2019tbar`, `xia2022alpharepair`, `just2014defects4j` | Not yet re-verified |
| All | Re-verify every entry (authors, title, venue, year, pages, DOI, supports claim) before submission |

Missing related work on patch-correctness assessment: ODS (Ye, Martinez, Monperrus), Tian et al., Wang et al. ASE'20, Invalidator, Shibboleth, PATCH-SIM.

## 4. Terminology corrections
- "Automatic" → "Automated" Program Repair throughout.
- Fig. 1 Stage 3 "RLHF Ranking" → "Preference-calibrated Ranking (Bradley–Terry)".
- Diff statistics must never be called CFG/PDG analysis.
- Label-supervised weight fitting = "exploratory supervised calibration", not preference learning.
- "ensuring a controlled and objective comparison" → drop "objective".
- Readability is promised as a ranking criterion but has no PVS term → add or drop.
- Broken sentence: "TBar relies on manually defined repair templates without;".
- "All methods use on identical hardware" → grammar.
- Abstract "slightly exceeding" vs RQ4 "narrowly missing" the 30 s target (contradiction; target unsourced).
- Author block: anonymize if the venue is double-blind.
- Remove `IEEE-conference-template-062824.tex/.pdf` (placeholder title, author names) from the submission folder.

## 5. Possible new contributions (author decision)
- Label leakage in a widely used patch-correctness benchmark (filename suffix, tool identity, whitespace artefacts).
- Validity rates of LLM-generated counterexamples under a fixed-version oracle.
- Memorization diagnostic for LLM patch assessors.
- Context ablation (diff / + failing tests / + method-class context).
- Correct-patch retention as a headline metric under class imbalance.
