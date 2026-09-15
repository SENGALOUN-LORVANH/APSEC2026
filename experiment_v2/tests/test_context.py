import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import context  # noqa: E402


def test_changed_ranges_by_file_single_hunk():
    diff = "--- /source/org/jfree/chart/plot/CategoryPlot.java\n" \
           "+++ /source/org/jfree/chart/plot/CategoryPlot.java\n" \
           "@@ -695,7 +695,7 @@\n context\n-old\n+new\n"
    ranges = context.changed_ranges_by_file(diff)
    assert ranges == {"org/jfree/chart/plot/CategoryPlot.java": [(695, 701)]}


def test_changed_ranges_by_file_default_length_one():
    diff = "--- /source/a/A.java\n+++ /source/a/A.java\n@@ -10 +10 @@\n-x\n+y\n"
    ranges = context.changed_ranges_by_file(diff)
    assert ranges == {"a/A.java": [(10, 10)]}


def test_changed_ranges_by_file_multiple_hunks_same_file():
    diff = "--- /source/a/A.java\n+++ /source/a/A.java\n" \
           "@@ -10,3 +10,3 @@\n-x\n+y\n c\n" \
           "@@ -50,5 +50,5 @@\n-x\n+y\n c\n"
    ranges = context.changed_ranges_by_file(diff)
    assert ranges == {"a/A.java": [(10, 12), (50, 54)]}


def test_changed_ranges_by_file_unknown_prefix_recorded_as_none():
    diff = "--- /weird/A.java\n+++ /weird/A.java\n@@ -1,1 +1,1 @@\n-x\n+y\n"
    ranges = context.changed_ranges_by_file(diff)
    assert ranges == {None: [(1, 1)]}
