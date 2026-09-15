# 10-Patch Smoke Test Sample Selection (Step 14)

Selected by structural criteria only (project, label, diff size, duplicate-group membership) from the
`included_primary` manifest rows -- never by outcome. One patch per (project x label) cell, smallest diff by
default, with one deliberate swap for size diversity (Chart's overfitting slot) since the corpus median diff
is only 2 lines.

| # | Project | Bug | Label | Diff lines | Duplicate group | Patch ID |
|---|---|---|---|---|---|---|
| 1 | Chart | Chart-12 | correct | 1 | - | Patches_ICSE__Ddifferent__Arja__Chart__patch1-Chart-12-Arja |
| 2 | Chart | Chart-15 | overfitting | 379 | - | Patches_ICSE__Doverfitting__AVATAR__Chart__patch1-Chart-15-AVATAR-plausible |
| 3 | Closure | Closure-115 | correct | 1 | - | Patches_ICSE__Ddifferent__Arja__Closure__patch1-Closure-115-Arja |
| 4 | Closure | Closure-117 | overfitting | 1 | - | Patches_ICSE__Doverfitting__Arja__Closure__patch1-Closure-117-Arja-plausible |
| 5 | Lang | Lang-43 | correct | 1 | - | Patches_ICSE__Dsame__SimFix__Lang__patch1-Lang-43-SimFix |
| 6 | Lang | Lang-58 | overfitting | 1 | - | Patches_ICSE__Doverfitting__AVATAR__Lang__patch1-Lang-58-AVATAR-plausible |
| 7 | Math | Math-53 | correct | 1 | - | Patches_others__Dcorrect__CapGen__Math__patch1-Math-53-CapGen |
| 8 | Math | Math-28 | overfitting | 1 | DUP0050 | Patches_ICSE__Doverfitting__Arja__Math__patch1-Math-28-Arja-plausible |
| 9 | Time | Time-15 | correct | 2 | - | Patches_ICSE__Dsame__ACS__Time__patch1-Time-15-ACS |
| 10 | Time | Time-11 | overfitting | 2 | - | Patches_ICSE__Doverfitting__FixMiner__Time__patch1-Time-11-FixMiner-plausible |

Covers all 5 projects (Chart, Closure, Lang, Math, Time), both labels (5 correct / 5 overfitting), diff size
range 1-379 lines, one duplicate-group member (Math-28), and Closure (the "complex project" requirement).

Not included here: Chart-19 (patch1-Chart-19-ACS), which was used earlier during pipeline *development* to
find and fix three real bugs (`reports/D4J_DRIVER_NOTES.md`, `reports/ORACLE_RUNNER_NOTES.md`). This smoke
test runs the 10 patches above through the pipeline in its current, fixed state, from a clean start.

This is an engineering smoke test (protocol.yaml `staging.stage1`) -- it validates that the pipeline runs
end-to-end and surfaces further bugs. It is not a scientific result and reports no accuracy claims.
