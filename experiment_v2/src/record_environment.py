"""Record the experiment machine and software environment.

Authoritative runs (Linux / WSL2 on the lab PC):
  python src/record_environment.py --authoritative
    -> results/environment.json, results/environment.txt
Any other host (e.g. macOS development machine):
  python src/record_environment.py
    -> logs/dev_environment_<timestamp>.json   (never written to results/)
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + p.stderr).strip()
        return out if out else None
    except Exception as e:  # noqa: BLE001 - recorded, not hidden
        return f"ERROR: {e}"


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def os_info():
    info = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "kernel": run("uname -srvm")}
    osr = read("/etc/os-release")
    if osr:
        kv = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', osr, re.M))
        info["distribution"] = kv.get("PRETTY_NAME")
    proc_version = read("/proc/version") or ""
    info["wsl"] = "microsoft" in proc_version.lower()
    if platform.system() == "Darwin":
        info["distribution"] = run("sw_vers | tr '\\n' ' '")
    return info


def cpu_mem_info():
    info = {"logical_cores": os.cpu_count()}
    if platform.system() == "Linux":
        lscpu = run("lscpu") or ""
        get = lambda k: (re.search(rf"^{k}:\s*(.+)$", lscpu, re.M) or [None, None])[1]
        info["cpu_model"] = get("Model name")
        sockets, cores = get("Socket\\(s\\)"), get("Core\\(s\\) per socket")
        if sockets and cores:
            info["physical_cores"] = int(sockets) * int(cores)
        mem = re.search(r"MemTotal:\s+(\d+) kB", read("/proc/meminfo") or "")
        info["ram_gb"] = round(int(mem.group(1)) / 1024 / 1024, 2) if mem else None
    elif platform.system() == "Darwin":
        info["cpu_model"] = run("sysctl -n machdep.cpu.brand_string")
        info["physical_cores"] = int(run("sysctl -n hw.physicalcpu") or 0)
        info["ram_gb"] = round(int(run("sysctl -n hw.memsize") or 0) / 1024 ** 3, 2)
    return info


def gpu_info():
    if not shutil.which("nvidia-smi"):
        return {"gpu": None, "note": "nvidia-smi not found"}
    q = run("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader")
    cuda = re.search(r"CUDA Version:\s*([\d.]+)", run("nvidia-smi") or "")
    return {"gpus": [dict(zip(["name", "vram", "driver"], [x.strip() for x in l.split(",")]))
                     for l in (q or "").splitlines() if l.strip()],
            "cuda_driver_version": cuda.group(1) if cuda else None,
            "nvcc": run("nvcc --version | tail -n 1") if shutil.which("nvcc") else None}


def software_info():
    d4j_home = os.environ.get("DEFECTS4J_HOME")
    tools_lock = ROOT / "configs" / "tools.lock"
    return {
        "python": sys.version,
        "pip_freeze": (run(f"{sys.executable} -m pip freeze") or "").splitlines(),
        "java": run("java -version") if shutil.which("java") else None,
        "javac": run("javac -version") if shutil.which("javac") else None,
        "java_home": os.environ.get("JAVA_HOME"),
        "maven": run("mvn -v") if shutil.which("mvn") else None,
        "gradle": run("gradle -v") if shutil.which("gradle") else None,
        "ant": run("ant -version") if shutil.which("ant") else None,
        "perl": run("perl -e 'print $^V'") if shutil.which("perl") else None,
        "defects4j_home": d4j_home,
        "defects4j_commit": run(f"git -C {d4j_home} rev-parse HEAD") if d4j_home else None,
        "defects4j_describe": run(f"git -C {d4j_home} describe --tags --always") if d4j_home else None,
        "docker": run("docker version --format '{{.Client.Version}} / server {{.Server.Version}}'")
        if shutil.which("docker") else None,
        "in_docker": Path("/.dockerenv").exists(),
        "tools_lock": read(tools_lock) if tools_lock.exists() else None,
        "spotbugs": run("spotbugs -version") if shutil.which("spotbugs") else None,
        "git_commit": run(f"git -C {ROOT} rev-parse HEAD"),
        "git_dirty": bool(run(f"git -C {ROOT} status --porcelain")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--authoritative", action="store_true",
                    help="write results/environment.{json,txt}; only allowed on Linux (native or WSL2)")
    args = ap.parse_args()
    env = {"recorded_at": datetime.now(timezone.utc).isoformat(), "hostname": platform.node(),
           "os": os_info(), "hardware": {**cpu_mem_info(), **gpu_info()}, "software": software_info()}
    env["authoritative"] = bool(args.authoritative)
    if args.authoritative:
        if platform.system() != "Linux":
            sys.exit("Refusing: authoritative environment must be Linux (native Ubuntu or WSL2).")
        out = ROOT / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "environment.json").write_text(json.dumps(env, indent=2))
        lines = [f"{k}: {v}" for k, v in {**env["os"], **env["hardware"]}.items()]
        lines += [f"{k}: {v}" for k, v in env["software"].items() if k != "pip_freeze"]
        (out / "environment.txt").write_text("\n".join(lines) + "\n")
        print(f"wrote {out/'environment.json'} and environment.txt")
    else:
        out = ROOT / "logs"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"dev_environment_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        path.write_text(json.dumps(env, indent=2))
        print(f"non-authoritative host; wrote {path}")


if __name__ == "__main__":
    main()
