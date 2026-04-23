"""Narrative phase — assemble a human-readable digest from prior phases.

M1 ships a deterministic, template-based digest (free, reproducible, testable).
A future milestone can add an ``--narrative llm`` mode that asks a model to
write prose, but the deterministic path must stay so the cycle is usable
offline and in CI without API keys or cost.
"""

from __future__ import annotations

from datetime import datetime

from kaos.dream.phases.associations import AssociationsReport
from kaos.dream.phases.consolidation import ConsolidationReport
from kaos.dream.phases.failures import FailuresReport
from kaos.dream.phases.policies import PoliciesReport
from kaos.dream.phases.replay import ReplayReport
from kaos.dream.phases.weights import WeightsReport
from kaos.dream.signals import now_utc


def render_digest(
    *,
    replay: ReplayReport,
    weights: WeightsReport,
    associations: AssociationsReport | None = None,
    failures: FailuresReport | None = None,
    consolidation: ConsolidationReport | None = None,
    policies: PoliciesReport | None = None,
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
    if associations is not None:
        _section_associations(lines, associations)
    if failures is not None:
        _section_failures(lines, failures)
    if consolidation is not None:
        _section_consolidation(lines, consolidation)
    if policies is not None:
        _section_policies(lines, policies)
    _section_recommendations(lines, replay, weights, consolidation, failures)
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


def _section_associations(lines: list[str], a: AssociationsReport) -> None:
    lines.append("## 🕸️ Associations (Hebbian graph)")
    lines.append("")
    if not a.total_edges:
        lines.append("_No co-occurrence edges yet — associations build as agents run._")
        lines.append("")
        return
    lines.append(f"{a.total_edges} edges across the library.")
    lines.append("")
    if a.top_edges:
        lines.append("**Top co-fired pairs (recency-decayed):**")
        lines.append("")
        lines.append("| A | B | weight | uses |")
        lines.append("|---|---|---:|---:|")
        for e in a.top_edges[:10]:
            lines.append(
                f"| `{e.kind_a}:{e.label_a}` | `{e.kind_b}:{e.label_b}` "
                f"| {e.decayed_weight:.2f} | {e.uses} |"
            )
        lines.append("")


def _section_failures(lines: list[str], f: FailuresReport) -> None:
    lines.append("## ⚠️ Failure fingerprints")
    lines.append("")
    if not f.total_fingerprints:
        lines.append("_No failures fingerprinted. (Either nothing has failed, "
                     "or only the success path has run so far.)_")
        lines.append("")
        return
    lines.append(f"Tracking **{f.total_fingerprints}** distinct failure signatures "
                 f"(newly added this cycle: **{f.newly_added}**).")
    lines.append("")
    if f.recurring:
        lines.append("**Recurring failures (count ≥ 2):**")
        lines.append("")
        lines.append("| Fingerprint | Tool | Count | Has fix? | Last seen |")
        lines.append("|---|---|---:|:---:|---|")
        for fe in f.recurring[:10]:
            fix = "✓" if fe.fix_summary or fe.fix_skill_id else "—"
            err = (fe.example_error or "")[:60]
            lines.append(
                f"| `{fe.fingerprint}` — `{err}` | {fe.tool_name or '_?_'} "
                f"| {fe.count} | {fix} | {fe.last_seen} |"
            )
        lines.append("")


def _section_consolidation(lines: list[str], c: ConsolidationReport) -> None:
    lines.append("## 🛠 Consolidation proposals")
    lines.append("")
    if not c.proposals:
        lines.append("_No structural changes proposed this cycle. "
                     "Library is stable._")
        lines.append("")
        return
    lines.append(
        f"**{len(c.proposals)}** proposals "
        f"({c.promoted} promote, {c.pruned} prune, "
        f"{c.merge_candidates} merge candidates). "
        f"Applied this cycle: **{c.applied}**."
    )
    if c.trigger_reason:
        lines.append(f"Trigger: `{c.trigger_reason}`.")
    lines.append("")
    for p in c.proposals[:12]:
        marker = {"promote": "🚀", "prune": "✂️", "merge": "🔗", "split": "🪓"}.get(p.kind, "•")
        applied = " · **applied**" if p.applied else ""
        lines.append(f"- {marker} **{p.kind}**{applied}: {p.rationale}")
    lines.append("")


def _section_policies(lines: list[str], p: PoliciesReport) -> None:
    if not p.candidates:
        return
    lines.append("## 📜 Auto-promoted policies")
    lines.append("")
    lines.append(f"{p.total_promoted} newly promoted this cycle "
                 f"({p.skipped_existing} already known).")
    lines.append("")
    for cand in p.candidates[:8]:
        new = " 🆕" if cand.newly_promoted else ""
        lines.append(
            f"- `{cand.action_pattern}` — approval "
            f"{int(cand.approval_rate * 100)}% "
            f"over {cand.sample_size} vote(s){new}"
        )
    lines.append("")


def _section_recommendations(
    lines: list[str],
    r: ReplayReport,
    w: WeightsReport,
    c: ConsolidationReport | None = None,
    f: FailuresReport | None = None,
) -> None:
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
            f"- **{len(cold)} skills never used**: consolidation will mark "
            "them deprecated once they cross the prune threshold."
        )
    if c and c.proposals and c.applied == 0:
        unapplied = [p for p in c.proposals if not p.applied]
        if unapplied:
            recs.append(
                f"- **{len(unapplied)} consolidation proposals awaiting review** "
                "(merges are never auto-applied). Run `kaos dream consolidate "
                "--apply` if you accept them."
            )
    if f and f.recurring:
        without_fix = [fe for fe in f.recurring if not (fe.fix_summary or fe.fix_skill_id)]
        if without_fix:
            recs.append(
                f"- **{len(without_fix)} recurring failures without a recorded fix**. "
                "Attach a fix via `kaos dream failures attach <fp_id>` so future "
                "agents hitting the same error get the known solution."
            )
    if not recs:
        recs.append("- Nothing obviously wrong. Library is warming up.")
    lines.extend(recs)
    lines.append("")


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "_(no uses)_"
    return f"{rate * 100:.1f}%"
