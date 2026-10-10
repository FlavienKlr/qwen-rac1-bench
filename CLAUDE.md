# CLAUDE.md — qwen-rac1-bench (public)

Public benchmark harness: does a locally run Qwen model manage matching decompilation on `OpenRAC/rac1-decomp` (Ratchet & Clank, PS2, PAL)? The full protocol, decisions and infra notes live in the owner's **private** repo `qwen-rac1-bench-lab` (`PROTOCOL.md` is the spec this harness implements). Do not copy private infra details here.

## Language

The owner talks in French. Everything committed to this repo (code, comments, docs, commit messages) is in **English**.

## Hard rules

- **No retail game data, ever**: no baserom, ISO, ELF, `asm/`, `.s` files, extracted assets, or raw run logs (packets and `--diff` output contain retail disassembly). `.gitignore` blocks the usual paths; check `git status` before every commit anyway. Outputs that may be published: function names and sizes, aggregate metrics, matched C.
- **No secrets or infra details**: no keys, tokens, hostnames, IPs or tunnel ports. Configuration comes from environment variables or a gitignored local file.
- **Do not reimplement the judge.** `tools/try_func.py` from the upstream checkout decides `EXACT`. The harness calls it as a subprocess (through the upstream container wrapper `tools/docker/run.sh`), with `--arm=<arm>` so each condition gets its own folder, run log and budget.
- **Never modify the upstream checkout** except where upstream tools write by design (`build-sn/try/<func>/<arm>/`, `build-sn/waves/`). Never push to upstream; never use its shared claims for benchmark runs.
- **Never invent results.** No fabricated numbers in docs, tests or examples; use clearly fake fixtures in tests.
- **Git**: never commit or push without an explicit request.

## Design principles

- **The model only gets mediated tools** in the default mode: `write_candidate`, `run_try_func`, `read_file` (allowlist), `append_notes`, `stop`. No shell. A shell arm, if added, must hash the protected upstream tree before and after each function and record every change.
- **Log everything, one JSONL line per attempt**: function, arm, run number, verdict, input / cached / output tokens, wall time, candidate hash. Logs go to a directory outside the repo, given by configuration.
- **Reproducibility**: record the upstream commit, the harness commit, the model file hash, quantization, llama.cpp commit, context length and sampling parameters in every run's metadata.
- **Validity screen** on every `EXACT`: re-run `try_func --no-budget` in a clean checkout, then check for forbidden constructs (inline asm in a function body, register pins, barriers, `volatile` added to pin an order, `#define`, numeric level addresses, `__asm__` aliases on expressions). An `EXACT` that fails the screen is recorded as an invalid match, never as a success.
- **Any OpenAI-compatible endpoint** for the model; no vendor SDK lock-in.
- Python ≥ 3.10, minimal dependencies, typed, small modules. Ask before adding a dependency.
