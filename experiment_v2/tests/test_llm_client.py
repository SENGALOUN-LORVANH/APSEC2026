import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import llm_client  # noqa: E402


def test_response_text_finds_text_block_at_index_zero():
    resp = SimpleNamespace(content=[SimpleNamespace(text='{"a": 1}')])
    assert llm_client.response_text(resp) == '{"a": 1}'


def test_response_text_skips_leading_thinking_block():
    # claude-sonnet-5 with effort set prepends a ThinkingBlock with no .text attribute before the real text
    thinking = SimpleNamespace()  # no .text attribute, like anthropic's ThinkingBlock
    resp = SimpleNamespace(content=[thinking, SimpleNamespace(text='{"a": 1}')])
    assert llm_client.response_text(resp) == '{"a": 1}'


def test_response_text_raises_if_no_text_block_found():
    resp = SimpleNamespace(content=[SimpleNamespace()])
    with pytest.raises(ValueError):
        llm_client.response_text(resp)
