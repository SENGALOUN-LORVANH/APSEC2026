"""Token-aware context assembly (condition C).

Items are dropped lowest-priority first until the estimate fits the budget. Mandatory items (changed method,
candidate diff) are never dropped; if they alone exceed the budget the context is marked over_budget and kept
whole (no blind truncation). Every decision is logged.

Priority (1 = highest): 1 changed method, 2 candidate diff, 3 method/class signatures, 4 failing tests + messages,
5 referenced fields, 6 direct helper methods, 7 imports/type declarations, 8 additional surrounding source.
"""
from dataclasses import dataclass, field

PRIORITY = {"changed_method": 1, "candidate_diff": 2, "signatures": 3, "failing_tests": 4, "referenced_fields": 5,
            "helper_methods": 6, "imports_types": 7, "surrounding_source": 8}
MANDATORY = {"changed_method", "candidate_diff"}
DEFAULT_BUDGET_TOKENS = 12_000
CHARS_PER_TOKEN = 3.0  # conservative for Java source; exact counts come from the API count_tokens endpoint when used


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


@dataclass
class ContextItem:
    kind: str
    text: str
    source_path: str | None = None
    label: str = ""

    def __post_init__(self):
        if self.kind not in PRIORITY:
            raise ValueError(f"unknown context kind {self.kind}")

    @property
    def tokens(self):
        return estimate_tokens(self.text)


@dataclass
class BudgetResult:
    kept: list
    removed: list = field(default_factory=list)
    original_tokens: int = 0
    final_tokens: int = 0
    over_budget: bool = False
    truncation_reason: str = ""

    def log(self):
        return {"original_token_estimate": self.original_tokens, "final_token_estimate": self.final_tokens,
                "items_removed": [f"{i.kind}:{i.label}" for i in self.removed], "over_budget": self.over_budget,
                "truncation_reason": self.truncation_reason, "truncated": bool(self.removed)}


def fit_to_budget(items, budget_tokens=DEFAULT_BUDGET_TOKENS, fixed_overhead_tokens=0):
    kept = list(items)
    original = sum(i.tokens for i in kept) + fixed_overhead_tokens
    total = original
    removed = []
    # Drop from lowest priority (largest number); within a priority level drop the largest item first.
    for item in sorted(kept, key=lambda i: (-PRIORITY[i.kind], -i.tokens)):
        if total <= budget_tokens:
            break
        if item.kind in MANDATORY:
            continue
        kept.remove(item)
        removed.append(item)
        total -= item.tokens
    over = total > budget_tokens
    reason = ""
    if removed:
        reason = f"estimate {original} > budget {budget_tokens}; dropped lowest-priority items"
    if over:
        reason = (reason + "; " if reason else "") + "mandatory items alone exceed budget (kept whole)"
    kept.sort(key=lambda i: PRIORITY[i.kind])
    return BudgetResult(kept, removed, original, total, over, reason)
