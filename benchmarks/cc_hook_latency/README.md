# cc-hook-latency — pre-registered latency probe for the Claude Code hooks

Gate **G4.1b** of `docs/roadmap/v2.1-stars.md`. Measures the cold-process cost of
`kaos-hook` (the entrypoint the Claude Code plugin calls) against a seeded
10,000-agent / 50,000-memory database.

```
uv run python benchmarks/cc_hook_latency/run_cc_hook_latency.py
```

The runner refuses to run unless `preregistration.json` hashes to a known lock.

## Results (2026-09-02, WSL2, Python 3.12, db on /tmp)

| Arm | p50 | p95 | Gate | |
|---|---:|---:|---|---|
| `session-start` (journal + weighted recall, 5 hits injected) | 219 ms | 241 ms | ≤ 400 ms | ✓ |
| `prompt` (journal + recall on the prompt text, 3 hits) | 250 ms | 275 ms | ≤ 200 ms | ✗ |
| never blocks (50/50 exit 0, 50/50 injected a `<kaos-memory>` block) | | | | ✓ |

**Verdict: `REJECT:prompt`** (lock `42f4a278…`, logged as experiment `cc-hook-latency-v2`).
Per the pre-registered rule, the `UserPromptSubmit` hook ships **off by default**: it
still journals every prompt (cheap, async-safe) but injects memory only after
`kaos connect claude-code --prompt-inject` or `KAOS_HOOK_PROMPT_INJECT=1`.
Session-start injection is on.

Where the time goes: bare Python start-up is ~54 ms here; the rest is importing
`kaos.core` (blobs → zstandard, checkpoints, events) and the weighted-rank path
(`kaos.dream.signals`, `memory_hits` bookkeeping). `click`, `rich`, `yaml` and
`ulid-py` are no longer on this path — `ulid-py` alone cost 216 ms and was removed
from the package entirely (`kaos/_ids.py`). The next step if the prompt arm should
ever pass: a socket-mode daemon, or an import-free raw-sqlite recall path.

## v1 result, kept

`results/kaos_v2.1.0_v1-instrument-defect.json` — lock `2eff0e07…`. It REJECTed on
G3 because the seed corpus contained nothing the session-start hint
(`payments-service`) could match, so no run could inject regardless of the hook.
That is an instrument defect; v2 adds project words to 1 % of seeded memories and
changes nothing else. The comparison also exposed a real hook improvement:
hyphenated project names are now split into words before recall.
