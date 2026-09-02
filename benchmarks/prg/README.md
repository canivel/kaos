# PRG — Paraphrase Recall Gap

Measures how often KAOS memory (SQLite FTS5 + porter stemming, no embeddings)
**misses a paraphrased query whose stored lesson exists** — the failure first
recorded in issue #42 ("duplicate processing" did not recall "double charge").
PRG is an instrument, not a mechanism: it publishes the weakness honestly and is
the acceptance gate for any future fix.

Pre-registered in [`preregistration.json`](preregistration.json)
(sha256 `42011e768a44dda2961d34d7b0b4d7c5a3b776830a2f96e01eb8b25045df3430`,
pinned in `run_prg.py`; the runner refuses an edited lock).

## Result — kaos-harness 2.0.2 (2026-09-02)

| Condition | Query | Miss rate (top-5) | p95 |
|---|---|---|---|
| **headline** — paraphrase, CLI default (implicit AND), bm25 | 50 paraphrases | **100 % (50/50)** | 0.04 ms |
| paraphrase, lenient (OR-joined), bm25 | 50 paraphrases | 86 % (43/50) | 0.08 ms |
| paraphrase, AND / OR, weighted rank | 50 paraphrases | 100 % / 86 % | ≤ 0.10 ms |
| **control** — verbatim stored phrase, AND, bm25 | 50 phrases | **0 % (0/50)** | 0.11 ms |
| verbatim, OR / weighted | 50 phrases | 0 % | ≤ 0.19 ms |

**Verdict: ACCEPT** — the instrument is valid (control 0 % miss, 50 pairs) and
the measurement stands. The pre-registration predicted 80–90 % before running; the
CLI-default number is worse than predicted (100 %), because implicit-AND requires
*every* query token to appear, and a real paraphrase rarely shares them all.

What it means: today, a KAOS agent that phrases an incident differently from the
agent that recorded the lesson will not find it. Neuroplasticity's weighted rank
cannot help — it re-ranks matches, and there are none.

## Fixing it — the gate

Any mechanism claiming to close the gap (query-time expansion by the LLM already
in the loop, a trigram tokenizer, a write-time alias column) must pre-register
its own gate against PRG, for example: *paraphrase/and/bm25 miss ≤ 0.20 with the
verbatim control unchanged at 0 % and p95 < 5 ms*. Embeddings are not a candidate;
"no embeddings, no GPU, no cloud" is a constraint, not a preference.

## Reproduce

```bash
uv run python benchmarks/prg/run_prg.py          # ~1 s, in-memory, no network
uv run python -m pytest tests/test_bench_prg.py  # lock integrity + smoke
```

`pairs.json` holds the 50 (stored_phrase, paraphrase_query) pairs, written by hand
from realistic incident vocabulary. Results: `results/kaos_v2.0.2.json`
(per-condition miss lists included). Logged: `kaos experiment list` → `prg-v1`.
