# PC Environment Validation (Gate 3)

**Date:** 2026-09-15
**Host:** WSL2 Ubuntu 26.04 LTS on Windows 11 (DESKTOP-8JTDF4D), i9-10850K (10c/20t), 32GB RAM (15.6GB to WSL2), RTX 3080 10GB, 951GB free disk.
**Image:** `qc-v2` built from `docker/Dockerfile` (`FROM ubuntu:22.04`), image ID `8f92552b2574`, 10GB disk / 4.16GB content.

## Build issues found and fixed

1. **`pandas>=3.0` unresolvable on Python 3.10.** `requirements.txt` pinned floors (`pandas>=3.0`, `numpy>=2.5`, `scikit-learn>=1.9`, `scipy>=1.18`) that don't exist for Python 3.10 (pandas 3.0+ requires Python >=3.11; Ubuntu 22.04's default `python3` is 3.10). The codebase's actual pandas usage (`src/metrics.py`) is limited to `DataFrame`, `groupby`, `unique` — no 3.0-only APIs — so the fix was to relax the floors to versions that resolve cleanly on Python 3.10 (`pandas>=2.0`, `numpy>=1.26`, `scikit-learn>=1.3`, `scipy>=1.11`), verified in an isolated container: resolved to pandas 2.3.3, numpy 2.2.6, scikit-learn 1.7.2, scipy 1.15.3, anthropic 1.5.0, pyyaml 6.0.3, pytest 9.1.1.
2. **`docker build`'s exit code was unreliable** in this environment — it reported `0` even when a `RUN` layer failed and no image was tagged. Verification must check `docker images qc-v2` and grep the build log for `ERROR`/`non-zero code`, not trust the process exit status alone.
3. **Old pip (22.0.2) on Ubuntu 22.04** can't resolve modern wheel tags even where a compatible version exists. Added `pip install --upgrade pip setuptools wheel` before installing `requirements.txt`.
4. **Git "dubious ownership" inside the container.** The mounted repo is owned by the host UID (1000) but the container runs as root, so `git` refused to read it. Added `git config --global --add safe.directory /work` to the Dockerfile.
5. **`PC_HANDOFF.md`'s documented mount (`-v "$PWD":/work` from inside `experiment_v2/`) cuts off the parent `.git` directory**, so `git_commit`/`git_dirty` can never resolve from inside the container with that exact command. Mount the **repository root** instead: `docker run --rm -v ~/APSEC2026:/work -v ~/qc_workspaces:/data/qc_workspaces qc-v2 bash`, then `cd /work/experiment_v2` inside.
6. **`/data/qc_workspaces` requires `sudo`**, which needs an interactive password unavailable to an automated session. Used `~/qc_workspaces` (user-owned, no root needed) instead; functionally equivalent.

## Verified inside the container

| Component | Result |
|---|---|
| JDK 8 | `1.8.0_502` (openjdk 8u502) |
| JDK 11 | `11.0.32` |
| JDK 21 (default `java`) | `21.0.12` |
| Maven | `3.6.3` |
| Defects4J v2.0.1 (`a83e479`, JDK 8) | `defects4j -h` runs |
| Defects4J v3.0.1 (`6d54320`, JDK 11) | `defects4j -h` runs |
| SpotBugs | `4.9.3` |
| FindSecBugs plugin | `findsecbugs-plugin-1.14.0.jar` present in `/opt/spotbugs/plugin/` |
| git (repo root mount) | resolves `git_commit` / `git_dirty` correctly |
| Python | `3.10.12` |
| Python deps | `pandas`, `numpy`, `sklearn`, `scipy`, `anthropic`, `yaml`, `pytest` all import cleanly |
| `src/record_environment.py --authoritative` | writes `results/environment.{json,txt}` correctly, `in_docker: True` |

**Not yet installed in the image (by design, not a defect):** SootUp, GumTree, WALA — these are pinned in `tools.lock` for later per-module Maven resolution (Gate 9+), not baked into the base image.

## Gate 3 status: PASS
