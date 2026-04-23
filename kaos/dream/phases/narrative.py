"""Narrative phase — assemble a human-readable digest from prior phases.

M1 ships a deterministic, template-based digest (free, reproducible, testable).
A future milestone can add an ``--narrative llm`` mode that asks a model to
write prose, but the deterministic path must stay so the cycle is usable
offline and in CI without API keys or cost.
"""

from __future__ import annotations

from datetime import datetime

from kaos.dream.phases.replay import ReplayReport
from kaos.dream.phases.weights import WeightsReport
from kaos.dream.signals import now_utc


def render_digest(
    *,
    replay: ReplayReport,
    weights: WeightsReport,
    mode: str,
    since_ts: str | None,
    started_at: datetime,
    finished_at: datetime,
    db_path: str,
    kaos_version: str = "0.7.0",
) -> str:
    """Produce a markdown digest summarising the dream cycle."""
    lines: list[str] = []
    lines.append("---")
    lines.append("type: dream_digest")
    lines.append(f"mode: {mode}")
    lines.append(f"db: {db_path}")
    lines.append(f"since: {since_ts or 'all-time'}")
    lines.append(f"kaos_version: {kaos_version}")
    lines.append(f"started_at: {started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"finished_at: {finished_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"episodes: {len(replay.episodes)}")
    lines.append(f"skills_scored: {len(weights.skills)}")
    lines.append(f"memories_scored: {len(weights.memory)}")
    lines.append("tags: [dream, digest]")
    lines.append("---")
    lines.append("")
    lines.append("# KAOS dream digest")
    lines.append("")
    lines.append(
        f"Cycle finished in "
        f"{(finished_at - started_at).total_seconds():.2f}s · "
        f"`{mode}` mode · "
        f"db `{db_path}` · "
        f"window `{since_ts or 'all-time'}`"
    )
    lines.append("")
    _section_replay(lines, replay)
    _section_hot_skills(lines, weights)
    _section_cold_skills(lines, weights)
    _section_hot_memory(lines, weights)
    _section_cold_memory(lines, weights)
    _section_recommendations(lines, replay, weights)
    return "\n".join(lines) + "\n"


def _section_replay(lines: list[str], r: ReplayReport) -> None:
    lines.append("## Episodes (replay)")
    lines.append("")
    total = len(r.episodes)
    if total == 0:
        lines.append("_No episodes replayed — the database has no agents yet._")
        lines.append("")
        return
    rate = (r.successes / total * 100.0) if total else 0.0
    lines.append(f"- **{total}** episodes  ·  **{r.successes}** completed"
                 f"  ·  **{r.failures}** failed  ·  **{r.in_flight}** in flight")
    lines.append(f"- Success rate: **{rate:.1f}%**")
    lines.append(f"- Total tokens across all runs: **{r.total_tokens:,}**")
    lines.append(f"- Total spend: **${r.total_cost_usd:.4f}**")
    # Top-5 agents by tool calls — a cheap "who's doing the work" view
    if r.episodes:
        top = sorted(r.episodes, key=lambda e: -e.tool_calls_count)[:5]
        if any(e.tool_calls_count for e in top):
            lines.append("")
            lines.append("**Top agents by tool-call volume**")
            for ep in top:
                status = ep.status
                lines.append(
                    f"- `{ep.agent_id[-8:]}` ({status}) — "
                    f"{ep.tool_calls_count} calls, "
                    f"{ep.tool_calls_error} errors, "
                    f"{ep.total_tokens:,} tokens"
                )
    lines.append("")


def _section_hot_skills(lines: list[str], w: WeightsReport) -> None:
    lines.append("## 🔥 Hot skills (top by weighted score)")
    lines.append("")
    if not w.hot_skills:
        lines.append("_No skills in the library._")
        lines.append("")
        return
    lines.append("| Skill | Uses | Success rate | Score |")
    lines.append("|---|---:|---:|---:|")
    for s in w.hot_skills:
        sr = _fmt_rate(s.success_rate)
        lines.append(
            f"| `{s.name}` | {s.uses} | {sr} | {s.score:.4f} |"
        )
    lines.append("")


def _section_cold_skills(lines: list[str], w: WeightsReport) -> None:
    cold = [s for s in w.cold_skills if s.coldness >= 0.5]
    if not cold:
        return
    lines.append("## ❄️ Cold skills (candidates for pruning or refresh)")
    lines.append("")
    lines.append("| Skill | Uses | Last used | Coldness |")
    lines.append("|---|---:|---|---:|")
    for s in cold[:10]:
        last = s.last_used_at or "_never_"
        lines.append(f"| `{s.name}` | {s.uses} | {last} | {s.coldness:.2f} |")
    lines.append("")


def _section_hot_memory(lines: list[str], w: WeightsReport) -> None:
    lines.append("## 🧠 Hot memory (most-retrieved)")
    lines.append("")
    if not w.hot_memory:
        lines.append("_No memory entries._")
        lines.append("")
        return
    lines.append("| Key | Type | Hits | Score |")
    lines.append("|---|---|---:|---:|")
    for m in w.hot_memory:
        key = m.key or f"memory-{m.memory_id}"
        lines.append(f"| `{key}` | {m.type} | {m.hits} | {m.score:.4f} |")
    lines.append("")


def _section_cold_memory(lines: list[str], w: WeightsReport) -> None:
    cold = [m for m in w.cold_memory if m.coldness >= 0.5]
    if not cold:
        return
    lines.append("## 🧊 Cold memory")
    lines.append("")
    lines.append("| Key | Type | Hits | Coldness |")
    lines.append("|---|---|---:|---:|")
    for m in cold[:10]:
        key = m.key or f"memory-{m.memory_id}"
        lines.append(f"| `{key}` | {m.type} | {m.hits} | {m.coldness:.2f} |")
    lines.append("")


def _section_recommendations(lines: list[str], r: ReplayReport, w: WeightsReport) -> None:
    lines.append("## Recommendations for the next cycle")
    lines.append("")
    recs: list[str] = []
    if r.failures >= 3 and r.failures / max(1, len(r.episodes)) > 0.3:
        recs.append(
            "- **Investigate failures**: "
            f"{r.failures}/{len(r.episodes)} episodes failed. "
            "Surface traces via `kaos logs <agent_id>` for the red agents above."
        )
    low_confidence = [s for s in w.hot_skills if s.uses < 3]
    if low_confidence:
        recs.append(
            f"- **Low-confidence top skills**: "
            f"{len(low_confidence)} of the hot-skill list have <3 uses. "
            "Scores will stabilise as they accumulate usage."
        )
    cold = [s for s in w.cold_skills if s.uses == 0]
    if cold:
        recs.append(
            f"- **{len(cold)} skills never used**: consider pruning in the M3 consolidation pass."
        )
    if not recs:
        recs.append("- Nothing obviously wrong. Library is warming up.")
    lines.extend(recs)
    lines.append("")


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "_(no uses)_"
    return f"{rate * 100:.1f}%"
