"""The ONLY place LLM requests are built. Every builder:
  1. rejects context items whose source path lies inside fixed_oracle/,
  2. renders the prompt from an immutable prompt file,
  3. passes all dynamic (data-derived) content through leakage_guard.check_request,
  4. returns an LLMRequest carrying the guard receipt; llm_client.send refuses requests without a valid receipt.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

import leakage_guard
import workspaces
from context_budget import ContextItem, fit_to_budget

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
SEMANTIC_PROMPT = PROMPTS / "semantic_v2.txt"
COUNTEREXAMPLE_PROMPT = PROMPTS / "counterexample_v2.txt"
PROBE_PROMPT = PROMPTS / "probe_v2.txt"
CONDITIONS = ("A", "B", "C")


@dataclass(frozen=True)
class PromptFile:
    path: Path
    system: str
    template: str
    schema: dict
    sha256: str


@dataclass(frozen=True)
class LLMRequest:
    purpose: str
    patch_id: str
    system: str
    user: str
    schema: dict
    prompt_sha256: str
    context_sha256: str
    dynamic_text: str
    receipt: leakage_guard.GuardReceipt
    context_log: dict


def load_prompt(path) -> PromptFile:
    text = Path(path).read_text()
    system = text.split("===== SYSTEM PROMPT =====", 1)[1].split("===== USER MESSAGE TEMPLATE =====", 1)[0].strip()
    rest = text.split("===== USER MESSAGE TEMPLATE =====", 1)[1]
    template, schema = rest.split("===== OUTPUT SCHEMA =====", 1)
    body = f"{system}\n\x00\n{template.strip()}\n\x00\n{schema.strip()}"
    return PromptFile(Path(path), system, template.strip(), json.loads(schema), leakage_guard.sha256(body))


def _select_blocks(template, condition):
    keep = {"CONDITION_B_AND_C": condition in ("B", "C"), "CONDITION_C": condition == "C"}
    for name, on in keep.items():
        pattern = re.compile(rf"\[\[{name}\]\]\n?(.*?)\[\[/{name}\]\]\n?", re.S)
        template = pattern.sub(lambda m: m.group(1) if on else "", template)
    return template


def _check_paths(items):
    for it in items:
        if it.source_path:
            workspaces.assert_not_fixed_oracle(it.source_path)


def _format_context(items):
    return "\n\n".join(f"// {it.kind}{(': ' + it.label) if it.label else ''}\n{it.text}" for it in items)


def build_semantic_request(patch_meta, condition, candidate_diff, failing_tests="", failure_messages="",
                           context_items=(), known_tools=(), fingerprint_hashes=frozenset(),
                           allowed_source_text="", budget_tokens=12_000, prompt_path=SEMANTIC_PROMPT):
    if condition not in CONDITIONS:
        raise ValueError(f"unknown context condition {condition}")
    prompt = load_prompt(prompt_path)
    items = list(context_items) if condition == "C" else []
    _check_paths(items)
    budget = fit_to_budget(items, budget_tokens,
                           fixed_overhead_tokens=len(candidate_diff + failing_tests + failure_messages) // 3)
    source_context = _format_context(budget.kept)
    fields = {"candidate_diff": candidate_diff}
    if condition in ("B", "C"):
        fields.update(failing_tests=failing_tests or "(none available)",
                      failure_messages=failure_messages or "(none available)")
    if condition == "C":
        fields["source_context"] = source_context or "(source context unavailable)"
    user = _select_blocks(prompt.template, condition).format(**fields)
    dynamic = "\n".join(fields.values())
    receipt = leakage_guard.check_request(dynamic, patch_meta, known_tools, fingerprint_hashes,
                                          purpose=f"semantic:{condition}", allowed_source_text=allowed_source_text)
    return LLMRequest("semantic", patch_meta["patch_id"], prompt.system, user, prompt.schema, prompt.sha256,
                      leakage_guard.sha256(dynamic), dynamic, receipt, {"condition": condition, **budget.log()})


def build_counterexample_request(patch_meta, candidate_diff, failing_tests, failure_messages, context_items,
                                 test_package, junit_style, k=3, known_tools=(), fingerprint_hashes=frozenset(),
                                 allowed_source_text="", budget_tokens=12_000, prompt_path=COUNTEREXAMPLE_PROMPT):
    prompt = load_prompt(prompt_path)
    items = list(context_items)
    _check_paths(items)
    budget = fit_to_budget(items, budget_tokens,
                           fixed_overhead_tokens=len(candidate_diff + failing_tests + failure_messages) // 3)
    fields = {"failing_tests": failing_tests or "(none available)",
              "failure_messages": failure_messages or "(none available)",
              "source_context": _format_context(budget.kept) or "(source context unavailable)",
              "candidate_diff": candidate_diff}
    system = prompt.system.format(k=k, test_package=test_package, junit_style=junit_style)
    user = prompt.template.format(**fields)
    dynamic = "\n".join([*fields.values(), test_package, junit_style])
    receipt = leakage_guard.check_request(dynamic, patch_meta, known_tools, fingerprint_hashes,
                                          purpose="counterexample", allowed_source_text=allowed_source_text)
    return LLMRequest("counterexample", patch_meta["patch_id"], system, user, prompt.schema, prompt.sha256,
                      leakage_guard.sha256(dynamic), dynamic, receipt, {"k": k, **budget.log()})


def build_probe_request(patch_meta, candidate_diff, known_tools=(), fingerprint_hashes=frozenset(),
                        allowed_source_text="", prompt_path=PROBE_PROMPT):
    """Memorization probe (reports/PRE_FLIGHT diagnostic): the model sees only the diff, nothing else -- no
    context, no failing tests, no metadata -- and is asked to recall the bug from memory."""
    prompt = load_prompt(prompt_path)
    user = prompt.template.format(candidate_diff=candidate_diff)
    dynamic = candidate_diff
    receipt = leakage_guard.check_request(dynamic, patch_meta, known_tools, fingerprint_hashes,
                                          purpose="probe", allowed_source_text=allowed_source_text)
    return LLMRequest("probe", patch_meta["patch_id"], prompt.system, user, prompt.schema, prompt.sha256,
                      leakage_guard.sha256(dynamic), dynamic, receipt, {})


BUILDERS = {"semantic": build_semantic_request, "counterexample": build_counterexample_request,
            "probe": build_probe_request}
