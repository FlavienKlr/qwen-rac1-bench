# Preregistration

Committed to the public repository **before** the first run on the real
pool. The commit hash is cited in the write-up: it shows the thresholds were
not chosen after seeing the results.

Date: 2026-10-11. Harness: this repository at `06c6e8b3396f813220882f587a208950b5f092a0`. The commit that adds this file is the preregistration commit cited in the write-up.

## Question

Can Qwen3.8-27B (base), quantised to Q6_K and served locally, do the job of
a matching worker on rac1-decomp, on its own, under the project's protocol,
and at what cost compared with Haiku 5.5 on the same functions?

## Fixed conditions

- Pool: `functions/haiku55-2026-10-07.txt`, repository at commit 777a7b13.
- Protocol: `docs/WORKER.md`, `tools/wave.py`'s prompt, a budget of 15 `try_func` runs.
- Model: `unsloth/Qwen3.8-27B-GGUF`, file `Qwen3.8-27B-UD-Q6_K.gguf` (Unsloth Dynamic Q6_K), sha256 `c9c206812fbe4ac7b76a729e25928b63f2ae89d37f69da7a71c20aec763cd436`, loaded from a pinned local path.
- llama.cpp build 10517 / dc72703fc, Windows, RTX 5090 32 GB.
- Context 131072, KV q8_0/q8_0, flash-attn, embedded MTP on (n=2, q8_0 draft KV), checked in the load log of each arm.
- Sampling: temperature 0.7, top_p 0.95, top_k 20, min_p 0; thinking on; reasoning not carried across turns.
- Three passes: seeds 1000, 2000, 3000.
- Limits: 150 turns, 3 h per function, 32768 tokens per response.
- Environment: Debian 13.7 VM (4 vCPU, 15 GB), Docker 26.1.5, Python 3.13.5;
  upstream tree at 777a7b13 with no later history (tracked-tree hash
  `ee394abc7ee869ad494ea9299e824d5fe5c8176c6bbe5497a14e4f503ed35441`),
  build image `sha256:954ef1abfd5a9a365200851d84463a4313d12d6755f48b190a00cd784d2ec98f`,
  toolchains, m2c, asm-differ and Lombyte (with its progress report) pinned
  to 2026-10-07; level overlays dumped from the PAL v2.00 disc image.
  Executable build 1068/1069 exact at that commit (one upstream near-miss).
  Every run starts from the same VM snapshot; outbound network blocked on the
  hypervisor during runs.
- Dry run (outside the pool, before this file): `func_L00_001EB194`, used only
  to validate the harness; it is not part of any result.

## What counts as a match

A candidate that is EXACT when `try_func` is rerun in a restored VM, breaks
none of the rules `verify.py` checks, and passes the full build.

A correctly identified join, named in `NOTES.md`, counts in a separate
"join identified" column. That is how 4 of Haiku's 6 EXACT were obtained.

## Fragments

Some functions are pieces the catalogue split apart; no worker can match them
alone, and joins are never added during runs. A worker may stop a function
by naming it a fragment; the diagnosis is checked by hand afterwards.
Confirmed fragments are a category of their own: match rates are published
both with them and without them in the denominator, and whether Qwen spots
them is reported separately.

## Floor

m2c's sketch, compiled as emitted through the same judge (`run_wave.py
baseline`), is run once and reported next to Qwen and Haiku.

## Main comparison

Function by function, on the functions whose Haiku outcome is known: Haiku
matched 6 of them (joins included) and missed 8.

## Hypotheses and thresholds

| | Hypothesis | Holds if |
|---|---|---|
| H1 capable | Qwen produces at least one real match | median over 3 passes ≥ 1 valid match |
| H1' comparable | Qwen roughly keeps up with Haiku | median over 3 passes ≥ 4 successful functions (valid match or join identified), against Haiku's 6 |
| H2 cost | Qwen costs no more tokens than Haiku | input tokens per valid match ≤ 514K (Haiku on previously tried functions, its most expensive case) |
| H3 autonomy | it runs on its own to the end | no human intervention during runs (enforced: any manual stop voids the pass) **and** ≥ 80% of workers end cleanly with a verdict line, rather than looping, filling the context or being truncated |
| H4 integrity | it does not cheat its way to EXACT | no threshold: the number of functions "EXACT only by breaking a rule" is published, whatever it is |
| H5 long-term goal | fully autonomous decompilation | no threshold: the share of functions taken to a valid match with no help at all (no human-added join, no restart) is published. This is the goal, not a success criterion of this study: Haiku is at 2 of 14 without a join |

## Comparisons outside this study

Only Haiku 5.5 has run on this exact pool. Published figures for Sonnet
5.5, Opus 5.5 and Haiku 4.5 cover other functions: they are cited as
context, never as a direct comparison. Other models, local or API, can be
replayed on the same pool in a follow-up with a new preset and the same
harness.

## Optional arm (not part of H1 to H5)

huihui-ai/Huihui-Qwen3.8-27B-abliterated, `Huihui-Qwen3.8-27B-abliterated-Q6_K.gguf`
(sha256 `a5c159519d7bdba523578977d649dbfc48f2e47277ec77edd77670003b5b2492`), same
conditions and seeds, reported separately if run. Its quantisation method
differs from the base arm's (plain Q6_K vs Unsloth Dynamic Q6_K).

## Published whatever happens

The `report.py` tables for every pass, failures included, the ledger and
the manifests, and the limitations listed in `ARTICLE.md`. A null result is
a result.
