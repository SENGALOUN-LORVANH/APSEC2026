"""The only module that calls the Anthropic API. Requests must come from request_builders and carry a guard receipt
whose hash matches the request's dynamic content."""
import json
import time
from dataclasses import asdict

import leakage_guard
from request_builders import LLMRequest

MODEL_SETTINGS = {
    "claude-haiku-4-5": {"extra_body": {"temperature": 0.0}},
    "claude-sonnet-5": {"output_config": {"effort": "medium"}},
}
MAX_TOKENS = 16000


class UnguardedRequestError(RuntimeError):
    pass


def verify_receipt(req: LLMRequest):
    r = req.receipt
    if not isinstance(req, LLMRequest) or not isinstance(r, leakage_guard.GuardReceipt):
        raise UnguardedRequestError("request was not produced by request_builders")
    if r.dynamic_sha256 != leakage_guard.sha256(req.dynamic_text) or r.patch_id != req.patch_id:
        raise UnguardedRequestError("guard receipt does not match request content")
    if req.dynamic_text not in req.user and not all(part in req.user or part in req.system
                                                     for part in req.dynamic_text.split("\n") if part):
        raise UnguardedRequestError("request user content diverges from guarded dynamic content")


def send(client, req: LLMRequest, model: str, max_retries=6):
    """Send one guarded request. Returns (response|None, latency_s, attempts, request_settings, error)."""
    verify_receipt(req)
    import anthropic  # local import keeps unit tests offline
    settings = json.loads(json.dumps(MODEL_SETTINGS[model]))
    output_config = {"format": {"type": "json_schema", "schema": req.schema}}
    output_config.update(settings.pop("output_config", {}))
    params = dict(model=model, max_tokens=MAX_TOKENS, system=req.system,
                  messages=[{"role": "user", "content": req.user}], output_config=output_config, **settings)
    attempts, err = 0, None
    while attempts < max_retries:
        attempts += 1
        t0 = time.perf_counter()
        try:
            resp = client.messages.create(**params)
            return resp, time.perf_counter() - t0, attempts, MODEL_SETTINGS[model], None
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            err = f"{type(e).__name__}: {e}"
        except anthropic.APIStatusError as e:
            if e.status_code < 500:
                return None, time.perf_counter() - t0, attempts, MODEL_SETTINGS[model], f"{type(e).__name__}: {e}"
            err = f"{type(e).__name__}: {e}"
        time.sleep(min(2 ** attempts, 60))
    return None, None, attempts, MODEL_SETTINGS[model], f"gave up after {attempts} attempts: {err}"


def response_text(resp):
    """The text content block, wherever it is. content[0] is not always it: models run with extended
    thinking (e.g. claude-sonnet-5 with effort set) prepend a ThinkingBlock with no .text attribute --
    confirmed directly during the pilot's model-comparison run."""
    for block in resp.content:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    raise ValueError(f"no text block in response content: {[type(b).__name__ for b in resp.content]}")


def request_log_fields(req: LLMRequest):
    d = asdict(req)
    d.pop("dynamic_text")
    d["receipt"] = asdict(req.receipt)
    return d
