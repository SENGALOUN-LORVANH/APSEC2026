import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import d4j  # noqa: E402


def test_strip_src_prefix_known_roots():
    assert d4j._strip_src_prefix("/source/org/jfree/chart/plot/CategoryPlot.java") == \
        "org/jfree/chart/plot/CategoryPlot.java"
    assert d4j._strip_src_prefix("/src/main/java/org/apache/commons/lang3/StringUtils.java") == \
        "org/apache/commons/lang3/StringUtils.java"
    assert d4j._strip_src_prefix("/src/java/org/apache/commons/lang/StringUtils.java") == \
        "org/apache/commons/lang/StringUtils.java"


def test_strip_src_prefix_unknown_root_returns_none():
    assert d4j._strip_src_prefix("/somewhere/else/File.java") is None


def test_rewrite_diff_for_target_rewrites_both_headers():
    diff = "--- /source/org/jfree/chart/plot/CategoryPlot.java\n" \
           "+++ /source/org/jfree/chart/plot/CategoryPlot.java\n" \
           "@@ -1,1 +1,1 @@\n-old\n+new\n"
    rewritten, ok = d4j.rewrite_diff_for_target(diff, "source")
    assert ok
    assert "--- source/org/jfree/chart/plot/CategoryPlot.java\n" in rewritten
    assert "+++ source/org/jfree/chart/plot/CategoryPlot.java\n" in rewritten
    assert "@@ -1,1 +1,1 @@\n-old\n+new\n" in rewritten
    assert not rewritten.startswith("--- /")


def test_touched_relpaths_reads_plus_plus_plus_side():
    diff = "--- /source/a/Old.java\n+++ /source/a/New.java\n@@ -1 +1 @@\n-a\n+b\n"
    assert d4j._touched_relpaths(diff) == {"a/New.java"}


def test_rewrite_diff_for_target_unknown_prefix_fails_closed():
    diff = "--- /weird/Path.java\n+++ /weird/Path.java\n@@ -1 +1 @@\n-a\n+b\n"
    _, ok = d4j.rewrite_diff_for_target(diff, Path("/work/x/source"))
    assert not ok
