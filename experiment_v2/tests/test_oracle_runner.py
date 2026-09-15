import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import oracle_runner  # noqa: E402


def test_extract_class_name_public_class():
    src = "package p;\nimport x;\n\npublic class FooTest extends TestCase {\n}\n"
    assert oracle_runner.extract_class_name(src) == "FooTest"


def test_extract_class_name_no_class_returns_none():
    assert oracle_runner.extract_class_name("not java at all") is None


def test_junit3_regex_detects_testcase_extension():
    assert oracle_runner.JUNIT3_RE.search("public class T extends TestCase {")
    assert oracle_runner.JUNIT3_RE.search("public class T extends junit.framework.TestCase {")
    assert not oracle_runner.JUNIT3_RE.search("public class T {\n  @Test public void t() {}\n}")
