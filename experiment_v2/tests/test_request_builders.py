"""Integration tests: every LLM request builder invokes the leakage guard; fixed-oracle content and paths never
reach a request; the client refuses unguarded requests; only llm_client.py calls the API."""
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import leakage_guard  # noqa: E402
import llm_client  # noqa: E402
import request_builders as rb  # noqa: E402
import workspaces  # noqa: E402
from context_budget import ContextItem  # noqa: E402

META = {"patch_id": "Patches_ICSE__Doverfitting__Kali__Math__patch1-Math-80-Kali-plausible", "APR_tool": "Kali",
        "original_dataset_location": "Patches.zip:Patches/Patches_ICSE/Doverfitting/Kali/Math/x.patch"}
TOOLS = ["Kali", "jKali", "Arja", "TBar", "SimFix", "ACS"]
DIFF = ("--- /src/main/java/org/apache/commons/math/Foo.java\n+++ /src/main/java/org/apache/commons/math/Foo.java\n"
        "@@ -10,3 +10,3 @@\n-    if (x > 0) {\n+    if (x >= 0) {\n")
METHOD = "public int f(int x) {\n    if (x > 0) {\n        return 1;\n    }\n    return 0;\n}"


def semantic_kwargs(**over):
    kw = dict(patch_meta=META, condition="C", candidate_diff=DIFF, failing_tests="org.FooTest::testZero",
              failure_messages="expected:<1> but was:<0>", known_tools=TOOLS,
              context_items=[ContextItem("changed_method", METHOD, None, "f")])
    kw.update(over)
    return kw


def cex_kwargs(**over):
    kw = dict(patch_meta=META, candidate_diff=DIFF, failing_tests="org.FooTest::testZero",
              failure_messages="expected:<1> but was:<0>",
              context_items=[ContextItem("changed_method", METHOD, None, "f")],
              test_package="org.apache.commons.math", junit_style="JUnit 4 (org.junit.Test annotations)",
              known_tools=TOOLS)
    kw.update(over)
    return kw


KWARGS = {"semantic": semantic_kwargs, "counterexample": cex_kwargs}


@pytest.fixture(autouse=True)
def isolated_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_WORKSPACES", str(tmp_path / "ws"))
    monkeypatch.setattr(leakage_guard, "ERRORS", tmp_path / "errors.jsonl")


def test_every_registered_builder_invokes_guard(monkeypatch):
    calls = []
    real = leakage_guard.check_request

    def spy(*a, **k):
        calls.append(k.get("purpose"))
        return real(*a, **{**k, "errors_path": Path("/dev/null")})

    monkeypatch.setattr(leakage_guard, "check_request", spy)
    for name, builder in rb.BUILDERS.items():
        before = len(calls)
        req = builder(**KWARGS[name]())
        assert len(calls) == before + 1, f"{name} builder did not call the guard"
        llm_client.verify_receipt(req)


def test_all_builders_are_registered():
    public = {n for n in dir(rb) if n.startswith("build_") and n.endswith("_request")}
    assert public == {f"build_{k}_request" for k in rb.BUILDERS}


def test_only_llm_client_calls_the_api():
    offenders = [p.name for p in SRC.glob("*.py")
                 if re.search(r"messages\.(create|stream|parse)\(", p.read_text()) and p.name != "llm_client.py"]
    assert offenders == []


@pytest.mark.parametrize("name", list(rb.BUILDERS))
@pytest.mark.parametrize("leak", ["see archive folder Doverfitting", "patch1-Math-80-Kali-plausible",
                                  "ground_truth_label: overfitting", "repaired by SimFix",
                                  "/data/qc_workspaces/fixed_oracle/Math_80/src/Foo.java"])
def test_leaky_content_aborts(name, leak):
    kw = KWARGS[name](failure_messages="expected:<1> but was:<0>\n" + leak)
    with pytest.raises(leakage_guard.LeakageError):
        rb.BUILDERS[name](**kw)


@pytest.mark.parametrize("name", list(rb.BUILDERS))
def test_fixed_oracle_source_path_is_rejected(name):
    fo = workspaces.fixed_oracle_root() / "Math_80" / "src" / "Foo.java"
    fo.parent.mkdir(parents=True)
    fo.write_text(METHOD)
    kw = KWARGS[name](context_items=[ContextItem("changed_method", METHOD, str(fo), "f")])
    with pytest.raises(workspaces.FixedOracleAccessError):
        rb.BUILDERS[name](**kw)


def test_read_for_prompt_rejects_symlink_into_fixed_oracle(tmp_path):
    fo = workspaces.fixed_oracle_root() / "Math_80" / "Foo.java"
    fo.parent.mkdir(parents=True)
    fo.write_text("secret")
    link = tmp_path / "innocent.java"
    link.symlink_to(fo)
    with pytest.raises(workspaces.FixedOracleAccessError):
        workspaces.read_for_prompt(link)


def test_non_oracle_module_cannot_locate_fixed_oracle(monkeypatch):
    # Simulate a call from a module that is not on the oracle allowlist.
    monkeypatch.setattr(workspaces, "ORACLE_MODULES", set())
    with pytest.raises(workspaces.FixedOracleAccessError):
        workspaces.fixed_oracle_dir("Math-80")


@pytest.mark.parametrize("name", list(rb.BUILDERS))
def test_fixed_version_canary_line_aborts(name):
    buggy = "class Foo {\n  int f(int x) {\n    return x + 1;\n  }\n}\n"
    fixed = "class Foo {\n  int f(int x) {\n    return canaryFixedOnlyCall_9d2e(x);\n  }\n}\n"
    fp = leakage_guard.developer_fix_fingerprint(buggy, fixed, DIFF)
    kw = KWARGS[name](context_items=[ContextItem("changed_method", "    return canaryFixedOnlyCall_9d2e(x);", None)],
                      fingerprint_hashes=fp)
    with pytest.raises(leakage_guard.LeakageError):
        rb.BUILDERS[name](**kw)


def test_ordinary_words_are_not_rejected():
    msg = ("junit.framework.AssertionFailedError: result is not correct; expected CORRECT_ROUNDING, "
           "incorrect overflow handling")
    ctx = [ContextItem("changed_method", "/** Returns the correct value; OVERFITTING is not a word here. */\n" + METHOD)]
    req = rb.build_semantic_request(**semantic_kwargs(failure_messages=msg, context_items=ctx))
    assert "CORRECT_ROUNDING" in req.user


def test_tool_name_occurring_in_buggy_source_is_allowed():
    ctx = [ContextItem("changed_method", "int ACS = 3; // constant in project code\n" + METHOD)]
    kw = semantic_kwargs(context_items=ctx, allowed_source_text="int ACS = 3;")
    rb.build_semantic_request(**kw)
    with pytest.raises(leakage_guard.LeakageError):
        rb.build_semantic_request(**semantic_kwargs(context_items=ctx))


def test_client_refuses_tampered_request():
    req = rb.build_semantic_request(**semantic_kwargs())
    tampered = replace(req, user=req.user + "\nOriginal label: overfitting", dynamic_text=req.dynamic_text + "x")
    with pytest.raises(llm_client.UnguardedRequestError):
        llm_client.verify_receipt(tampered)


def test_conditions_select_prompt_sections():
    a = rb.build_semantic_request(**semantic_kwargs(condition="A"))
    b = rb.build_semantic_request(**semantic_kwargs(condition="B"))
    c = rb.build_semantic_request(**semantic_kwargs(condition="C"))
    assert "Failing test" not in a.user and "source context" not in a.user
    assert "Failing test" in b.user and "Unpatched source context" not in b.user
    assert "Unpatched source context" in c.user and METHOD.splitlines()[0] in c.user
    assert a.prompt_sha256 == b.prompt_sha256 == c.prompt_sha256
    assert len({a.context_sha256, b.context_sha256, c.context_sha256}) == 3


def test_semantic_prompt_contains_approved_wording():
    p = rb.load_prompt(rb.SEMANTIC_PROMPT)
    assert ("The candidate patch has been classified as plausible because it passes the available test suite. "
            "Passing the available tests does not necessarily establish semantic correctness.") in p.system
    assert "Defects4J" not in p.system
