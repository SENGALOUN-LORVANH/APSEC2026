"""Fetch Defects4J trigger (failing) test info for every bug in data/patches.jsonl.

Pinned to a single defects4j commit, recorded in the output for reproducibility.

Outputs:
  data/raw/trigger_tests/<Project>/<bug>.txt   raw files
  data/trigger_tests.json                      {bug_id: {"tests": [...], "messages": [...]}}
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "trigger_tests"
REPO = "rjust/defects4j"


def get(url, retries=5):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except urllib.error.URLError as e:
            err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after {retries} attempts: {url}: {err}")


def parse(text):
    """Blocks start with '--- Class::method'; the next non-frame lines are the failure message."""
    tests, messages = [], []
    current = None
    for line in text.splitlines():
        if line.startswith("--- "):
            current = line[4:].strip()
            tests.append(current)
            messages.append([])
        elif current is not None and not line.startswith("\tat ") and line.strip():
            messages[-1].append(line)
    return tests, ["\n".join(m) for m in messages]


def main():
    sha = json.loads(get(f"https://api.github.com/repos/{REPO}/commits/master"))["sha"]
    bugs = sorted({json.loads(l)["bug_id"] for l in open(ROOT / "data" / "patches.jsonl")})
    out, missing = {}, []
    for bug in bugs:
        project, num = bug.rsplit("-", 1)
        dest = RAW / project / f"{num}.txt"
        if dest.exists():
            text = dest.read_text()
        else:
            text = get(f"https://raw.githubusercontent.com/{REPO}/{sha}/framework/projects/{project}/trigger_tests/{num}")
            if text is None:
                missing.append(bug)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
        tests, messages = parse(text)
        out[bug] = {"tests": tests, "messages": messages}
    result = {"defects4j_repo": REPO, "defects4j_commit": sha, "n_bugs": len(bugs),
              "n_found": len(out), "missing": missing, "bugs": out}
    with open(ROOT / "data" / "trigger_tests.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"commit {sha}: {len(out)}/{len(bugs)} bugs found; missing: {missing}")


if __name__ == "__main__":
    main()
