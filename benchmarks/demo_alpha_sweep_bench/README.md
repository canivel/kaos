# Alpha sensitivity sweep

Characterises how the plasticity weight (`usage_multiplier`, aka **alpha**)
affects retrieval accuracy on the realistic benchmark.

## What alpha controls

`weighted_score = max(bm25, floor) × (0.5 + alpha × wilson_lower_bound) × recency`

- **alpha = 0** — plasticity is disabled; weighted ranking reduces to a
  BM25-equivalent baseline (modulo the fixed 0.5 offset and the recency
  decay factor).
- **alpha = 3.0** — the shipped default. Success-weighted usage can
  swing a skill's score by up to 3.5× relative to a never-used one.
- **Higher alpha** — outcomes dominate over lexical relevance. Good once
  plasticity is well-trained, potentially bad during cold-start.

## What it measures

Final top-1 accuracy after 120 training episodes against the 15
natural-language queries and 40-skill library from
`demo_realistic_retrieval_bench/`, across 8 alpha values.

## Reproducing

```bash
uv run python demo_alpha_sweep_bench/run.py
```

## Latest measured result

| alpha | top-1 accuracy |
|---:|---:|
| 0.0 | 73.3% |
| 0.5 | 86.7% |
| 1.0 | 80.0% |
| 2.0 | 93.3% |
| **3.0 (default)** | **93.3%** |
| 5.0 | 93.3% |
| 8.0 | 93.3% |
| 12.0 | 93.3% |

The default **alpha = 3.0** sits on a broad plateau covering the entire
2.0 - 12.0 range, giving +20pp over the alpha=0 baseline. The sensitivity
curve is flat-topped rather than sharp, which means the default is not a
knife-edge choice — the plasticity signal is robust to moderate
mis-tuning.

Raw numbers: [results.json](results.json).
