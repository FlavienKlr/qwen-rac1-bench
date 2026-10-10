# qwen-rac1-bench

**Status: work in progress — no results yet.**

A benchmark harness to measure whether a locally run, open-weight model (Qwen3.8-27B to start with) can do **matching decompilation** on a real PS2 project: [`OpenRAC/rac1-decomp`](https://github.com/OpenRAC/rac1-decomp), the decompilation of *Ratchet & Clank* (2002, PAL).

Matching decompilation means writing C that the original compiler turns back into the exact bytes of the retail executable. A strict, automatic judge decides what counts, which makes it a clean measure of a model's reverse-engineering ability.

## What it measures

- Exact-match rate by function size band (small functions to 4 KB).
- Tokens and time per matched function and per matched byte.
- How the chance of a match evolves run after run.
- Whether the model tries to get around the judge: forbidden constructs (inline assembly, register pins, barriers…) or, in an optional shell mode, changes to the build tooling.

## How it works

The harness does not reimplement the project's tooling. It drives it:

- **Judge**: rac1-decomp's own `tools/try_func.py`. For level code, a candidate is linked at its retail address, and every byte and relocation is compared.
- **Agent protocols**: the project's own `docs/QUEUE.md` (small functions) and `docs/LONG_FUNCTIONS.md` (long functions), with the same run budgets the project uses.
- **Function selection**: the project's `tools/wave.py plan`, which skips fragments, known walls and variants that can be cloned for free.
- **Model**: any OpenAI-compatible endpoint (e.g. a local `llama.cpp` server). The model only gets mediated tools: write a candidate, run the judge, read its own files, take notes, stop. It has no shell by default.

Every attempt is logged, and every exact match is re-checked in a clean checkout and screened for forbidden constructs before it counts.

## What this repository does NOT contain

**No game data. Ever.** No disc image, no executable, no disassembly (`asm/`, `.s`), no extracted assets, and no raw run logs (they contain disassembly of the retail binary). To run the benchmark you need **your own legally owned copy** of the game, dumped yourself, exactly as rac1-decomp requires (see its `LEGAL.md`).

Published results are limited to function names and sizes, aggregate metrics, and the matched C.

## Layout

To come as the harness is written.

## Credits

- [rac1-decomp](https://github.com/OpenRAC/rac1-decomp) and its contributors: the judge, the protocols and the tooling this harness drives.

## License

MIT, for the code in this repository. See [LICENSE](LICENSE).
