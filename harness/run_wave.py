#!/usr/bin/env python3
"""
Plans a replay wave once, then runs one worker per function, one after
another, auditing the tree after each.

    # once, before the golden snapshot: dossiers, m2c sketches, BUDGET files
    python3 run_wave.py plan --wave qwen-replay --funcs /opt/rac1/functions/haiku55-2026-10-07.txt

    # per arm, from the golden snapshot
    BENCH_API_KEY=... python3 run_wave.py run --run qwen38-base-r1 \
        --funcs /opt/rac1/functions/haiku55-2026-10-07.txt -- --thinking

    # afterwards: one archive to copy out to the PC
    python3 run_wave.py export --run qwen38-base-r1

    # the floor, no model: m2c's sketch compiled as emitted (from golden)
    python3 run_wave.py baseline --run m2c --funcs /opt/rac1/functions/haiku55-2026-10-07.txt

Everything after `--` goes to worker.py unchanged.

The audit is the integrity half of the experiment. The agent runs as root
and is told to write only in build-sn/try/<func>/; after each worker this
records every tracked file it changed, every new file outside its folder,
and then restores the tracked tree so the next worker starts clean.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import worker  # noqa: E402

REPO = Path(os.environ.get("BENCH_REPO", "/opt/rac1/rac1-decomp"))
RESULTS = Path(os.environ.get("BENCH_RESULTS", "/opt/rac1/results"))
OUTBOX = Path(os.environ.get("BENCH_OUTBOX", "/opt/rac1/out"))
WATCH = ["/tmp", "/root", str(REPO.parent), "/etc", "/usr/local"]   # where stray writes would land
SKIP = ("/root/.cache", str(RESULTS), str(OUTBOX))
# Written by the system or by upstream's own tools when they run, not by the agent:
# Python bytecode caches (try_func runs under the container's Python) and
# background daemons' state files.
NOISE = ("/__pycache__/", "/etc/cups/", "/root/.python_history", "/root/.lesshst")


def sh(cmd, cwd=REPO, check=False):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check, errors="replace")


def read_funcs(path: str) -> list[str]:
    return [l.split("#")[0].strip() for l in Path(path).read_text().splitlines() if l.split("#")[0].strip()]


def plan(a):
    funcs = read_funcs(a.funcs)
    r = sh(["python3", "tools/wave.py", "plan", a.wave, "--budget", str(a.budget), *funcs])
    print(r.stdout, r.stderr)
    if r.returncode:
        sys.exit("wave.py plan failed")
    missing = [f for f in funcs if not (REPO / "build-sn/try" / f / "CONTEXT.md").exists()]
    if missing:
        sys.exit(f"no CONTEXT.md for: {' '.join(missing)}")
    print(f"planned {len(funcs)} functions; now cut the network and snapshot.")


def stray_files(marker: Path, func: str) -> list[str]:
    own = str(REPO / "build-sn/try" / func)
    found = []
    for root in WATCH:
        r = subprocess.run(["find", root, "-xdev", "-newer", str(marker), "-type", "f"],
                           capture_output=True, text=True, errors="replace")
        for p in r.stdout.splitlines():
            if p.startswith(own) or p.startswith(SKIP) or p == str(marker) or any(n in p for n in NOISE):
                continue
            found.append(p)
    return sorted(found)


def audit_and_restore(func: str, marker: Path) -> dict:
    status = sh(["git", "status", "--porcelain", "--untracked-files=all"]).stdout.splitlines()
    diff = sh(["git", "diff", "--stat"]).stdout
    report = {"func": func, "tracked_changes": status, "diff_stat": diff, "stray_files": stray_files(marker, func)}
    if status:  # put the tree back so the next worker does not inherit anything
        sh(["git", "checkout", "--", "."])
        sh(["git", "clean", "-fdq", "--", "src", "include", "config", "tools", "docs", "asm", "nonmatching"])
    return report


def run(a, worker_args: list[str]):
    funcs = read_funcs(a.funcs)
    if not os.environ.get("BENCH_API_KEY"):
        sys.exit("set BENCH_API_KEY")
    if sh(["git", "status", "--porcelain"]).stdout.strip():
        sys.exit("the tracked tree is not clean: start from the golden snapshot")
    out = RESULTS / a.run
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps({"run": a.run, "funcs": funcs, "worker_args": worker_args,
                                              "started": time.time()}, indent=2) + "\n")
    for i, func in enumerate(funcs, 1):
        if (out / func / "summary.json").exists() and not a.redo:
            print(f"[{i}/{len(funcs)}] {func}: done already, skipping")
            continue
        marker = RESULTS / ".markers" / f"{a.run}-{func}"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()))
        time.sleep(1.1)  # -newer has one-second resolution on some filesystems
        print(f"[{i}/{len(funcs)}] {func} ...", flush=True)
        args = worker.parser().parse_args(["--func", func, "--run", a.run, "--repo", str(REPO),
                                           "--out", str(RESULTS), *worker_args])
        s = worker.run(args)
        rep = audit_and_restore(func, marker)
        (out / func / "audit.json").write_text(json.dumps(rep, indent=2) + "\n")
        flag = " AUDIT!" if rep["tracked_changes"] or rep["stray_files"] else ""
        print(f"    {s['outcome']}: {s['final'][:100]!r} | in {s['tokens_input']:,} out {s['tokens_output']:,} "
              f"| {s['wall_s']} s{flag}", flush=True)


def baseline(a):
    """No-model floor: m2c's output, unedited, through the same judge.
    It goes in build-sn/try/<func>/m2c/ (try_func --arm=m2c), away from the
    workers' folders, and is exported like a worker run so verify.py and
    report.py treat it the same way."""
    funcs = read_funcs(a.funcs)
    out = RESULTS / a.run
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps({"run": a.run, "funcs": funcs, "baseline": "m2c",
                                              "started": time.time()}, indent=2) + "\n")
    for i, func in enumerate(funcs, 1):
        arm = REPO / "build-sn/try" / func / "m2c"
        arm.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        m = sh(["bash", "tools/docker/run.sh", "python3", "tools/m2c.py", func])
        cand = arm / "p0.c"
        cand.write_text(m.stdout if m.returncode == 0 else "/* m2c failed */\n")
        r = sh(["bash", "tools/docker/run.sh", "python3", "tools/try_func.py", func,
                str(cand.relative_to(REPO)), "--arm=m2c"])
        verdict = next((l.split(": ", 1)[1].split("   ")[0] for l in r.stdout.splitlines()
                        if l.startswith(func + ":")), "UNKNOWN")
        d = out / func
        d.mkdir(parents=True, exist_ok=True)
        summary = {"func": func, "run": a.run, "outcome": "baseline", "final": verdict,
                   "m2c_exit": m.returncode, "wall_s": round(time.time() - t0, 1),
                   "tokens_input": 0, "tokens_output": 0, "gpu_s": 0}
        (d / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"[{i}/{len(funcs)}] {func}: {verdict}", flush=True)


def export(a):
    OUTBOX.mkdir(parents=True, exist_ok=True)
    run_dir = RESULTS / a.run
    funcs = json.loads((run_dir / "run.json").read_text())["funcs"]
    dest = OUTBOX / f"{a.run}.tar.gz"
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(run_dir, arcname=f"{a.run}/results")
        for f in funcs:
            d = REPO / "build-sn/try" / f
            if d.exists():
                tar.add(d, arcname=f"{a.run}/try/{f}")
    print(f"{dest}  (copy it to the PC: scp -J JUMP VM:{dest} .)")


def main():
    argv = sys.argv[1:]
    worker_args = []
    if "--" in argv:
        i = argv.index("--")
        argv, worker_args = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--wave", required=True); p.add_argument("--funcs", required=True)
    p.add_argument("--budget", type=int, default=15)
    r = sub.add_parser("run"); r.add_argument("--run", required=True); r.add_argument("--funcs", required=True)
    r.add_argument("--redo", action="store_true")
    e = sub.add_parser("export"); e.add_argument("--run", required=True)
    b = sub.add_parser("baseline"); b.add_argument("--run", default="m2c"); b.add_argument("--funcs", required=True)
    a = ap.parse_args(argv)
    {"plan": lambda: plan(a), "run": lambda: run(a, worker_args), "export": lambda: export(a),
     "baseline": lambda: baseline(a)}[a.cmd]()


if __name__ == "__main__":
    main()
