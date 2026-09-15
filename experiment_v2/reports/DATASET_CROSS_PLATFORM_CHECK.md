# Dataset Cross-Platform Check (Gate 4/5)

**Date:** 2026-09-15
**Environment:** inside `qc-v2` container (Ubuntu 22.04, Python 3.10.12), repo root mounted at `/work`.

## Procedure
```
python src/dataset.py --download   # Zenodo record 3730599, Patches.zip, MD5 verified
python src/dataset.py
pytest -q tests/
```

## Result: byte-identical to the Mac-committed outputs

`git status` after the re-run shows **no changes** to any generated data file:
- `data/dataset_manifest.csv`
- `data/normalized_patches/*.diff` (908 files)
- `results/exclusions.csv`, `results/corrected_labels.csv`, `results/duplicates.csv`
- `results/normalization_audit.csv`, `results/dataset_stats.json`, `results/policy_identifier_matches.csv`

Only `data/DATASET_PROVENANCE.md` differs, and only in its generation timestamp line
(`2026-09-14T15:18:50` on Mac vs. `2026-09-15T02:33:28` on PC) — expected, not a discrepancy.

Archive MD5 verified against the published Zenodo checksum (`11203b88e6ae8a657757c6b5842d5a46`) before parsing,
same as the Mac run. `dataset_stats.json` confirms: 908 archive files parsed, 899 primary patches
(245 correct / 654 overfitting, overfitting rate 0.7275), 202 bugs — matching the Mac's numbers exactly.

## Tests: 90/90 passed on the PC (container)

Covers `test_dataset.py`, `test_leakage_guard.py`, `test_scores_pvs.py`, `test_metrics.py`,
`test_context_budget.py`, `test_bradley_terry.py`, `test_request_builders.py` — same count as the
Mac's last commit ("90 tests"). No skips, no xfails.

`logs/errors.jsonl` (new, 13 lines) contains only `LEAKAGE_ABORT` canary records from the leakage-guard
test suite intentionally exercising the guard's abort paths (label/tool-identifier/archive-folder-token
leakage) — expected test behavior, not a pipeline failure. Recorded per the "never silently drop a
failure" rule rather than discarded.

## Gate 4/5 status: PASS
