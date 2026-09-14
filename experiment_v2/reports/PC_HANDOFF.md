# Handoff to the Lab PC (authoritative experiment machine)

Everything below gate 5 was built on the macOS development machine. Gates 3 and 6–19 need the lab PC.
Run Claude Code **on the PC** in this repository and continue from §4.

## 1. Move the repository to the PC
On the Mac (already prepared): `APSEC2026_v2.bundle` in the repository root's parent folder.
On the PC (Ubuntu or WSL2 Ubuntu):
```bash
git clone APSEC2026_v2.bundle APSEC2026
cd APSEC2026 && git log --oneline | head -3      # must show the latest v2 commit
```
Copy the API key separately (never through git): create `experiment_v2/.env` with one line `ANTHROPIC_API_KEY=...`
(use a newly issued key).

## 2. Build the environment
```bash
# Docker Engine on Ubuntu (or Docker Desktop with the WSL2 backend)
cd APSEC2026/experiment_v2
docker build -t qc-v2 -f docker/Dockerfile .
sudo mkdir -p /data/qc_workspaces && sudo chown "$USER" /data/qc_workspaces
docker run --rm -it -v "$PWD":/work -v /data/qc_workspaces:/data/qc_workspaces qc-v2 bash
```
Inside the container:
```bash
python src/record_environment.py --authoritative     # GATE 3 -> results/environment.json / .txt
python src/dataset.py --download && python src/dataset.py && pytest -q tests/   # GATE 4/5 re-check on the PC
```

## 3. Gate status
| Gate | Status |
|---|---|
| 1 Repository inspection | PASS (`reports/IMPLEMENTATION_ASSESSMENT.md`) |
| 2 v1 preserved | PASS (tag `rebuild-v1-snapshot`, `experiment/` untouched) |
| 3 Environment recorded | PENDING — PC |
| 4 Dataset reproduced from source | PASS on Mac (archive MD5 verified; re-run on PC) |
| 5 Leakage guard | PARTIAL — guard + 12 tests pass; wiring into request builders pending |
| 6 Buggy/fixed Defects4J environments | PENDING — PC |
| 7 Source-context extraction | PENDING |
| 8 Semantic evaluator structured output | PENDING (v1 schema worked; v2 prompt not written) |
| 9–11 Counterexamples compile / reveal bug / candidate execution | PENDING — PC |
| 12–14 CFG / PDG / warning comparison | PENDING — PC |
| 15 Component scores reproducible | PENDING |
| 16 10-patch end-to-end | PENDING — PC |
| 17 No manuscript numbers in results | PASS so far (no generated result contains draft values) |
| 18 Protocol frozen | PENDING (draft in `protocol/`) |
| 19 50-patch pilot | PENDING — PC |

## 4. Remaining implementation order (from the directive, steps 7–37)
7. `src/d4j.py`: checkout buggy → `workspaces/buggy/<P>_<N>`, fixed → `workspaces/fixed_oracle/<P>_<N>` (then read-only),
   export `dir.src.classes`, `dir.bin.classes`, `cp.compile`, `cp.test`, `tests.trigger`; compile; run trigger tests;
   write `results/d4j_status.csv`; try both Defects4J versions on a sample of every project, freeze one.
8. Patch application: map diff paths (`/source/...`, `/src/main/java/...`, `/src/java/...`) onto `dir.src.classes`;
   `patch --dry-run -p?` without fuzz; candidate workspace = copy of buggy + patch; compile; run original trigger
   tests → fill `patch_applies`, `patch_compiles`, `original_tests_pass` in the manifest.
9. `tools/java` Maven module (JDK 21): JavaParser context extractor (changed methods, signatures, class declaration,
   referenced fields, imports, direct helpers) → `results/source_context_manifest.csv`.
10. Wire `leakage_guard.check_request` into every request builder; fixed-oracle fingerprint from `d4j.py` only;
    canary test in a real checkout.
11–12. `prompts/semantic_v2.txt` (schema from directive §P), context conditions A/B/C, `src/semantic.py`, S_sem.
13–15. `prompts/counterexample_v2.txt`, `src/counterexamples.py` (generate K=3), `src/oracle_runner.py`
       (compile, fixed ×3, buggy ×3, candidate ×3, statuses), S_cex.
16–17. SootUp CFG features; PDG via `sootup.codepropertygraph` or own implementation → `cfg_features.csv`, `pdg_features.csv`.
18–19. SpotBugs + FindSecBugs buggy vs candidate → `vulnerability_findings.csv`, S_vuln.
20. GumTree S_edit → `edit_scores.csv`.
21. Port v1 diff features as M2 (label "Diff-feature baseline").
22. `src/pvs.py` → `patch_scores.csv` (all components + flags).
23–24. `preference_tool/` + sampling plan + Bradley–Terry (weights per LOPO fold, training projects only).
25–30. Evaluation (LOPO, GroupKFold, cluster bootstrap, metrics, ranking, ablations, overlap matrices), latency/cost.
31. Complete tests (directive §BC).
32–33. 10-patch smoke test → `reports/SMOKE_TEST_V2.md`.
34. Freeze protocol (fill every TO_FREEZE; author decides the missing-S_cex strategy) → tag `protocol-v2-frozen`.
35–37. 50-patch pilot → `reports/PRE_FLIGHT_REPORT_V2.md` → STOP.

## 5. Decisions for the authors before the freeze
- Missing-S_cex strategy (directive formula vs shifted renormalization; see `protocol/protocol.yaml`).
- S_vuln severity weights.
- Context cap for condition C.
- Confirm the LLM selection rule (does not use label agreement).
