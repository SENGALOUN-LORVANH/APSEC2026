# Defects4J Driver (`src/d4j.py`) — Steps 7-8

Implements bug-level checkout/compile/trigger-test (Step 7) and candidate-level patch application/compile/
trigger-test (Step 8), against Defects4J v2.0.1 per `protocol/protocol.yaml` (`no_per_bug_version_switching: true`).

## Validated end-to-end on Chart-19 / patch1-Chart-19-ACS (`ground_truth_label: correct`)

`defects4j checkout` (buggy + fixed_oracle) → `defects4j compile` → `defects4j export` (`dir.src.classes`,
`tests.trigger`) → `defects4j test` (buggy: 2/2 expected trigger failures; fixed: 0 failures) → candidate copy →
patch application → compile → trigger-test re-check: `patch_applies=True, patch_compiles=True,
original_tests_pass=True`. Real Defects4J execution, not simulated.

## Three real bugs found and fixed during validation (not hypothetical — each reproduced and confirmed fixed)

1. **GNU `patch` refuses absolute file paths** ("potentially dangerous file name"). Fix: rewrite diff headers to
   paths *relative* to the checkout root and run `patch` with `cwd=<checkout root>`, not absolute paths.
2. **CRLF/LF inconsistency** between the archive's diffs and the actual old jfreechart/commons sources (mixed
   within a single diff file). Reading with `newline=''` alone wasn't enough — the archive's hunk content is LF
   while the checked-out source is CRLF. Fix: normalize CRLF→LF on both the diff text and the specific touched
   file(s) in the candidate workspace before invoking `patch`. Line endings are not semantic content.
3. **Trailing whitespace on context lines does not match between archive diff and real checkout** — confirmed by
   direct byte comparison: the diff expects a blank context line to be empty, the actual checked-out file has that
   line padded with trailing spaces. Fix: `patch --ignore-whitespace`. This is **not** the same as `--fuzz`
   (context-radius tolerance, which stays at `--fuzz=0` per protocol's "no fuzz" rule) — `--ignore-whitespace`
   only normalizes incidental whitespace, not approximate context-line matching. Flagging this explicitly since
   it's adjacent to a protocol constraint, even though it's a distinct concept.

## Also fixed: container/host UID mismatch

Files written by `docker run` (as root) inside a host-mounted volume become unreadable/unwritable by the host
user's own venv (e.g. `logs/errors.jsonl`, `.pytest_cache/`), breaking subsequent host-side pytest runs with
`PermissionError`. Fixed existing files via one-off `chown` through the container; all container invocations
from here on use `--user $(id -u):$(id -g)` to prevent recurrence.

## Test coverage

`tests/test_d4j.py`: 5 unit tests for the pure-Python diff-rewriting logic (prefix stripping, header rewriting,
touched-file extraction), runnable without Defects4J installed (Mac-compatible). The checkout/compile/patch-apply
integration path can only be exercised on the PC (requires Defects4J + JDK 8), validated manually above; not yet
wrapped in an automated integration test since that would require a real Defects4J environment as a test fixture.

## Not yet done

- Only 1 bug / 1 patch processed so far (validation only). The 10-patch smoke-test sample (Step 14) and the
  ~50-patch pilot (Step 17) will exercise `d4j.py` at the scale the protocol actually calls for.
- `--sample N` CLI mode (bug-level only) is implemented but not yet run at scale.
