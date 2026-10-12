#!/usr/bin/env python3
"""
One matching worker driven by a local model, on the same protocol the
project's Claude workers follow (docs/WORKER.md through .claude/agents/
match-worker.md): the same one-line prompt, the same six tools (Bash, Read,
Write, Edit, Grep, Glob), the same try_func budget. Only the model changes.

Talks to an OpenAI-compatible endpoint (llama-server --jinja) with tool
calls. Standard library only: the VM has no network once the run starts.

    python3 worker.py --func func_L00_001F75F8 --run qwen38-base-r1 \
        --repo /opt/rac1/rac1-decomp --out /opt/rac1/results

Writes, under OUT/RUN/FUNC/:
    transcript.jsonl   every request's usage/timings and every message, in order
    summary.json       outcome, turns, tokens, wall time, last line
The token figures here are the harness's view; the PC's ledger
(pc/logproxy.py) is the copy the agent cannot edit.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUTPUT_LIMIT = 30000          # characters of tool output given back, as Claude Code does
READ_LIMIT = 2000             # lines per Read by default

# The project's sub-agent definition, used as the system prompt (match-worker.md body).
SYSTEM_FROM_AGENT_FILE = ".claude/agents/match-worker.md"

SECTION = {"match": "Matching", "compile": "First compile"}


def worker_prompt(func: str, repo: str, budget: int, role: str = "match") -> str:
    """tools/wave.py's prompt() with the VM's repository path."""
    return (f"You are a {role} worker on {func} in the repository {repo} "
            f"(run every command from there). Follow docs/WORKER.md, the rules and the "
            f"\"{SECTION[role]}\" section; your context is build-sn/try/{func}/CONTEXT.md and "
            f"your budget is {budget} try_func runs. Work alone: never use the Agent, "
            f"WebSearch or WebFetch tools.")


def system_prompt(repo: Path) -> str:
    text = (repo / SYSTEM_FROM_AGENT_FILE).read_text()
    body = text.split("---", 2)[2].strip() if text.startswith("---") else text
    return (body + "\n\nYou act through tool calls. When you are finished, reply with your final "
            "one-line answer and no tool call.")


TOOLS = [
    {"type": "function", "function": {
        "name": "Bash",
        "description": "Run a bash command from the repository root and return its output. Default timeout 600 s.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "seconds, at most 1800"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "Read",
        "description": "Read a text file with line numbers. Paths are relative to the repository root or absolute.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"},
            "offset": {"type": "integer", "description": "first line, 1-based"},
            "limit": {"type": "integer"}},
            "required": ["file_path"]}}},
    {"type": "function", "function": {
        "name": "Write",
        "description": "Create or overwrite a file with the given content.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file_path", "content"]}}},
    {"type": "function", "function": {
        "name": "Edit",
        "description": "Replace an exact string in a file. old_string must occur exactly once unless replace_all is true.",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}, "old_string": {"type": "string"},
            "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
            "required": ["file_path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "Grep",
        "description": "Search file contents with a regular expression (ripgrep). Returns matching lines with paths and line numbers.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"},
            "glob": {"type": "string", "description": "file filter, e.g. *.c"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "Glob",
        "description": "List files matching a glob pattern such as src/**/*.c.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}},
            "required": ["pattern"]}}},
]


def clip(text: str, limit: int = OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} characters cut] ...\n" + text[-half:]


class Tools:
    def __init__(self, repo: Path):
        self.repo = repo

    def _path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else self.repo / q

    def Bash(self, command: str, timeout: int = 600) -> str:
        timeout = max(1, min(int(timeout or 600), 1800))
        try:
            r = subprocess.run(["bash", "-lc", command], cwd=self.repo, capture_output=True,
                               text=True, timeout=timeout, errors="replace")
            out = r.stdout + (("\n" + r.stderr) if r.stderr else "")
            return clip(out) + (f"\n[exit code {r.returncode}]" if r.returncode else "")
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or "") if isinstance(e.stdout, str) else ""
            return clip(partial) + f"\n[timed out after {timeout} s]"

    def Read(self, file_path: str, offset: int = 1, limit: int = READ_LIMIT) -> str:
        p = self._path(file_path)
        if not p.exists():
            return f"Error: {file_path} does not exist"
        if p.is_dir():
            return f"Error: {file_path} is a directory"
        lines = p.read_text(errors="replace").splitlines()
        start = max(1, int(offset or 1))
        chunk = lines[start - 1:start - 1 + int(limit or READ_LIMIT)]
        if not chunk:
            return "(empty)" if not lines else f"(no lines from {start}; the file has {len(lines)})"
        return clip("\n".join(f"{i:6}\t{l}" for i, l in enumerate(chunk, start)))

    def Write(self, file_path: str, content: str) -> str:
        p = self._path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} characters to {file_path}"

    def Edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        p = self._path(file_path)
        if not p.exists():
            return f"Error: {file_path} does not exist"
        text = p.read_text(errors="replace")
        n = text.count(old_string)
        if n == 0:
            return "Error: old_string not found"
        if n > 1 and not replace_all:
            return f"Error: old_string occurs {n} times; make it unique or set replace_all"
        p.write_text(text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1))
        return f"Edited {file_path} ({n if replace_all else 1} replacement)"

    def Grep(self, pattern: str, path: str = ".", glob: str | None = None) -> str:
        cmd = ["rg", "-n", "--no-heading", "-e", pattern]
        if glob:
            cmd += ["-g", glob]
        cmd.append(path or ".")
        try:
            r = subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True, timeout=120, errors="replace")
        except FileNotFoundError:
            r = subprocess.run(["grep", "-rnE", pattern, path or "."], cwd=self.repo,
                               capture_output=True, text=True, timeout=120, errors="replace")
        return clip(r.stdout or r.stderr or "(no matches)")

    def Glob(self, pattern: str, path: str = ".") -> str:
        base = self._path(path or ".")
        hits = sorted(str(p.relative_to(self.repo)) if p.is_relative_to(self.repo) else str(p)
                      for p in base.glob(pattern))
        return clip("\n".join(hits) or "(no files)")

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if fn is None or name.startswith("_") or name == "call":
            return f"Error: no tool named {name}. Tools: Bash, Read, Write, Edit, Grep, Glob"
        try:
            return fn(**args)
        except TypeError as e:
            return f"Error: bad arguments for {name}: {e}"
        except Exception as e:  # a tool error goes back to the model, as in Claude Code
            return f"Error: {type(e).__name__}: {e}"


class Endpoint:
    def __init__(self, url: str, key: str, run: str, worker: str):
        self.url = url.rstrip("/") + "/v1/chat/completions"
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                        "X-Bench-Run": run, "X-Bench-Worker": worker}

    def chat(self, body: dict, timeout: int = 3600) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"error": {"status": e.code, "body": e.read().decode(errors="replace")[:4000]}}


def input_tokens(resp: dict) -> int:
    """The whole prompt read for this turn, cached or not: what upstream's
    `wave.py tokens` counts as input (input + cache creation + cache reads)."""
    t = resp.get("timings") or {}
    if "prompt_n" in t:
        return int(t.get("prompt_n") or 0) + int(t.get("cache_n") or 0)
    return int((resp.get("usage") or {}).get("prompt_tokens") or 0)


# Recovery (deviation 1, 2026-10-12): a response cut at the output limit, or one
# with neither a tool call nor any text, is discarded and the model is told to
# act. Without this, one over-long deliberation ended the worker (pass 1).
NUDGE_CUT = ("Your previous response was cut off at the output limit before you called a tool, "
             "and it has been discarded. Do not restate your analysis. Take the next concrete step "
             "now with a tool call (for example write a candidate and run try_func), or end with "
             "your one-line verdict.")
NUDGE_EMPTY = ("Your previous response contained no tool call and no answer. Take the next concrete "
               "step now with a tool call, or end with your one-line verdict.")

FINAL = re.compile(r"(EXACT|BYTES\s+\d+/\d+|SIZE\b[^|]*|COMPILE)\s*\|")


def run(a) -> dict:
    repo = Path(a.repo).resolve()
    out = Path(a.out) / a.run / a.func
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "transcript.jsonl", "a")

    def record(kind: str, **kw):
        log.write(json.dumps({"t": time.time(), "kind": kind, **kw}) + "\n")
        log.flush()

    tools = Tools(repo)
    ep = Endpoint(a.endpoint, a.api_key, a.run, a.func)
    messages = [{"role": "system", "content": system_prompt(repo)},
                {"role": "user", "content": worker_prompt(a.func, str(repo), a.budget, a.role)}]
    for m in messages:
        record("message", message=m)

    totals = {"input": 0, "output": 0, "gpu_ms": 0.0, "requests": 0}
    recoveries = []
    outcome, final_text, t0 = "max_turns", "", time.time()

    for turn in range(1, a.max_turns + 1):
        if time.time() - t0 > a.max_wall:
            outcome = "max_wall"
            break
        body = {"model": a.model, "messages": messages, "tools": TOOLS, "tool_choice": "auto",
                "temperature": a.temperature, "top_p": a.top_p, "top_k": a.top_k, "min_p": a.min_p,
                "seed": a.seed + turn, "max_tokens": a.max_tokens,
                "chat_template_kwargs": {"enable_thinking": a.thinking}}
        resp = ep.chat(body)
        totals["requests"] += 1
        if "error" in resp:
            record("error", turn=turn, error=resp["error"])
            body_txt = json.dumps(resp["error"]).lower()
            outcome = "context_exhausted" if ("context" in body_txt or "exceed" in body_txt) else "server_error"
            break

        usage, timings = resp.get("usage") or {}, resp.get("timings") or {}
        totals["input"] += input_tokens(resp)
        totals["output"] += int(usage.get("completion_tokens") or timings.get("predicted_n") or 0)
        totals["gpu_ms"] += float(timings.get("prompt_ms") or 0) + float(timings.get("predicted_ms") or 0)

        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        reasoning = msg.get("reasoning_content")
        calls = msg.get("tool_calls") or []
        finish = choice.get("finish_reason")
        record("response", turn=turn, usage=usage, timings=timings, finish_reason=finish,
               content=msg.get("content"), reasoning=reasoning, tool_calls=calls)

        cut = finish == "length"
        empty = not calls and not (msg.get("content") or "").strip()
        if cut or empty:
            ctx_used = int(timings.get("prompt_n") or 0) + int(timings.get("cache_n") or 0) \
                + int(timings.get("predicted_n") or usage.get("completion_tokens") or 0)
            if cut and a.ctx and ctx_used >= a.ctx - 64:
                outcome = "context_exhausted"     # the window is full: retrying cannot help
                break
            if len(recoveries) < a.max_recoveries:
                kind = "cut" if cut else "empty"
                recoveries.append({"turn": turn, "kind": kind})
                nudge = {"role": "user", "content": NUDGE_CUT if cut else NUDGE_EMPTY}
                messages.append(nudge)
                record("recovery", turn=turn, cause=kind, message=nudge)
                continue
            outcome = "output_truncated" if cut else "stopped_without_verdict"
            break

        kept = {"role": "assistant", "content": msg.get("content") or ""}
        if a.keep_reasoning and reasoning:
            kept["reasoning_content"] = reasoning
        if calls:
            kept["tool_calls"] = calls
        messages.append(kept)

        if not calls:
            final_text = (msg.get("content") or "").strip()
            outcome = "finished" if FINAL.search(final_text) else "stopped_without_verdict"
            if choice.get("finish_reason") == "length":
                outcome = "output_truncated"
            break

        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
                result = tools.call(name, args) if isinstance(args, dict) else "Error: arguments must be an object"
            except json.JSONDecodeError as e:
                args, result = fn.get("arguments"), f"Error: arguments are not valid JSON: {e}"
            tool_msg = {"role": "tool", "tool_call_id": call.get("id", ""), "name": name, "content": result}
            messages.append(tool_msg)
            record("tool", turn=turn, name=name, args=args, result=result)

    summary = {"func": a.func, "run": a.run, "outcome": outcome, "turns": turn, "final": final_text,
               "wall_s": round(time.time() - t0, 1), "tokens_input": totals["input"],
               "tokens_output": totals["output"], "gpu_s": round(totals["gpu_ms"] / 1000, 1),
               "requests": totals["requests"], "recoveries": recoveries,
               "settings": {k: getattr(a, k) for k in ("model", "budget", "role", "temperature", "top_p", "top_k", "min_p",
                                                        "seed", "thinking", "keep_reasoning", "max_turns",
                                                        "max_wall", "max_tokens", "max_recoveries", "ctx")}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    record("summary", **summary)
    return summary


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--func", required=True)
    ap.add_argument("--run", required=True, help="run id, e.g. qwen38-base-r1")
    ap.add_argument("--repo", default="/opt/rac1/rac1-decomp")
    ap.add_argument("--out", default="/opt/rac1/results")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8080")
    ap.add_argument("--api-key", default=os.environ.get("BENCH_API_KEY", ""))
    ap.add_argument("--budget", type=int, default=15, help="try_func runs; the Haiku 5.5 trial used 15")
    ap.add_argument("--role", choices=list(SECTION), default="match")
    # Sampling: the request overrides the preset. Defaults: the agentic preset in pc/bench-presets.ini; never change them between arms.
    ap.add_argument("--model", default="bench-base", help="router preset name (llama-server --models-preset)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--min-p", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--keep-reasoning", action="store_true",
                    help="keep reasoning in the history (Qwen's guidance is to drop it)")
    ap.add_argument("--max-turns", type=int, default=150)
    ap.add_argument("--max-wall", type=int, default=3 * 3600, help="seconds")
    ap.add_argument("--max-tokens", type=int, default=32768, help="per response, as the router preset's predict")
    ap.add_argument("--max-recoveries", type=int, default=3,
                    help="cut or empty responses discarded and retried with a nudge (0 = protocol v1)")
    ap.add_argument("--ctx", type=int, default=131072, help="server context, to tell a full window from a long answer")
    return ap


if __name__ == "__main__":
    s = run(parser().parse_args())
    print(json.dumps(s))
    sys.exit(0)
