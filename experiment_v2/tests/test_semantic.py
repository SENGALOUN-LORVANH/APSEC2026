import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import semantic  # noqa: E402
import workspaces  # noqa: E402


def test_read_failure_messages_caps_per_message_and_total(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_WORKSPACES", str(tmp_path))
    bug_dir = workspaces.buggy_dir("Chart-19")
    bug_dir.mkdir(parents=True)
    body = "x" * 10
    (bug_dir / "failing_tests").write_text(f"--- A\n{body}\n--- B\n{body}\n--- C\n{body}\n")

    out = semantic.read_failure_messages("Chart-19", per_message_chars=5, total_chars=12)
    assert "A" in out
    assert "C" not in out  # never reached: total_chars exhausted after A + (truncated) B


def test_read_failure_messages_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_WORKSPACES", str(tmp_path))
    assert semantic.read_failure_messages("Chart-19") == ""
