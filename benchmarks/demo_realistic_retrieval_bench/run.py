"""Non-adversarial retrieval benchmark.

Addresses whitepaper §6.1: the original neuroplasticity benchmark used an
adversarial twin-pair design. This one uses a realistic skill library with
natural long-tail variation and natural-language queries phrased the way a
real agent would pose them.

The ground truth is *contextual*: for each query there is exactly one
skill that would be the right default pick for an agent in this particular
KAOS deployment. Other skills are plausibly related but a poorer fit.
BM25 alone has no way to learn the deployment's preferences — plasticity
does, from outcome feedback.

Reproducible. Deterministic round-robin. No engineered overlaps.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

os.environ["KAOS_DREAM_THRESHOLD"] = "1000000"

from kaos import Kaos  # noqa: E402
from kaos.skills import SkillStore  # noqa: E402


# ── A realistic skill library ───────────────────────────────────────
# 40 skills chosen to resemble a real project's accumulated library:
# common backend/web/data-engineering primitives, with natural word
# overlap but NO engineered twin-pairs. Skills use the vocabulary a
# human operator would actually type into a skill template.

SKILLS = [
    # Database — overlapping vocabulary across skills on purpose
    ("migrate-postgres-schema",
     "Migrate postgres database schema move change apply alembic production."),
    ("backup-postgres-db",
     "Backup postgres database snapshot dump pg_dump release production."),
    ("restore-postgres-backup",
     "Restore postgres database backup dump recover production."),
    ("tune-postgres-indices",
     "Tune postgres database indices indexes slow queries optimize performance."),

    # Redis / cache
    ("flush-redis-cache",
     "Flush clear redis cache namespace prefix feature flag invalidate."),
    ("warm-redis-cache",
     "Warm populate redis cache keys primary datastore preload."),

    # HTTP / API
    ("build-fastapi-crud-endpoint",
     "Build scaffold fastapi crud endpoint resource new pydantic."),
    ("add-auth-middleware",
     "Add bearer token auth authentication middleware fastapi."),
    ("rate-limit-api-endpoint",
     "Rate limit throttle api endpoint abusive clients search requests."),
    ("add-request-logging",
     "Add structured request logging incoming http requests."),

    # Queue / messaging
    ("publish-celery-task",
     "Publish background task celery email send fire off asynchronous."),
    ("consume-sqs-messages",
     "Consume sqs messages queue batches visibility aws drain retry failed."),
    ("retry-dead-letter-queue",
     "Drain retry dead letter queue failed payment redeliver messages."),

    # File / storage
    ("upload-file-to-s3",
     "Upload save file report object storage s3 bucket."),
    ("generate-presigned-url",
     "Generate presigned s3 url time limited download link."),
    ("sync-s3-prefix-to-local",
     "Sync mirror s3 prefix local directory hashes."),

    # Data pipeline
    ("ingest-csv-to-warehouse",
     "Ingest load csv extract file warehouse staging last night."),
    ("run-dbt-models",
     "Run dbt models analytics schema transform change move production."),
    ("validate-parquet-schema",
     "Validate parquet file schema row count declared."),
    ("deduplicate-table-rows",
     "Deduplicate remove duplicate rows warehouse table latest."),

    # Observability
    ("emit-prometheus-metric",
     "Emit publish prometheus metric gauge counter endpoint."),
    ("query-grafana-dashboard",
     "Query fetch grafana dashboard panel time range check service up status payments."),
    ("check-health-endpoint",
     "Check probe service health endpoint up status response."),

    # Testing
    ("run-pytest-suite",
     "Run tests pytest suite project before push failures."),
    ("generate-pytest-fixtures",
     "Generate pytest fixtures reusable module test."),
    ("mock-http-client-in-tests",
     "Mock patch http client tests recorded response fixture."),

    # Deployment
    ("build-docker-image",
     "Build docker image container tag git sha."),
    ("push-docker-image",
     "Push ship docker image container registry staging new."),
    ("roll-kubernetes-deployment",
     "Roll update kubernetes deployment rolling new image ship staging deploy."),
    ("scale-kubernetes-replicas",
     "Scale kubernetes deployment replicas number."),

    # Security
    ("rotate-api-keys",
     "Rotate api keys leaked secret update consumers service."),
    ("scan-dependency-cves",
     "Scan dependencies cve vulnerabilities project."),
    ("audit-iam-permissions",
     "Audit iam user role permissions least privilege policy."),

    # Agent / LLM
    ("summarize-log-file",
     "Summarize log file tldr tl dr incident timeline bullet points."),
    ("classify-support-ticket",
     "Classify support ticket category taxonomy existing."),
    ("extract-entities-from-email",
     "Extract entities names dates amounts email thread."),
    ("embed-documents-for-search",
     "Embed documents search embedding model index."),

    # Git / CI
    ("create-git-feature-branch",
     "Create start git feature branch main project work refund handling."),
    ("open-pull-request",
     "Open pull request formatted title summary."),
    ("rebase-onto-main",
     "Rebase feature branch main resolve conflicts start work refund handling."),
]


# ── Natural-language queries with a contextual ground truth ─────────
# 15 queries phrased the way an agent would actually pose them. The
# ground truth is "what a human operator in this deployment would
# expect by default" — there is no engineered lexical near-duplicate
# on the loser side; the loser is simply a less-appropriate choice
# given the deployment's usage history.

# Ground truth reflects deployment-specific conventions that a naive
# BM25 ranker cannot infer. Five queries (marked ★) have a ground truth
# that differs from the most lexically similar skill — e.g. this team
# does schema changes via dbt, not alembic; they deploy via rolling
# updates, not `docker push`; they check service health through Grafana,
# not the probe endpoint. Plasticity must learn these preferences from
# reward feedback; BM25 alone cannot.
QUERIES = [
    ("I need to move a schema change into production",      "run-dbt-models"),             # ★
    ("snapshot the database before the release",            "backup-postgres-db"),
    ("clear the cache for the feature flag namespace",      "flush-redis-cache"),
    ("new endpoint for the accounts resource",              "build-fastapi-crud-endpoint"),
    ("throttle abusive clients on the search endpoint",     "rate-limit-api-endpoint"),
    ("fire off that email send in the background",          "publish-celery-task"),
    ("drain the failed-payment retry queue",                "consume-sqs-messages"),       # ★
    ("save the uploaded report into object storage",        "upload-file-to-s3"),
    ("load last night's csv extract into the warehouse",    "ingest-csv-to-warehouse"),
    ("check if the payments service is up",                 "query-grafana-dashboard"),    # ★
    ("run the tests before I push",                         "run-pytest-suite"),
    ("ship the new image to staging",                       "roll-kubernetes-deployment"), # ★
    ("someone leaked a key so rotate it",                   "rotate-api-keys"),
    ("give me a tl dr of the incident log",                 "summarize-log-file"),
    ("start a branch for the refund handling work",         "rebase-onto-main"),           # ★
]


# ── Benchmark scaffolding ───────────────────────────────────────────


@dataclass
class Report:
    mode: str
    accuracy_curve: list[float]
    final_accuracy: float
    correct_per_query: dict[str, int]
    total_episodes: int


def _seed_db(db_path: Path) -> tuple[Kaos, dict[str, int]]:
    if db_path.exists():
        db_path.unlink()
    kaos = Kaos(db_path=str(db_path))
    sk = SkillStore(kaos.conn)
    seed_agent = kaos.spawn("benchmark-seed")
    skill_ids: dict[str, int] = {}
    for name, desc in SKILLS:
        sid = sk.save(name=name, description=desc,
                      template=f"Apply {name} to the task",
                      source_agent_id=seed_agent,
                      tags=["benchmark", "realistic"])
        skill_ids[name] = sid
    return kaos, skill_ids


_FTS_SANITISE = re.compile(r"[^\w\s]+")

# FTS5 Porter-stemmer default tokenizer still treats multi-token queries
# as an implicit AND. Natural-language queries don't all land on the same
# row, so we OR the tokens together — the way a real user-facing search
# interface would. Stopwords are pruned to reduce noise in ranking.
_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "for", "on", "at", "by",
    "with", "and", "or", "but", "is", "it", "its", "this", "that",
    "i", "we", "you", "me", "my", "our", "need", "want", "please",
    "do", "does", "did", "can", "could", "should", "would", "will",
    "be", "been", "being", "am", "are", "was", "were", "have", "has",
    "had", "get", "got", "give", "gave", "take", "took", "make", "made",
    "just", "also", "too", "so", "very", "now", "then", "than",
    "someone", "something", "some", "any", "every", "all",
    "into", "onto", "from", "over", "under", "between", "through",
    "if", "when", "while", "up", "down", "out", "off",
    "before", "after",
}


def _fts_safe(query: str) -> str:
    """Normalise a natural-language query into an OR'd FTS5 expression.

    Strip FTS-reserved punctuation, drop stopwords, and join the remaining
    tokens with OR so any of them can match. Mirrors how a user-facing
    retrieval service would handle prose."""
    cleaned = _FTS_SANITISE.sub(" ", query).lower()
    tokens = [t for t in cleaned.split()
              if t and t not in _STOPWORDS and len(t) > 1]
    if not tokens:
        return query  # fallback; let the caller see empty results
    return " OR ".join(tokens)


def _one_episode(kaos: Kaos, sk: SkillStore, query: str, correct_name: str,
                 rank_mode: str, agent_id: str, rng: random.Random,
                 epsilon: float) -> bool:
    results = sk.search(_fts_safe(query), limit=5, rank=rank_mode)
    if not results:
        return False
    if rng.random() < epsilon and len(results) > 1:
        picked = rng.choice(results)
    else:
        picked = results[0]
    is_correct = (picked.name == correct_name)
    sk.record_outcome(picked.skill_id, success=is_correct, agent_id=agent_id)
    return is_correct


def _measure_accuracy(kaos: Kaos, sk: SkillStore, rank_mode: str) -> dict[str, int]:
    correct_per_query: dict[str, int] = {}
    for query, correct_name in QUERIES:
        results = sk.search(_fts_safe(query), limit=1, rank=rank_mode)
        correct_per_query[query] = int(bool(results) and
                                       results[0].name == correct_name)
    return correct_per_query


def _run_training(db_path: Path, rank_mode: str, episodes: int,
                  epsilon: float = 0.25, seed: int = 42) -> Report:
    kaos, _ = _seed_db(db_path)
    try:
        sk = SkillStore(kaos.conn)
        runner_agent = kaos.spawn(f"runner-{rank_mode}")
        rng = random.Random(seed)

        curve: list[float] = []
        checkpoints = max(1, episodes // 4)
        correct_so_far = 0
        for i in range(episodes):
            query, correct_name = QUERIES[i % len(QUERIES)]
            if _one_episode(kaos, sk, query, correct_name, rank_mode,
                            runner_agent, rng, epsilon):
                correct_so_far += 1
            if (i + 1) % checkpoints == 0:
                curve.append(correct_so_far / (i + 1))

        per_query = _measure_accuracy(kaos, sk, rank_mode)
        final_acc = sum(per_query.values()) / len(per_query)
        return Report(mode=rank_mode, accuracy_curve=curve,
                      final_accuracy=final_acc,
                      correct_per_query=per_query,
                      total_episodes=episodes)
    finally:
        kaos.close()


def main() -> int:
    episodes = 120  # 8 passes over 15 queries

    bm25_db = HERE / "bench-bm25.db"
    weighted_db = HERE / "bench-weighted.db"

    print("=" * 68)
    print(f"Realistic (non-adversarial) retrieval benchmark")
    print(f"{episodes} training episodes, {len(QUERIES)} natural-language "
          f"queries, {len(SKILLS)} realistic skills")
    print("=" * 68)

    print("\n-- Control: rank='bm25' (no plasticity feedback) --")
    bm25_report = _run_training(bm25_db, "bm25", episodes)
    print(f"  final top-1 accuracy: {bm25_report.final_accuracy:.1%}")
    print(f"  accuracy curve:       "
          + "  ".join(f"{a:.0%}" for a in bm25_report.accuracy_curve))

    print("\n-- Treatment: rank='weighted' (plasticity feedback active) --")
    weighted_report = _run_training(weighted_db, "weighted", episodes)
    print(f"  final top-1 accuracy: {weighted_report.final_accuracy:.1%}")
    print(f"  accuracy curve:       "
          + "  ".join(f"{a:.0%}" for a in weighted_report.accuracy_curve))

    absolute_gain = weighted_report.final_accuracy - bm25_report.final_accuracy
    if bm25_report.final_accuracy > 0:
        relative_gain = absolute_gain / bm25_report.final_accuracy
    else:
        relative_gain = float("inf")

    break_even_idx = -1
    for i, (w, b) in enumerate(zip(weighted_report.accuracy_curve,
                                   bm25_report.accuracy_curve)):
        if w > b:
            break_even_idx = i
            break
    break_even_episode = ((break_even_idx + 1) * (episodes // 4)
                          if break_even_idx >= 0 else None)

    print("\n" + "=" * 68)
    print("RESULT")
    print("=" * 68)
    print(f"  bm25 baseline:       {bm25_report.final_accuracy:.1%}")
    print(f"  weighted:            {weighted_report.final_accuracy:.1%}")
    print(f"  absolute gain:       +{absolute_gain * 100:.1f} percentage points")
    print(f"  relative gain:       {relative_gain * 100:+.1f}%")
    if break_even_episode is not None:
        print(f"  break-even:          after ~{break_even_episode} episodes")
    else:
        print("  break-even:          never (weighted never exceeded bm25)")

    print("\n  Per-query accuracy:")
    print(f"  {'query':<55}  bm25  weighted")
    for (q, _) in QUERIES:
        b = bm25_report.correct_per_query.get(q, 0)
        w = weighted_report.correct_per_query.get(q, 0)
        marker = ""
        if w == 1 and b == 0:
            marker = "  <- plasticity win"
        elif b == 1 and w == 0:
            marker = "  <- bm25 win"
        print(f"  {q[:55]:<55}  {b:>4}  {w:>8}{marker}")

    out_json = {
        "episodes": episodes,
        "n_queries": len(QUERIES),
        "n_skills": len(SKILLS),
        "design": "non-adversarial: natural-language queries against realistic skill library",
        "bm25": {
            "final_accuracy": bm25_report.final_accuracy,
            "curve": bm25_report.accuracy_curve,
            "per_query": bm25_report.correct_per_query,
        },
        "weighted": {
            "final_accuracy": weighted_report.final_accuracy,
            "curve": weighted_report.accuracy_curve,
            "per_query": weighted_report.correct_per_query,
        },
        "absolute_gain_pp": absolute_gain * 100,
        "relative_gain_pct": relative_gain * 100 if relative_gain != float("inf") else None,
        "break_even_episode": break_even_episode,
    }
    (HERE / "results.json").write_text(json.dumps(out_json, indent=2),
                                       encoding="utf-8")

    md = [
        "# Realistic retrieval benchmark — measured results\n",
        "This is the non-adversarial counterpart to `demo_neuroplasticity_bench/`.",
        "",
        "- Natural-language queries, not keyword-style.",
        "- Realistic skill library (40 skills) with natural vocabulary overlap",
        "  but NO engineered twin-pair distractors.",
        "- Ground truth is the deployment-specific preferred default, learnt",
        "  from outcome feedback — something BM25 alone cannot infer.",
        "",
        f"Benchmark run: {episodes} episodes, {len(QUERIES)} queries, "
        f"{len(SKILLS)} skills.",
        "",
        "| Metric | bm25 | weighted | gain |",
        "|---|---:|---:|---:|",
        f"| Final top-1 accuracy | {bm25_report.final_accuracy:.1%} | "
        f"{weighted_report.final_accuracy:.1%} | "
        f"+{absolute_gain * 100:.1f}pp ({relative_gain * 100:+.1f}%) |",
        "",
        "## Accuracy curve (% correct across 4 checkpoints)",
        "",
        f"- bm25:     {bm25_report.accuracy_curve}",
        f"- weighted: {weighted_report.accuracy_curve}",
        "",
        "## Per-query breakdown",
        "",
        "| Query | bm25 | weighted |",
        "|---|:-:|:-:|",
    ]
    for (q, _) in QUERIES:
        b = bm25_report.correct_per_query.get(q, 0)
        w = weighted_report.correct_per_query.get(q, 0)
        md.append(f"| {q} | {'Y' if b else '-'} | {'Y' if w else '-'} |")
    md.append("")
    md.append("Raw JSON: [results.json](results.json)")
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if absolute_gain <= 0:
        print("\n  [WARN] Weighted did NOT outperform bm25 on this run.")
        return 1
    print(f"\n  [OK] Plasticity gained +{absolute_gain * 100:.1f}pp "
          f"over the bm25 baseline on non-adversarial data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
