# Memory recall misses on vocabulary mismatch — FTS5 is literal, incidents aren't

**Observed (2026-09-01, KAOS 2.0.2, real end-to-end session):** after the payments
double-charge incident, the lesson was saved as memory `payment-retry-idempotency`
("Payment retry double-charge: client timeout != server failure. Fix = Idempotency-Key
header generated once per logical charge, reused across retries.").

A later, genuinely related incident — *"webhook handler processes the same event twice
when the sender retries"* — recalled **nothing**:

```
kaos memory search "duplicate processing retry"   -> []        (no term overlap)
kaos memory search "idempotency retry"            -> hit
kaos memory search "double charge"                -> hit
kaos memory search "timeout retry"                -> hit
```

The downstream agent then solved the task from general knowledge and explicitly flagged
it had received no verified team lesson — the brain had the answer and didn't surface it.

**Why it matters:** cross-incident recall is the core value proposition of the memory
layer, and new incidents rarely reuse the old incident's nouns ("duplicate processing"
vs "double charge"). BM25 weighting (neuroplasticity) can only rerank matches that FTS5
finds at all.

**Possible directions (respecting the no-embeddings constraint):**
- write-time keyword expansion: when saving a memory, have the (already-present) LLM
  emit 5–10 alternate phrasings/synonyms into an indexed `aliases` column;
- query-time expansion: same trick on search, OR-ing expanded terms;
- trigram/porter tokenizers on the FTS index as a cheap partial mitigation;
- measure first, per the falsifiable-eval discipline: a small probe with paraphrased
  queries over real memories, gate = recall@3 uplift with hash-locked kill gates.

Priority: P2 · Type: enhancement · Area: kaos/memory.py, FTS5 schema

Reported by AI agent
