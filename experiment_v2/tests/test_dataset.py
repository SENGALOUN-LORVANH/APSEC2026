import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dataset as ds  # noqa: E402


def rec(tool="Jaid", bug="Lang-51", idx=2, plausible=False, folder="Dcorrect", label="correct"):
    return {"patch_id": f"x__{tool}__{bug}__{idx}__{plausible}", "APR_tool": tool, "bug_id": bug, "patch_index": idx,
            "plausible_suffix": plausible, "archive_folder": folder, "original_label": label}


# ---------------------------------------------------------------- identifier matching
def test_full_filename_identifier_requires_exact_suffix():
    assert ds.identifier_matches("patch2-Lang-51-Jaid", rec(plausible=False))
    assert not ds.identifier_matches("patch2-Lang-51-Jaid", rec(plausible=True))
    assert ds.identifier_matches("patch1-Lang-6-SketchFix-plausible",
                                 rec(tool="SketchFix", bug="Lang-6", idx=1, plausible=True))
    assert not ds.identifier_matches("patch1-Lang-6-SketchFix-plausible",
                                     rec(tool="SketchFix", bug="Lang-6", idx=1, plausible=False))


def test_short_identifier_matches_any_index_but_exact_tool():
    assert ds.identifier_matches("SimFix-Math-72", rec(tool="SimFix", bug="Math-72", idx=3))
    assert not ds.identifier_matches("Kali-Lang-7", rec(tool="jKali", bug="Lang-7", idx=1))
    assert ds.parse_identifier("Kali-A-Mockito-10")["tool"] == "Kali-A"


# ---------------------------------------------------------------- policies
PRIMARY = {"policy": "primary", "corrections": {"corrected_label": "overfitting", "ids": ["Arja-Math-50"]},
           "exclude": {"borderline": ["TBar-Lang-7"], "unlabeled_folders": ["Error"]}}
SENS = {"policy": "sensitivity", "corrections": None,
        "exclude": {"mislabeled": ["Arja-Math-50"], "borderline": ["TBar-Lang-7"], "unlabeled_folders": ["Error"]}}


def test_primary_corrects_and_sensitivity_excludes():
    r = rec(tool="Arja", bug="Math-50", idx=1, folder="Ddifferent")
    log = defaultdict(list)
    assert ds.apply_policy(r, PRIMARY, log) == (True, "overfitting", "corrected:correct->overfitting", "")
    inc, lab, _, reason = ds.apply_policy(r, SENS, log)
    assert (inc, lab) == (False, None) and reason == "mislabeled:Arja-Math-50"


def test_borderline_and_unlabeled_excluded_in_both():
    for pol in (PRIMARY, SENS):
        assert ds.apply_policy(rec(tool="TBar", bug="Lang-7", idx=1, folder="Ddifferent"), pol,
                               defaultdict(list))[0] is False
        assert ds.apply_policy(rec(tool="kPAR", bug="Chart-12", idx=1, folder="Error", label=None), pol,
                               defaultdict(list))[3] == "unlabeled_folders:Error"


def test_correction_of_already_overfitting_patch_stops():
    r = rec(tool="Arja", bug="Math-50", idx=1, folder="Doverfitting", label="overfitting")
    with pytest.raises(SystemExit):
        ds.apply_policy(r, PRIMARY, defaultdict(list))


def test_unaffected_patch_keeps_label():
    assert ds.apply_policy(rec(), PRIMARY, defaultdict(list)) == (True, "correct", "none", "")


# ---------------------------------------------------------------- normalization
ORIG = ("--- /a/X.java\n+++ /a/X.java\n@@ -10,4 +10,4 @@\n"
        "-    int a = 1;   \n+    int a = 1;\n-    return a;\n+    return a + 1;\n     }\n \n")


def test_whitespace_only_lines_are_removed_and_verified():
    rebuilt = ds.normalize_trailing_whitespace(ORIG)
    assert rebuilt is not None
    assert ds.changed_line_count(rebuilt) == 2
    assert "+    return a + 1;" in rebuilt
    assert ds.verify_normalization(ORIG, rebuilt)


def test_no_whitespace_change_returns_none():
    diff = "--- /a/X.java\n+++ /a/X.java\n@@ -1,2 +1,2 @@\n-  x = 1;\n+  x = 2;\n   y();\n"
    assert ds.normalize_trailing_whitespace(diff) is None


def test_blank_trailing_line_does_not_count_as_change():
    # Regression: '' in '+-' is True in Python; empty lines must not be counted as changed lines.
    assert ds.changed_line_count("--- a\n+++ a\n@@ -1 +1 @@\n-x\n+y\n\n") == 2


def test_verification_detects_semantic_change():
    bad = ORIG.replace("+    return a;", "+    return a;").replace("+    return a + 1;", "+    return a + 2;")
    rebuilt = ds.normalize_trailing_whitespace(ORIG)
    assert not ds.verify_normalization(bad, rebuilt)
