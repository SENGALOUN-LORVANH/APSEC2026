"""Signal A: LLM semantic review (Stage 1, S_sem).

Every API call is appended to the log with the full raw response, latency, token usage, and the exact
request parameters. Results are cached by (model, prompt sha, patch_id, run) so re-running resumes.
Errors are logged, never dropped; a re-run retries them.

Pilot (allowed on a DRAFT prompt):
  python src/llm_review.py --model claude-haiku-4-5 --pilot 20
Full run (refused while the prompt filename contains _DRAFT):
  python src/llm_review.py --model <model> --prompt prompts/review_v1.txt --runs 3

The model is never shown the filename, path, APR tool name, or '-plausible' suffix (they leak the label).
"""
import argparse
import hashlib
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]

# Per-model request settings. Sampling parameters are rejected (400) on claude-sonnet-5, so temperature 0
# is only possible on models that still accept it. Whatever is sent is logged with every call.
# anthropic SDK 1.x removed `temperature` from messages.create(); models that still honour it (Haiku 4.5) take
# it via extra_body, which is merged into the request JSON as-is.
MODEL_SETTINGS = {
    "claude-haiku-4-5": {"extra_body": {"temperature": 0.0}},
    "claude-sonnet-5": {},  # no temperature (rejected); thinking left at the model default (adaptive)
}

SCHEMA = {
    "type": "object",
    "properties": {
        **{f"q{i}": {"type": "string"} for i in range(1, 7)},
        "judgement": {"type": "string", "enum": ["CORRECT", "OVERFITTING"]},
        "confidence": {"type": "number"},
    },
    "required": [f"q{i}" for i in range(1, 7)] + ["judgement", "confidence"],
    "additionalProperties": False,
}


def load_dotenv(path):
    """Minimal .env reader (KEY=VALUE lines) so the key never has to be typed into a command. .env is gitignored."""
    import os
    if not path.exists():
        return []
    names = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # utf-8-sig drops a leading BOM
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            names.append((key, bool(value)))
            if value and not os.environ.get(key):  # also replaces an empty variable inherited from the shell
                os.environ[key] = value
    return names


def load_prompt(path):
    text = path.read_text()
    system = text.split("===== SYSTEM PROMPT =====", 1)[1].split("===== USER MESSAGE TEMPLATE =====", 1)[0].strip()
    template = text.split("===== USER MESSAGE TEMPLATE =====", 1)[1].strip()
    sha = hashlib.sha256((system + "\n\x00\n" + template).encode()).hexdigest()[:16]
    return system, template, sha


def cap(text, limit):
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[... truncated {len(text) - limit} characters ...]", True


def build_user_message(template, rec, trig, msg_cap_each, msg_cap_total):
    info = trig.get(rec["bug_id"], {"tests": [], "messages": []})
    parts, truncated = [], False
    for m in info["messages"]:
        c, t = cap(m, msg_cap_each)
        parts.append(c)
        truncated |= t
    messages, t = cap("\n\n".join(parts), msg_cap_total)
    truncated |= t
    msg = template.format(failing_tests="\n".join(info["tests"]) or "(none available)",
                          failure_messages=messages or "(none available)",
                          diff=rec.get("diff_for_model", rec["diff"]))
    return msg, truncated


def pilot_sample(records, n, seed):
    """Equal numbers per label, round-robin over projects so every project is represented."""
    rng = random.Random(seed)
    picked = []
    for label in ("correct", "overfitting"):
        by_proj = {}
        for r in records:
            if r["label"] == label:
                by_proj.setdefault(r["project"], []).append(r)
        for lst in by_proj.values():
            rng.shuffle(lst)
        want, projects = n // 2 + (n % 2 if label == "overfitting" else 0), sorted(by_proj)
        i = 0
        while sum(p["label"] == label for p in picked) < want:
            lst = by_proj[projects[i % len(projects)]]
            if lst:
                picked.append(lst.pop())
            i += 1
    return picked


def call(client, model, system, user, max_retries=6, schema=SCHEMA):
    settings = MODEL_SETTINGS[model]
    params = dict(model=model, max_tokens=4096, system=system,
                  messages=[{"role": "user", "content": user}],
                  output_config={"format": {"type": "json_schema", "schema": schema}}, **settings)
    attempts, last_err = 0, None
    while attempts < max_retries:
        attempts += 1
        t0 = time.perf_counter()
        try:
            resp = client.messages.create(**params)
            return resp, time.perf_counter() - t0, attempts, settings, None
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            last_err = f"{type(e).__name__}: {e}"
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                last_err = f"{type(e).__name__}: {e}"
            else:
                return None, time.perf_counter() - t0, attempts, settings, f"{type(e).__name__}: {e}"
        time.sleep(min(2 ** attempts + random.random(), 60))
    return None, None, attempts, settings, f"gave up after {attempts} attempts: {last_err}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(MODEL_SETTINGS))
    ap.add_argument("--prompt", default="prompts/review_v1_DRAFT.txt")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--pilot", type=int, default=0, help="review only a stratified pilot sample of N patches")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--msg-cap-each", type=int, default=2000, help="max chars per failure message")
    ap.add_argument("--msg-cap-total", type=int, default=8000, help="max chars for all failure messages")
    ap.add_argument("--log", default="results/raw_llm_responses.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="build prompts and print sizes; no API calls")
    args = ap.parse_args()

    prompt_path = ROOT / args.prompt
    if "_DRAFT" in prompt_path.name and not args.pilot:
        sys.exit("Refusing a full run on a DRAFT prompt. The author must approve and rename the prompt first.")
    system, template, prompt_sha = load_prompt(prompt_path)
    records = [json.loads(l) for l in open(ROOT / "data" / "patches.jsonl")]
    trig_file = json.loads((ROOT / "data" / "trigger_tests.json").read_text())
    trig = trig_file["bugs"]

    if args.pilot:
        ids_file = ROOT / "data" / f"pilot_ids_n{args.pilot}_seed{args.seed}.txt"
        if ids_file.exists():
            ids = set(ids_file.read_text().split())
            records = [r for r in records if r["patch_id"] in ids]
        else:
            records = pilot_sample(records, args.pilot, args.seed)
            ids_file.write_text("\n".join(r["patch_id"] for r in records) + "\n")
        log_path = ROOT / args.log.replace(".jsonl", "_pilot.jsonl")
    else:
        log_path = ROOT / args.log

    done = set()
    if log_path.exists():
        for line in open(log_path):
            e = json.loads(line)
            if e["status"] == "ok":
                done.add((e["model"], e["prompt_sha"], e["patch_id"], e["run"]))
    jobs = [(r, run) for r in records for run in range(args.runs)
            if (args.model, prompt_sha, r["patch_id"], run) not in done]
    print(f"{len(records)} patches x {args.runs} runs; {len(jobs)} calls to make; log -> {log_path}")

    if args.dry_run:
        sizes = []
        for r in records:
            user, truncated = build_user_message(template, r, trig, args.msg_cap_each, args.msg_cap_total)
            sizes.append((len(system) + len(user), truncated, r))
        for n, t, r in sizes:
            print(f"  {r['label']:<11} {r['project']:<7} chars={n:>6} msg_truncated={t} {r['patch_id']}")
        print(f"total input chars for these patches: {sum(s[0] for s in sizes)}")
        print("===== example system prompt =====\n" + system)
        print("===== example user message (first pilot patch) =====\n" + build_user_message(
            template, records[0], trig, args.msg_cap_each, args.msg_cap_total)[0])
        return

    found = {str(p): load_dotenv(p) for p in (ROOT / ".env", ROOT.parent / ".env")}
    import os
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        # Variable names and whether each has a value only; never the values.
        sys.exit("No API key: expected a line 'ANTHROPIC_API_KEY=...'. Variables found (name, has value): "
                 + json.dumps({k: v for k, v in found.items() if v is not None}))
    client = anthropic.Anthropic(max_retries=2)
    lock = threading.Lock()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def work(rec, run):
        user, truncated = build_user_message(template, rec, trig, args.msg_cap_each, args.msg_cap_total)
        resp, latency, attempts, settings, err = call(client, args.model, system, user)
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "model": args.model,
                 "prompt_file": args.prompt, "prompt_sha": prompt_sha, "patch_id": rec["patch_id"],
                 "bug_id": rec["bug_id"], "run": run, "request_settings": settings,
                 "msg_cap_each": args.msg_cap_each, "msg_cap_total": args.msg_cap_total,
                 "failure_messages_truncated": truncated, "defects4j_commit": trig_file["defects4j_commit"],
                 "latency_s": latency, "attempts": attempts}
        if err:
            entry.update(status="error", error=err)
        else:
            text = next((b.text for b in resp.content if b.type == "text"), "")
            entry.update(status="ok", response_model=resp.model, request_id=resp._request_id,
                         stop_reason=resp.stop_reason, usage=resp.usage.to_dict(),
                         raw_response=resp.to_dict(), text=text)
            try:
                entry["parsed"] = json.loads(text)
            except json.JSONDecodeError as e:
                entry.update(parsed=None, parse_error=str(e))
        with lock:
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    n_ok = n_err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed([pool.submit(work, r, run) for r, run in jobs]):
            e = fut.result()
            if e["status"] == "ok":
                n_ok += 1
            else:
                n_err += 1
                print("ERROR", e["patch_id"], e["error"][:200])
    print(f"done: {n_ok} ok, {n_err} errors")


if __name__ == "__main__":
    main()
