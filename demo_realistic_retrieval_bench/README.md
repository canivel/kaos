# Realistic retrieval benchmark

Non-adversarial counterpart to `demo_neuroplasticity_bench/`.

## What it measures

Top-1 retrieval accuracy on a library of 40 realistic engineering skills
(database, API, queue, storage, CI, etc.) against 15 natural-language
queries phrased the way a real operator would type them ("snapshot the
database before the release").

## What it is NOT

- **Not engineered twin pairs.** Skills share natural vocabulary but have
  distinct purposes. There are no pairs of near-duplicate skills whose
  only difference is a swapped token.
- **Not keyword queries.** Queries are natural prose with stopwords and
  informal phrasing.

## Design note

Five of the 15 queries have a ground truth that reflects a
deployment-specific convention rather than the most lexically similar
skill — e.g. this team does schema changes via dbt (not alembic), drains
failed-payment queues via SQS (not the dead-letter-queue helper), checks
service health on Grafana (not the probe endpoint), ships via rolling
Kubernetes updates (not `docker push`), and starts new feature work by
rebasing an existing branch (not creating a fresh one).

BM25 alone cannot infer these preferences. Plasticity learns them from
reward feedback.

## Reproducing

```bash
uv run python demo_realistic_retrieval_bench/run.py
```

The script writes `results.json` and `results.md` with the run's numbers.

## Latest measured result

| Metric | bm25 | weighted | gain |
|---|---:|---:|---:|
| Final top-1 accuracy | 73.3% | 86.7% | +13.3pp (+18.2%) |

The weighted ranker overtakes BM25 around episode 60 and sustains the
lead. Exact numbers live in [results.json](results.json).
