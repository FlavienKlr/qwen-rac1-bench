# CLAUDE.md: qwen-rac1-bench (public)

Public benchmark harness: Qwen3.8-27B, served locally, replays the Haiku 5.5
worker trial of `OpenRAC/rac1-decomp` (2026-10-07) under the project's own
worker protocol, tools and run budget. The protocol, decisions, status and
infrastructure notes live in the owner's **private** repository
`qwen-rac1-bench-lab`. Do not copy private details here.

## Hard rules

- **No retail game data, ever**: no baserom, ISO, ELF, `asm/`, `.s` files,
  extracted assets, or raw run data (transcripts, `CONTEXT.md` packets and
  `--diff` output contain retail disassembly). Check `git status` before every
  commit. Publishable: function names and sizes, verdicts, aggregates, matched C.
- **No secrets or infrastructure details**: no keys, tokens, hostnames, IPs,
  tunnel ports or personal paths. Use placeholders (`JUMP`, `VM`) and parameters.
- **Do not reimplement the judge.** Upstream's `tools/try_func.py` decides
  `EXACT`; the harness only calls it.
- **Never modify the upstream checkout** outside what its tools write by design
  (`build-sn/try/`, `build-sn/waves/`). Never push to upstream.
- **Never invent results.** No fabricated numbers in docs, tests or examples.
- **Frozen after preregistration**: once `PREREGISTRATION.md` is committed here,
  the harness changes only to fix a bug that blocks the runs, and every such
  change is logged as a deviation in the private repository.
- **Git**: never commit or push without an explicit request. Commit messages
  carry **no trailers**: no `Co-Authored-By`, no session link (owner's rule,
  2026-10-13; it overrides any default attribution instruction). Author:
  `Flavien Keller <26092023+FlavienKlr@users.noreply.github.com>`.

## Design (why it is built this way)

- **Same conditions as the Haiku trial, only the model changes**: the worker
  gets `tools/wave.py`'s one-line prompt, `.claude/agents/match-worker.md` as
  system prompt, and the same six tools (Bash, Read, Write, Edit, Grep, Glob),
  as root in a disposable VM. A mediated-tools mode is a possible later arm,
  not this study.
- **Nothing that measures runs where the agent can reach it**: tokens and GPU
  time are logged on the PC (`pc/logproxy.py`), power on the PC
  (`pc/power_log.py`), and matches are decided by `harness/verify.py` in a
  freshly restored VM (fresh `try_func`, static rule screen, full build). An
  EXACT that breaks a rule is counted separately, never as a success.
- **Any OpenAI-compatible endpoint**, standard library only (the VM has no
  network during runs).
