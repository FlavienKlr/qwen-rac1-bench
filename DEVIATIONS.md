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
