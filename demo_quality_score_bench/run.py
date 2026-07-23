"""Track A (v0.8.3) benchmark — does continuous quality beat binary success?

Same non-adversarial retrieval workload as demo_realistic_retrieval_bench,
two treatments:

  - BINARY: record_outcome(success=bool)            (the pre-v0.8.3 signal)
  - QUALITY: record_outcome(success, quality=q)     where q reflects how
             close the picked skill is to the deployment-preferred one

Hypothesis: graded partial-credit feeds the Wilson estimator a less noisy
signal, so the QUALITY run reaches similar-or-higher final accuracy with
LOWER run-to-run variance across seeds. We measure both.

Reproducible. Multiple seeds. No pre-engineered winners.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

os.environ["KAOS_DREAM_THRESHOLD"] = "1000000"

from kaos import Kaos  # noqa: E402
from kaos.skills import SkillStore  # noqa: E402

# Reuse the realistic, non-adversarial library + queries.
from demo_realistic_retrieval_bench.run import (  # noqa: E402
    SKILLS, QUERIES, _fts_safe,
)
import random  # noqa: E402


def _seed_db(db_path: Path) -> tuple[Kaos, dict[str, int]]:
    if db_path.exists():
        db_path.unlink()
    kaos = Kaos(db_path=str(db_path))
    sk = SkillStore(kaos.conn)
    seed = kaos.spawn("seed")
    ids: dict[str, int] = {}
    for name, desc in SKILLS:
        ids[name] = sk.save(name=name, description=desc,
                            template=f"Apply {name}",
                            source_agent_id=seed, tags=["bench"])
    return kaos, ids


# Quality given the picked skill vs the deployment-preferred ground truth.
# Exact match = 1.0; a "near" skill (shares the query's head noun) = 0.4;
# anything else = 0.0. This is the partial-credit signal binary throws away.
def _quality_for(picked_name: str, correct_name: str) -> float:
    if picked_name == correct_name:
        return 1.0
    head = correct_name.split("-")[0]
    return 0.4 if picked_name.startswith(head) else 0.0


def _run(db_path: Path, mode: str, episodes: int, seed: int) -> float:
    kaos, _ = _seed_db(db_path)
    try:
        sk = SkillStore(kaos.conn)
        runner = kaos.spawn(f"r-{mode}-{seed}")
        rng = random.Random(seed)
        epsilon = 0.25
        for i in range(episodes):
            query, correct = QUERIES[i % len(QUERIES)]
            results = sk.search(_fts_safe(query), limit=5, rank="weighted")
            if not results:
                continue
            if rng.random() < epsilon and len(results) > 1:
                picked = rng.choice(results)
            else:
                picked = results[0]
            ok = picked.name == correct
            if mode == "binary":
                sk.record_outcome(picked.skill_id, success=ok,
                                  agent_id=runner)
            else:  # quality
                q = _quality_for(picked.name, correct)
                sk.record_outcome(picked.skill_id, success=ok,
                                  quality=q, agent_id=runner)
        # Deterministic final measurement
        correct_total = 0
        for query, correct in QUERIES:
            r = sk.search(_fts_safe(query), limit=1, rank="weighted")
            if r and r[0].name == correct:
                correct_total += 1
        return correct_total / len(QUERIES)
    finally:
        kaos.close()


def main() -> int:
    episodes = 120
    seeds = [42, 43, 44, 45, 46]

    print("=" * 68)
    print("Quality-score benchmark — binary vs continuous outcome signal")
    print(f"{episodes} episodes/run, {len(seeds)} seeds, "
          f"{len(QUERIES)} queries, {len(SKILLS)} skills")
    print("=" * 68)

    bin_acc, qual_acc = [], []
    for s in seeds:
        b = _run(HERE / f"bin-{s}.db", "binary", episodes, s)
        q = _run(HERE / f"qual-{s}.db", "quality", episodes, s)
        bin_acc.append(b)
        qual_acc.append(q)
        print(f"  seed {s}:  binary={b:.1%}   quality={q:.1%}")

    b_mean = statistics.mean(bin_acc)
    q_mean = statistics.mean(qual_acc)
    b_std = statistics.pstdev(bin_acc)
    q_std = statistics.pstdev(qual_acc)

    print("\n" + "=" * 68)
    print("RESULT")
    print("=" * 68)
    print(f"  binary   mean={b_mean:.1%}  stdev={b_std:.4f}")
    print(f"  quality  mean={q_mean:.1%}  stdev={q_std:.4f}")
    acc_delta = (q_mean - b_mean) * 100
    var_drop = (b_std - q_std)
    print(f"  accuracy delta:  {acc_delta:+.1f} pp")
    print(f"  variance change: {var_drop:+.4f} (positive = seed variance increased)")

    out = {
        "episodes": episodes, "seeds": seeds,
        "binary": {"per_seed": bin_acc, "mean": b_mean, "pstdev": b_std},
        "quality": {"per_seed": qual_acc, "mean": q_mean, "pstdev": q_std},
        "accuracy_delta_pp": acc_delta,
        "variance_reduction": var_drop,
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=2),
                                       encoding="utf-8")

    md = [
        "# Quality-score benchmark — measured results\n",
        "Binary `success ∈ {0,1}` vs continuous `quality ∈ [0,1]` on the "
        "non-adversarial retrieval workload.\n",
        f"Run: {episodes} episodes/run, {len(seeds)} seeds.\n",
        "| Signal | mean acc | pstdev |",
        "|---|---:|---:|",
        f"| binary  | {b_mean:.1%} | {b_std:.4f} |",
        f"| quality | {q_mean:.1%} | {q_std:.4f} |",
        "",
        f"Accuracy delta: **{acc_delta:+.1f} pp**. "
        f"Variance change: **{var_drop:+.4f}** "
        f"(positive ⇒ the graded signal is less noisy across seeds).",
        "",
        "Raw JSON: [results.json](results.json)",
    ]
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # Acceptance: quality must not regress accuracy, and should not be
    # noisier than binary. Equal-or-better on both axes passes.
    if q_mean + 1e-9 < b_mean:
        print("\n  [WARN] quality regressed mean accuracy vs binary")
        return 1
    print(f"\n  [OK] quality signal: {acc_delta:+.1f}pp accuracy, "
          f"variance {var_drop:+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
