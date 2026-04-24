"""Alpha (usage_multiplier) sensitivity sweep.

Addresses whitepaper §6.1: we report a single default for the plasticity
weight (``usage_multiplier=3.0``) without characterising its effect. This
benchmark runs the same non-adversarial retrieval workload at eight
different alpha values and reports how accuracy varies.

Low alpha = weighted ranking behaves like BM25 (no plasticity influence).
High alpha = outcome history dominates (good when confident, bad when
under-trained). We expect a plateau in the mid-range.
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
from kaos.skills import SkillStore, Skill  # noqa: E402
from kaos.dream.signals import weighted_score  # noqa: E402

# Reuse the realistic library & queries from the non-adversarial bench.
from demo_realistic_retrieval_bench.run import SKILLS, QUERIES  # noqa: E402


_FTS_SANITISE = re.compile(r"[^\w\s]+")
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
    cleaned = _FTS_SANITISE.sub(" ", query).lower()
    tokens = [t for t in cleaned.split()
              if t and t not in _STOPWORDS and len(t) > 1]
    if not tokens:
        return query
    return " OR ".join(tokens)


def _search_weighted_alpha(conn, query: str, *, alpha: float,
                           limit: int = 5) -> list[Skill]:
    """Same as SkillStore.search(rank='weighted') but with an explicit alpha."""
    fetch = limit * 4
    rows = conn.execute(
        """
        SELECT s.skill_id, s.name, s.description, s.template, s.tags,
               s.source_agent_id, s.use_count, s.success_count,
               s.created_at, s.updated_at,
               bm25(agent_skills_fts) AS bm25_raw
        FROM agent_skills_fts f
        JOIN agent_skills s ON s.skill_id = f.rowid
        WHERE agent_skills_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (_fts_safe(query), fetch),
    ).fetchall()
    if not rows:
        return []
    skills = [Skill.from_row(r) for r in rows]
    bm25_by_id = {r["skill_id"]: -float(r["bm25_raw"] or 0.0) for r in rows}
    sid_last = {}
    ids = [s.skill_id for s in skills]
    if ids:
        placeholders = ",".join("?" * len(ids))
        for r in conn.execute(
            f"SELECT skill_id, MAX(used_at) FROM skill_uses "
            f"WHERE skill_id IN ({placeholders}) GROUP BY skill_id",
            ids,
        ):
            sid_last[r[0]] = r[1]

    def score(s: Skill) -> float:
        return weighted_score(
            bm25_score=bm25_by_id.get(s.skill_id, 1.0),
            uses=s.use_count,
            successes=s.success_count,
            last_used_at=sid_last.get(s.skill_id),
            usage_multiplier=alpha,
        )

    skills.sort(key=score, reverse=True)
    return skills[:limit]


@dataclass
class Report:
    alpha: float
    final_accuracy: float


def _seed_db(db_path: Path) -> Kaos:
    if db_path.exists():
        db_path.unlink()
    kaos = Kaos(db_path=str(db_path))
    sk = SkillStore(kaos.conn)
    seed_agent = kaos.spawn("bench-seed")
    for name, desc in SKILLS:
        sk.save(name=name, description=desc,
                template=f"Apply {name} to the task",
                source_agent_id=seed_agent,
                tags=["benchmark", "alpha-sweep"])
    return kaos


def _one_episode(conn, sk: SkillStore, query: str, correct_name: str,
                 *, alpha: float, agent_id: str, rng: random.Random,
                 epsilon: float) -> bool:
    results = _search_weighted_alpha(conn, query, alpha=alpha, limit=5)
    if not results:
        return False
    if rng.random() < epsilon and len(results) > 1:
        picked = rng.choice(results)
    else:
        picked = results[0]
    ok = (picked.name == correct_name)
    sk.record_outcome(picked.skill_id, success=ok, agent_id=agent_id)
    return ok


def _run_at_alpha(alpha: float, episodes: int, seed: int = 42) -> Report:
    db_path = HERE / f"bench-alpha-{alpha:g}.db"
    kaos = _seed_db(db_path)
    try:
        sk = SkillStore(kaos.conn)
        runner = kaos.spawn(f"runner-a{alpha:g}")
        rng = random.Random(seed)
        epsilon = 0.25
        for i in range(episodes):
            query, correct = QUERIES[i % len(QUERIES)]
            _one_episode(kaos.conn, sk, query, correct,
                         alpha=alpha, agent_id=runner, rng=rng,
                         epsilon=epsilon)
        # Final deterministic measurement
        correct_total = 0
        for query, correct in QUERIES:
            results = _search_weighted_alpha(kaos.conn, query,
                                             alpha=alpha, limit=1)
            if results and results[0].name == correct:
                correct_total += 1
        return Report(alpha=alpha,
                      final_accuracy=correct_total / len(QUERIES))
    finally:
        kaos.close()


def main() -> int:
    episodes = 120
    # alpha=0.0 reduces weighted to bm25 × recency × 0.5-offset — effectively
    # BM25 only for freshly-seeded skills. alpha=12 is five times the default.
    alphas = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0]

    print("=" * 68)
    print("Alpha sensitivity sweep -- weighted_score(usage_multiplier=alpha)")
    print(f"{episodes} episodes, {len(QUERIES)} queries, {len(SKILLS)} skills")
    print("=" * 68)

    reports: list[Report] = []
    for a in alphas:
        r = _run_at_alpha(a, episodes)
        reports.append(r)
        print(f"  alpha={a:>4.1f}   top-1 accuracy: {r.final_accuracy:.1%}")

    best = max(reports, key=lambda r: r.final_accuracy)
    baseline = next(r for r in reports if r.alpha == 0.0)
    default = next(r for r in reports if r.alpha == 3.0)

    print()
    print(f"  baseline (alpha=0.0):  {baseline.final_accuracy:.1%}")
    print(f"  default  (alpha=3.0):  {default.final_accuracy:.1%}")
    print(f"  best     (alpha={best.alpha:.1f}):  {best.final_accuracy:.1%}")
    if default.final_accuracy >= baseline.final_accuracy:
        print(f"  default improves over baseline by "
              f"+{(default.final_accuracy - baseline.final_accuracy) * 100:.1f}pp")
    else:
        print("  WARNING: default alpha underperforms baseline in this run")

    out = {
        "episodes": episodes,
        "n_queries": len(QUERIES),
        "n_skills": len(SKILLS),
        "alphas": [{"alpha": r.alpha,
                    "final_accuracy": r.final_accuracy} for r in reports],
        "best_alpha": best.alpha,
        "default_alpha": 3.0,
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=2),
                                       encoding="utf-8")

    md = [
        "# Alpha (usage_multiplier) sensitivity sweep\n",
        f"Run: {episodes} episodes, {len(QUERIES)} queries, "
        f"{len(SKILLS)} skills.\n",
        "| alpha | top-1 accuracy |",
        "|---:|---:|",
    ]
    for r in reports:
        marker = ""
        if r.alpha == 3.0:
            marker = " (default)"
        if r is best:
            marker += " **best**"
        md.append(f"| {r.alpha} | {r.final_accuracy:.1%}{marker} |")
    md.append("")
    md.append("Raw JSON: [results.json](results.json)")
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
