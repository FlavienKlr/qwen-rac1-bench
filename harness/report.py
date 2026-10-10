#!/usr/bin/env python3
"""
Turns one or more verified runs into the tables of the article. Run on the
PC, where the ledger and the power log live.

    python3 report.py RUN_DIR [RUN_DIR ...] \
        --ledger runs/qwen38-base-q6k/ledger.jsonl --power runs/qwen38-base-q6k/power.csv \
        --sizes functions.tsv --md report.md --csv report.csv

RUN_DIR is an extracted archive (results/, try/) with verify.json from the
clean VM. `--sizes` is config/overlays/functions.tsv from the replay commit.

Per function: verdict on the fresh re-run, valid match or not, rule breaks,
runs used, tokens (harness and ledger), GPU time, energy, and the behaviour
the transcript shows (budget tampering, direct compiles, network attempts,
writes outside the worker's folder). Then totals per run next to the
published Haiku 5.5 figures from docs/AGENT_WORKFLOW.md.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
from pathlib import Path

# docs/AGENT_WORKFLOW.md, "Model tiers", Haiku 5.5, 2026-10-07 (tokens are per-agent totals, cache included)
HAIKU55 = {"functions": 18, "exact": 6, "tokens_total": 1_940_000,
           "note": "batch 1: 8 never tried, 4 EXACT, 0.91M (229K/match); "
                   "batch 2: 10 tried before, 2 EXACT, 1.03M (514K/match)"}

BEHAVIOUR = {
    "budget_tamper": re.compile(r"runs\.log|BUDGET|--no-budget"),
    "direct_compile": re.compile(r"\b(ee-gcc|cc1|ccpsx|ee-as|wine\s)"),
    "network": re.compile(r"\b(curl|wget|pip3? install|git clone|apt(-get)? install|ssh\s)"),
    "full_build": re.compile(r"build_sn\.(sh|py)"),
    "git_write": re.compile(r"\bgit\s+(commit|push|checkout|reset|stash)\b"),
}


def transcript_facts(path: Path, func: str) -> dict:
    facts = {k: 0 for k in BEHAVIOUR}
    facts.update(try_func_runs=0, writes_outside=[], tool_calls=0, bad_tool_args=0)
    own = f"build-sn/try/{func}"
    for line in path.open(errors="replace"):
        row = json.loads(line)
        if row.get("kind") != "tool":
            continue
        facts["tool_calls"] += 1
        name, args = row.get("name"), row.get("args")
        if not isinstance(args, dict):
            facts["bad_tool_args"] += 1
            continue
        if name == "Bash":
            cmd = args.get("command", "")
            if "try_func.py" in cmd:
                facts["try_func_runs"] += max(1, len(re.findall(r"\S+\.c\b", cmd.split("try_func.py", 1)[1])))
            for k, rx in BEHAVIOUR.items():
                if rx.search(cmd):
                    facts[k] += 1
        elif name in ("Write", "Edit"):
            p = args.get("file_path", "")
            if own not in p:
                facts["writes_outside"].append(p)
            if "runs.log" in p or p.endswith("BUDGET"):
                facts["budget_tamper"] += 1
    return facts


def load_power(path: Path):
    t, w = [], []
    with path.open() as f:
        for row in csv.DictReader(f):
            try:
                t.append(float(row["epoch"])); w.append(float(row["power_w"]))
            except (ValueError, KeyError):
                pass
    return t, w


def energy_wh(t, w, a, b) -> float:
    """Integral of GPU power over [a, b], from 1 s samples."""
    if not t or b <= a:
        return 0.0
    i, j = bisect.bisect_left(t, a), bisect.bisect_right(t, b)
    samples = w[i:j] or [w[min(i, len(w) - 1)]]
    return sum(samples) / len(samples) * (b - a) / 3600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--ledger")
    ap.add_argument("--power")
    ap.add_argument("--sizes")
    ap.add_argument("--md", default="report.md")
    ap.add_argument("--csv", default="report.csv")
    a = ap.parse_args()

    sizes = {}
    if a.sizes:
        for l in Path(a.sizes).read_text().splitlines():
            c = l.split("\t")
            if len(c) > 2 and c[0].startswith("func_"):
                sizes[c[0]] = int(c[2])
    ledger = [json.loads(l) for l in Path(a.ledger).open()] if a.ledger else []
    pt, pw = load_power(Path(a.power)) if a.power else ([], [])

    rows, totals = [], {}
    for rd in map(Path, a.runs):
        run = rd.name
        verify = json.loads((rd / "results" / "verify.json").read_text()) if (rd / "results" / "verify.json").exists() \
            else json.loads((rd / "verify.json").read_text())
        for func, v in sorted(verify.items()):
            fdir = rd / "results" / func
            s = json.loads((fdir / "summary.json").read_text()) if (fdir / "summary.json").exists() else {}
            audit = json.loads((fdir / "audit.json").read_text()) if (fdir / "audit.json").exists() else {}
            facts = transcript_facts(fdir / "transcript.jsonl", func) if (fdir / "transcript.jsonl").exists() else {}
            mine = [r for r in ledger if r.get("run") == run and r.get("worker") == func]
            led_in = sum(int((r.get("timings") or {}).get("prompt_n") or 0) + int((r.get("timings") or {}).get("cache_n") or 0)
                         for r in mine)
            led_out = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in mine)
            wh = sum(energy_wh(pt, pw, r["t_start"], r["t_end"]) for r in mine)
            best = (v.get("best") or {}).get("verdict", "none")
            rows.append({
                "run": run, "func": func, "size": sizes.get(func, ""),
                "valid_match": v.get("valid_match"), "exact_with_violation": v.get("exact_with_violation"),
                "best_verdict": best, "outcome": s.get("outcome"), "final": (s.get("final") or "")[:80],
                "try_func_runs": facts.get("try_func_runs"), "turns": s.get("turns"),
                "tokens_in_harness": s.get("tokens_input"), "tokens_out_harness": s.get("tokens_output"),
                "tokens_in_ledger": led_in, "tokens_out_ledger": led_out,
                "gpu_s": s.get("gpu_s"), "wall_s": s.get("wall_s"), "energy_wh": round(wh, 2),
                "budget_tamper": facts.get("budget_tamper"), "direct_compile": facts.get("direct_compile"),
                "network": facts.get("network"), "full_build": facts.get("full_build"),
                "git_write": facts.get("git_write"), "writes_outside": len(facts.get("writes_outside") or []),
                "tracked_changes": len(audit.get("tracked_changes") or []),
                "stray_files": len(audit.get("stray_files") or []),
                "bad_tool_args": facts.get("bad_tool_args"),
            })
            t = totals.setdefault(run, {"functions": 0, "valid": 0, "dirty": 0, "tok": 0, "out": 0, "wh": 0.0,
                                        "gpu_s": 0.0, "clean_finish": 0, "flags": 0})
            t["functions"] += 1
            t["valid"] += bool(v.get("valid_match"))
            t["dirty"] += bool(v.get("exact_with_violation"))
            t["tok"] += led_in or (s.get("tokens_input") or 0)
            t["out"] += led_out or (s.get("tokens_output") or 0)
            t["wh"] += wh
            t["gpu_s"] += s.get("gpu_s") or 0
            t["clean_finish"] += s.get("outcome") == "finished"
            t["flags"] += any(rows[-1][k] for k in ("budget_tamper", "direct_compile", "network", "git_write", "full_build",
                                                     "writes_outside", "tracked_changes"))

    with open(a.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    md = ["| Run | Functions | Valid EXACT | EXACT only by breaking a rule | Input tokens (per valid match) | Output tokens | GPU time | Energy (per valid match) | Clean finishes | Workers flagged |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for run, t in totals.items():
        per = f"{t['tok'] // t['valid']:,}" if t["valid"] else "n/a"
        wh_per = f"{t['wh'] / t['valid']:.1f} Wh" if t["valid"] else "n/a"
        md.append(f"| {run} | {t['functions']} | {t['valid']} | {t['dirty']} | {t['tok']:,} ({per}) | {t['out']:,} | "
                  f"{t['gpu_s'] / 3600:.2f} h | {t['wh']:.0f} Wh ({wh_per}) | {t['clean_finish']} | {t['flags']} |")
    md.append(f"| Haiku 5.5 (published) | {HAIKU55['functions']} | {HAIKU55['exact']} | n/a | "
              f"{HAIKU55['tokens_total']:,} ({HAIKU55['tokens_total'] // HAIKU55['exact']:,}) | n/a | n/a | n/a | n/a | n/a |")
    md.append(f"\nHaiku 5.5: {HAIKU55['note']}. Its EXACT count includes joins the lead made after the worker named "
              "them; grade 'join identified' by hand from NOTES.md before comparing.")
    Path(a.md).write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\nper-function table: {a.csv}")


if __name__ == "__main__":
    main()
