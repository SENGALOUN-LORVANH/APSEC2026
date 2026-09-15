import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import vuln  # noqa: E402


def test_parse_warnings_basic_line():
    out = "H B HE: org.jfree.chart.util.Size2D defines equals and uses Object.hashCode()  At Size2D.java:[line 83]"
    ws = vuln.parse_warnings(out)
    assert len(ws) == 1
    w = ws[0]
    assert w["priority"] == "H"
    assert w["severity"] == "HIGH"
    assert w["bug_type"] == "HE"
    assert w["class"] == "Size2D"


def test_parse_warnings_extracts_method():
    out = ("M V EI: org.jfree.chart.event.PlotChangeEvent.getPlot() may expose internal representation "
           "by returning PlotChangeEvent.plot  At PlotChangeEvent.java:[line 74]")
    w = vuln.parse_warnings(out)[0]
    assert w["method"] == "getPlot"
    assert w["severity"] == "MEDIUM"


def test_parse_warnings_skips_findsecbugs_internal_noise():
    out = ("M B CT: Exception thrown in class com.h3xstream.findsecbugs.taintanalysis.data.TaintLocation "
           "at new com.h3xstream.findsecbugs.taintanalysis.data.TaintLocation(MethodDescriptor, int) "
           "will leave the constructor.  At TaintLocation.java:[line 42]")
    assert vuln.parse_warnings(out) == []


def test_parse_warnings_ignores_non_matching_lines():
    assert vuln.parse_warnings("some unrelated log line\nanother one") == []


def test_warning_key_uses_type_class_method():
    w = {"bug_type": "HE", "class": "Size2D", "method": "equals"}
    assert vuln.warning_key(w) == ("HE", "Size2D", "equals")
