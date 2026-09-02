# LongMemEval on KAOS memory — split-reported

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (Wu et al., MIT) is the
benchmark memory systems cite. This runs its **S** split against KAOS's memory as
it ships — SQLite FTS5 + porter stemming + BM25, **no embeddings, no LLM at
retrieval** — and reports recall@5 at session level, split by whether the
question shares vocabulary with its evidence.

Pre-registered before the first run in [`preregistration.json`](preregistration.json)
(sha256 `fc191bfb93454f3bec6b7e8ff65fddc946b2cef077a1424dc46cc7cc162070d8`, pinned in
`run_longmemeval.py`). Dataset hashes, the split function, the query sanitizer,
the gates and the expected range are all in the lock.

## Result — kaos-harness 2.0.2 (2026-09-02), `longmemeval_s_cleaned.json`

**Split table (the pre-registered headline):**

| Bucket (mechanical 3-gram split) | n | recall@5 |
|---|---|---|
| verbatim — question shares ≥ 1 content 3-gram with an evidence session | 211 | **0.991** |
| paraphrase — no shared 3-gram | 289 | 0.965 |

**Per question type:**

| question_type | n | recall@5 |
|---|---|---|
| single-session-user | 70 | 1.000 |
| single-session-assistant | 56 | 1.000 |
| knowledge-update | 78 | 1.000 |
| multi-session | 133 | 0.992 |
| temporal-reasoning | 133 | 0.955 |
| single-session-preference | 30 | 0.833 |

**Aggregate — not comparable to embedding-based systems: 0.976** (12 misses of
500) · p95 search latency **0.9 ms** (in-memory SQLite) · control on the oracle
file (evidence sessions only): 1.000.

**Verdict: ACCEPT** — verbatim recall@5 0.991 ≥ 0.70 and p95 < 25 ms. Both gates
were set before running; the pre-registration expected verbatim 0.65–0.85 and
paraphrase 0.10–0.35. The result beat the expectation, and that is exactly why the
next section exists.

## Read this before quoting the number

1. **The S haystack is small.** 38–62 sessions per question (median 48). Session-level
   recall@5 over 48 candidates is a much easier task than answering the question,
   and easier than the **M** split (500 sessions per question, 2.7 GB), which was
   **not run** — no claim is made about M.
2. **Evidence sessions share entities with the question.** Names, products, places.
   OR-joined BM25 over content tokens finds them even when no 3-gram is shared; that
   is why the "paraphrase" bucket still scores 0.965. The mechanical split measures
   phrase overlap, not the kind of vocabulary gap that PRG measures with short
   incident lessons — where the same memory misses 100 % (see `../prg/`). Both
   numbers are true; they describe different regimes.
3. **The query is OR-joined content tokens**, more lenient than today's CLI default
   (implicit AND). It is stated in the lock. The CLI would do worse on the same data.
4. **Session-level, not answer-level.** LongMemEval's headline task is answer
   accuracy with a reader model; this run measures only whether the right session is
   in the top 5. The repository lists `flat-bm25` among its own baseline retrievers;
   expect any BM25-class retriever to be strong on S at this granularity.
5. Misses cluster in *single-session-preference* (5/30) and *temporal-reasoning*
   (6/133) — questions whose wording carries little content overlap with the evidence.

What the result does license: KAOS's embedding-free memory is not the retrieval
bottleneck at S scale, and it does it in under a millisecond per query. What it
does not license: "beats MemPalace" or any other aggregate comparison.

## Reproduce

```bash
uv run python benchmarks/longmemeval/download.py        # 277 MB + 15 MB from Hugging Face, sha256-verified
uv run python benchmarks/longmemeval/run_longmemeval.py  # ~20 s; per-question labels + hits in results/
```

Per-question bucket labels and hit flags are in `results/kaos_v2.0.2.json` so anyone
can re-split with a different rule. Logged: `kaos experiment list` →
`longmemeval-s-split-v1`.
