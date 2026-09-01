"""Real measurement of neuroplasticity gains.

Runs two identical training loops against the same ambiguous query set —
one with plasticity (rank="weighted") and one without (rank="bm25") —
and reports the actual accuracy delta.

Reproducible. Deterministic round-robin. No pre-engineered outcomes.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# Disable auto-consolidation during the benchmark. We want to isolate the
# *search ranking* effect, not the additional wins from structural changes
# that fire at the episode threshold. A later benchmark can add the
# consolidation contribution on top.
os.environ["KAOS_DREAM_THRESHOLD"] = "1000000"

from kaos import Kaos  # noqa: E402
from kaos.skills import SkillStore  # noqa: E402


# ── The benchmark — 10 ambiguous queries with ground truth ──────────


# Queries with one CORRECT skill and several plausible DISTRACTORS that
# share vocabulary with the query but shouldn't be picked. All skills below
# will be indexed by FTS5; bm25 alone cannot reliably pick the correct one
# because the distractors share key terms.

# Twin-pair design: each query has two plausible candidates that share
# vocabulary, making bm25 essentially a coin-flip between them. Only one is
# ground-truth correct. Plasticity must learn from outcomes to disambiguate.
SKILLS = [
    # --- pair 1: classify text ---
    ("tfidf-logreg-classifier",
     "Classify text document topic with tfidf logreg features."),
    ("naive-bayes-text-classifier",
     "Classify text document topic with naive bayes features."),

    # --- pair 2: forecast time series ---
    ("arima-forecaster",
     "Forecast time series univariate values with arima seasonal."),
    ("prophet-forecaster",
     "Forecast time series univariate values with prophet seasonal."),

    # --- pair 3: detect time series anomaly ---
    ("time-series-anomaly-detector",
     "Detect time series anomaly with stl residual threshold."),
    ("autoencoder-series-anomaly",
     "Detect time series anomaly with autoencoder reconstruction threshold."),

    # --- pair 4: classify image ---
    ("cnn-image-classifier",
     "Classify image label with cnn backbone pretrained."),
    ("vit-image-classifier",
     "Classify image label with vit transformer pretrained."),

    # --- pair 5: segment image pixel ---
    ("image-segmentation-unet",
     "Segment image pixel region with unet encoder decoder."),
    ("image-segmentation-maskrcnn",
     "Segment image pixel region with maskrcnn instance head."),

    # --- pair 6: transcribe speech ---
    ("whisper-speech-transcriber",
     "Transcribe speech audio to text with whisper pretrained."),
    ("deepspeech-speech-transcriber",
     "Transcribe speech audio to text with deepspeech pretrained."),

    # --- pair 7: classify audio clip ---
    ("mfcc-audio-classifier",
     "Classify audio clip label with mfcc features forest."),
    ("melspec-audio-classifier",
     "Classify audio clip label with melspec features forest."),

    # --- pair 8: classify tabular structured ---
    ("xgboost-tabular-classifier",
     "Classify tabular structured row with xgboost gradient boosted."),
    ("randomforest-tabular-classifier",
     "Classify tabular structured row with randomforest gradient ensemble."),

    # --- pair 9: detect tabular anomaly ---
    ("isolation-forest-tabular-anomaly",
     "Detect tabular anomaly row with isolation forest ensemble."),
    ("autoencoder-tabular-anomaly",
     "Detect tabular anomaly row with autoencoder reconstruction ensemble."),

    # --- pair 10: extract named entity ---
    ("spacy-ner-tagger",
     "Extract named entity span with spacy tagger pretrained."),
    ("bert-ner-tagger",
     "Extract named entity span with bert tagger pretrained."),
]


# Each query has exactly one ground-truth correct skill.
# Queries use keyword-style terms (the way FTS5 is designed to be queried and
# the way agents actually phrase searches). Each query should match 2-4
# skills on raw FTS relevance so bm25 alone can't reliably pick the winner.
# Queries use terms that appear in the skill descriptions and stem the same
# way under Porter (e.g. "classify" stems to "classifi" — same as "classifier").
# Each query still has multiple plausible matches under bm25 alone.
QUERIES = [
    ("classify text topic",                      "tfidf-logreg-classifier"),
    ("forecast time series",                     "arima-forecaster"),
    ("detect time series anomaly",               "time-series-anomaly-detector"),
    ("classify image label",                     "cnn-image-classifier"),
    ("segment image pixel region",               "image-segmentation-unet"),
    ("transcribe speech audio",                  "whisper-speech-transcriber"),
    ("classify audio clip",                      "mfcc-audio-classifier"),
    ("classify tabular structured row",          "xgboost-tabular-classifier"),
    ("detect tabular anomaly row",               "isolation-forest-tabular-anomaly"),
    ("extract named entity span",                "spacy-ner-tagger"),
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
                      tags=["benchmark"])
        skill_ids[name] = sid
    return kaos, skill_ids


def _one_episode(kaos: Kaos, sk: SkillStore, query: str,
                 correct_name: str, rank_mode: str,
                 agent_id: str, rng: random.Random,
                 epsilon: float) -> bool:
    """Perform one training episode — epsilon-greedy pick.

    With probability epsilon, explore a random skill among the top-5.
    Otherwise exploit the top-1. This mirrors how real agents use search
    results: mostly pick the best, occasionally try alternatives.

    Returns True if the pick was the ground-truth correct skill.
    """
    results = sk.search(query, limit=5, rank=rank_mode)
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
    """Final measurement — one pick per query. Does NOT record outcomes."""
    correct_per_query: dict[str, int] = {}
    for query, correct_name in QUERIES:
        results = sk.search(query, limit=1, rank=rank_mode)
        correct_per_query[query] = int(bool(results) and
                                       results[0].name == correct_name)
    return correct_per_query


def _run_training(db_path: Path, rank_mode: str, episodes: int,
                  epsilon: float = 0.25, seed: int = 42) -> Report:
    """Same protocol for both bm25 and weighted runs; only rank_mode varies.

    Both runs explore with the same seeded RNG so the only true variable is
    whether plasticity is allowed to reshape the ranking.
    """
    kaos, skill_ids = _seed_db(db_path)
    try:
        sk = SkillStore(kaos.conn)
        runner_agent = kaos.spawn(f"runner-{rank_mode}")

        rng = random.Random(seed)  # same seed for both runs = honest comparison

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

        # Final measurement — deterministic, no exploration
        per_query = _measure_accuracy(kaos, sk, rank_mode)
        final_acc = sum(per_query.values()) / len(per_query)

        return Report(
            mode=rank_mode,
            accuracy_curve=curve,
            final_accuracy=final_acc,
            correct_per_query=per_query,
            total_episodes=episodes,
        )
    finally:
        kaos.close()


# ── Main ────────────────────────────────────────────────────────────


def main() -> int:
    episodes = 80  # 8 passes over the 10-query set

    bm25_db = HERE / "bench-bm25.db"
    weighted_db = HERE / "bench-weighted.db"

    print("=" * 68)
    print(f"Neuroplasticity gain benchmark — {episodes} training episodes")
    print(f"10 ambiguous queries over {len(SKILLS)} skills")
    print("=" * 68)

    print("\n-- Control group: rank='bm25' (no plasticity feedback) --")
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

    # Find break-even episode (first checkpoint where weighted > bm25)
    break_even_idx = -1
    for i, (w, b) in enumerate(zip(weighted_report.accuracy_curve,
                                   bm25_report.accuracy_curve)):
        if w > b:
            break_even_idx = i
            break
    break_even_episode = (break_even_idx + 1) * (episodes // 4) if break_even_idx >= 0 else None

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

    # Per-query breakdown
    print("\n  Per-query accuracy:")
    print(f"  {'query':<48}  bm25  weighted")
    for (q, correct) in QUERIES:
        b = bm25_report.correct_per_query.get(q, 0)
        w = weighted_report.correct_per_query.get(q, 0)
        marker = ""
        if w == 1 and b == 0:
            marker = "  <- plasticity win"
        elif b == 1 and w == 0:
            marker = "  <- bm25 win"
        print(f"  {q[:48]:<48}  {b:>4}  {w:>8}{marker}")

    # Persist as JSON + markdown for the README to reference
    out_json = {
        "episodes": episodes,
        "n_queries": len(QUERIES),
        "n_skills": len(SKILLS),
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
        "# Neuroplasticity gain — measured results\n",
        f"Benchmark run: {episodes} episodes, {len(QUERIES)} queries, "
        f"{len(SKILLS)} skills.\n",
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
    for (q, correct) in QUERIES:
        b = bm25_report.correct_per_query.get(q, 0)
        w = weighted_report.correct_per_query.get(q, 0)
        md.append(f"| {q} | {'✓' if b else '✗'} | {'✓' if w else '✗'} |")
    md.append("")
    md.append(f"Raw JSON: [results.json](results.json)")
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # Exit 0 only if weighted actually beat bm25 (protects against regression
    # in the weighted ranking). Equal or worse = benchmark fails.
    if absolute_gain <= 0:
        print("\n  [WARN] Weighted did NOT outperform bm25 on this run.")
        return 1
    print(f"\n  [OK] Plasticity gained +{absolute_gain * 100:.1f}pp "
          f"over the bm25 baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
