"""Workspace layout and fixed-oracle isolation.

  <QC_WORKSPACES>/buggy/<Project>_<N>/          defects4j checkout -v <N>b
  <QC_WORKSPACES>/candidate/<patch_id>/         copy of buggy + candidate patch
  <QC_WORKSPACES>/fixed_oracle/<Project>_<N>/   defects4j checkout -v <N>f  (oracle modules only)
  <QC_WORKSPACES>/gen_tests/<patch_id>/<test>/  generated tests

Only oracle-side code may call `fixed_oracle_dir`. Everything that feeds an LLM prompt, a feature, or a score must
read files through `read_for_prompt` / `assert_not_fixed_oracle`, which reject any path inside fixed_oracle/
(symlinks resolved).
"""
import inspect
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORACLE_MODULES = {"oracle_runner", "d4j", "test_workspaces", "test_request_builders"}


class FixedOracleAccessError(PermissionError):
    pass


def workspace_root() -> Path:
    return Path(os.environ.get("QC_WORKSPACES", ROOT / "workspaces")).resolve()


def bug_dirname(bug_id: str) -> str:
    project, number = bug_id.rsplit("-", 1)
    return f"{project}_{number}"


def buggy_dir(bug_id: str) -> Path:
    return workspace_root() / "buggy" / bug_dirname(bug_id)


def candidate_dir(patch_id: str) -> Path:
    return workspace_root() / "candidate" / patch_id


def gen_tests_dir(patch_id: str) -> Path:
    return workspace_root() / "gen_tests" / patch_id


def fixed_oracle_root() -> Path:
    return workspace_root() / "fixed_oracle"


def fixed_oracle_dir(bug_id: str) -> Path:
    caller = Path(inspect.stack()[1].filename).stem
    if caller not in ORACLE_MODULES:
        raise FixedOracleAccessError(f"module '{caller}' is not allowed to locate the fixed oracle")
    return fixed_oracle_root() / bug_dirname(bug_id)


def is_inside_fixed_oracle(path) -> bool:
    p = Path(path).resolve()
    fo = fixed_oracle_root().resolve()
    return p == fo or fo in p.parents


def assert_not_fixed_oracle(path):
    if is_inside_fixed_oracle(path):
        raise FixedOracleAccessError(f"refusing to use fixed-oracle path for LLM/feature input: {path}")
    return Path(path)


def read_for_prompt(path) -> str:
    assert_not_fixed_oracle(path)
    return Path(path).read_text(encoding="utf-8", errors="replace")
