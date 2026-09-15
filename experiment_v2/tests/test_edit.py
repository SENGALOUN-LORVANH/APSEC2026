import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import edit  # noqa: E402


def test_is_executable_line_filters_blank_and_comments():
    assert not edit.is_executable_line("")
    assert not edit.is_executable_line("   ")
    assert not edit.is_executable_line("// comment")
    assert not edit.is_executable_line("* javadoc continuation")
    assert not edit.is_executable_line("/* block start")
    assert edit.is_executable_line("return 1;")


def test_method_exec_loc_counts_only_code_lines():
    src = "/**\n * javadoc\n */\npublic int f() {\n    return 1;\n}\n"
    assert edit.method_exec_loc(src) == 3  # public int f() {, return 1;, }


def test_changed_exec_loc_counts_plus_minus_excluding_headers():
    diff = "--- a/F.java\n+++ a/F.java\n@@ -1,2 +1,2 @@\n-old();\n+new();\n context\n"
    assert edit.changed_exec_loc(diff) == 2


def test_changed_exec_loc_skips_comment_only_changes():
    diff = "--- a/F.java\n+++ a/F.java\n@@ -1 +1 @@\n-// old comment\n+// new comment\n"
    assert edit.changed_exec_loc(diff) == 0
