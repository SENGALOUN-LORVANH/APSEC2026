"""Step 1 credit check: ONE cheap guarded API call to confirm the key works.

Goes through the required path request_builders -> leakage_guard -> llm_client.send.
Never prints the API key. Exits 0 on success, 1 on any API/billing error.

Usage: python src/credit_check.py [patch_id] [model]
"""
import sys

import llm_client
import semantic


def main():
    patch_id = sys.argv[1] if len(sys.argv) > 1 else \
        "Patches_ICSE__Ddifferent__ACS__Chart__patch1-Chart-19-ACS"
    model = sys.argv[2] if len(sys.argv) > 2 else "claude-haiku-4-5"

    import anthropic
    client = anthropic.Anthropic()
    req, _ = semantic.build_request(patch_id, "C")  # guarded request + receipt
    resp, latency, attempts, _settings, err = llm_client.send(client, req, model, max_retries=2)

    if err is not None or resp is None:
        print(f"CREDIT_CHECK_FAILED model={model} attempts={attempts} error={err}")
        sys.exit(1)

    usage = getattr(resp, "usage", None)
    text = llm_client.response_text(resp)  # confirm the response parses through the fixed accessor
    print(f"CREDIT_OK model={model} patch={patch_id} "
          f"input_tokens={getattr(usage, 'input_tokens', None)} "
          f"output_tokens={getattr(usage, 'output_tokens', None)} "
          f"latency_s={round(latency, 2)} attempts={attempts} response_chars={len(text)}")


if __name__ == "__main__":
    main()
