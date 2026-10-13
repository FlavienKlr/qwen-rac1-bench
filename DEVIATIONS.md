# Deviations from the preregistration

The preregistration (`PREREGISTRATION.md`, commit `a04bf18`) is unchanged.
Every departure from it is listed here, dated, with its reason, and is reported
in the write-up. Results obtained before a deviation are kept and published.

## 1. Recovery from cut or empty responses (2026-10-12)

**What changed.** `harness/worker.py` gained a recovery step. When a response
is cut at the 32768-token output limit, or contains neither a tool call nor
any text, it is discarded and the model receives one fixed instruction to take
its next step with a tool call or give its verdict. At most 3 recoveries per
worker (`--max-recoveries 3`). A response cut because the 131072-token context
is full still ends the worker (`context_exhausted`). Every recovery is
recorded in the transcript and counted in `summary.json` and the report.
Nothing else changed: model, sampling, limits, prompt, tools, budget, pool.

**Why.** In the first pass (`qwen38-base-s1`, run under the preregistered
protocol), 9 of 14 workers ended on a single response that hit the output
limit, almost always one long deliberation before any action; 6 of 14 never
ran `try_func`. The protocol treated a cut response as the end of the worker,
so the pass mostly measured the length of the model's deliberations rather
than its ability to match, which is not what the preregistered hypotheses
ask. Agent harnesses generally recover from a cut response rather than end
the agent, so the original rule also made the comparison with Haiku 5.5
(run inside Claude Code) less fair.

**Consequence.** `qwen38-base-s1` is reported as protocol v1 ("no recovery").
Three new passes run with recovery (protocol v2), seeds 1000, 2000 and 3000,
named `qwen38-base-v2-s1` to `-s3`. The hypotheses are evaluated on v2; v1
is reported next to it. Harness version for v2: the commit adding this file.

## 2. Verifier: allowed symbol aliases with a trailing attribute (2026-10-13)

**What changed.** `harness/verify.py`'s static screen allows file-scope symbol
aliases (`extern int D_x_m __asm__("D_x");`), as the preregistered rules do.
Its pattern required the `;` right after the alias, so the upstream idiom
`extern int D_x_m __asm__("D_x") MACRO_ADDR;` (in `include/common.h`, used in
over a hundred upstream source files at the replay commit) was flagged as
`inline_asm`. The pattern now accepts trailing attributes before the `;`.
Statement-level `asm`/`__asm__` and register pins are still flagged.

**Why.** A bug in the verifier, found while reading `qwen38-base-v2-s1`'s
results: all three candidates of `func_L11_002D3620` were flagged although
their only `__asm__` is this alias idiom. It changes no runs and no
`try_func` verdict, only the rule screen.

**Consequence.** Re-screening every candidate of `qwen38-base-s1` and
`qwen38-base-v2-s1` with the fixed pattern: no candidate breaks a rule in
either pass (before the fix, the three `func_L11_002D3620` candidates were
the only ones flagged; none was EXACT). Verdicts and valid-match counts are
unchanged. Later passes are verified with the fixed `verify.py`.
