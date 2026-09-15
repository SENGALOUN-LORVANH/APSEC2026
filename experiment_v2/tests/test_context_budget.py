import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from context_budget import ContextItem, fit_to_budget  # noqa: E402


def item(kind, n_chars, label=""):
    return ContextItem(kind, "x" * n_chars, None, label)


def test_under_budget_keeps_everything():
    r = fit_to_budget([item("changed_method", 300), item("imports_types", 300)], budget_tokens=1000)
    assert not r.removed and not r.over_budget and r.log()["truncated"] is False


def test_drops_lowest_priority_first_and_logs():
    items = [item("changed_method", 3000, "m"), item("helper_methods", 3000, "h"),
             item("imports_types", 3000, "i"), item("surrounding_source", 3000, "s")]
    r = fit_to_budget(items, budget_tokens=2100)
    assert [f"{i.kind}:{i.label}" for i in r.removed] == ["surrounding_source:s", "imports_types:i"]
    assert [i.kind for i in r.kept] == ["changed_method", "helper_methods"]
    log = r.log()
    assert log["original_token_estimate"] > log["final_token_estimate"] and log["truncation_reason"]


def test_mandatory_items_never_dropped_even_over_budget():
    r = fit_to_budget([item("changed_method", 90_000), item("referenced_fields", 30)], budget_tokens=12_000)
    assert [i.kind for i in r.kept] == ["changed_method"] and r.over_budget
    assert "mandatory" in r.truncation_reason
