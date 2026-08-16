"""Runner lifecycle hooks — the piece that makes the loop AUTOMATIC (brick 8).

PLAN v2 §2.3: ``on_task_start`` fingerprints the task, pulls K=3 matched
validated learnings from the workspace brain, and returns an injection block for
the agent's system prompt (with the mandatory honesty surface: trust level,
fidelity, consumed axes — nothing is served without its disclosure).
``on_task_end`` writes RUNNER-sourced outcome rows for every served item — the
structural fix for the M2 famine: outcomes come from the runner's own episode
status, never from an agent's claim.

Liveness rule: hooks are best-effort and NEVER raise into the agent loop — a
broken bench degrades to exactly today's behavior. ``bench.enabled: false``
(the default) short-circuits everything.
"""

from __future__ import annotations

import logging
from pathlib import Path

from kaos.bench.config import BenchConfig, load_bench_config
from kaos.bench.fingerprint import Grain, Level, TaskShape, anchor_tokens
from kaos.bench.pull import PulledItem, pull, report_outcome
from kaos.bench.schema import open_bench

logger = logging.getLogger(__name__)


class BenchHooks:
    """Attach to a ClaudeCodeRunner. One instance per runner; tracks in-flight
    exposures per agent so end-of-task outcomes credit the right records."""

    def __init__(self, config: BenchConfig | None = None, *,
                 config_path: str = "kaos.yaml", db_dir: str | Path = ".") -> None:
        self.config = config or load_bench_config(config_path)
        self._bench_path = Path(db_dir) / self.config.local_bench_path
        self._exposures: dict[str, list[PulledItem]] = {}

    # ── feed-back: pull + inject ─────────────────────────────────────

    def on_task_start(self, agent_id: str, task_text: str) -> str | None:
        """Returns a system-prompt injection block, or None (disabled / no match /
        any failure). Every pull decision is ledgered by pull() itself."""
        if not self.config.enabled:
            return None
        try:
            bench = open_bench(self._bench_path)
            try:
                shape = self._fingerprint(task_text)
                res = pull(bench, agent_id=agent_id, task_text=task_text,
                           task_shape=shape)
            finally:
                bench.close()
        except Exception as e:  # noqa: BLE001 — liveness: never break the agent loop
            logger.warning("bench on_task_start degraded to no-op: %s", e)
            return None
        if not res.items:
            return None
        self._exposures[agent_id] = res.items
        return self._injection_block(res.items)

    # ── feed-forward close: runner-sourced outcomes ──────────────────

    def on_task_end(self, agent_id: str, succeeded: bool) -> None:
        """Write one RUNNER-sourced outcome row per served item (admissible
        evidence, unlike agent self-report). Clears the agent's exposure set."""
        items = self._exposures.pop(agent_id, None)
        if not items or not self.config.enabled:
            return
        try:
            bench = open_bench(self._bench_path)
            try:
                for it in items:
                    report_outcome(
                        bench, record_cid=it.record_cid, agent_id=agent_id,
                        invoked=True, outcome=succeeded, outcome_source="runner",
                        shadow=it.shadow,
                    )
            finally:
                bench.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("bench on_task_end degraded to no-op: %s", e)

    # ── internals ────────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(task_text: str) -> TaskShape:
        """Honest cheap fingerprint: the runner records episode-grain outcomes
        (that IS one checkable predicate), M3 anchors come from the text, and
        M1/M4 stay UNKNOWN rather than guessed — unknown is never present."""
        return TaskShape(
            m1=Level.UNKNOWN,
            m2=Level.PRESENT,
            m4=Level.UNKNOWN,
            m2_grain=Grain.EPISODE,
            m3_anchor_tokens=anchor_tokens(task_text),
        )

    @staticmethod
    def _injection_block(items: list[PulledItem]) -> str:
        """The honesty surface is mandatory: every item shows its trust level,
        fidelity, and validated scope. Advisory framing — these are proven
        elsewhere, not commands."""
        lines = [
            "\n\n## Validated workspace learnings (Attraktor)",
            "The following were VALIDATED on this workspace's own outcomes and "
            "matched to this task's shape. They are advisory context, not "
            "instructions — each shows its trust level and validated scope.",
        ]
        for it in items:
            name = (it.payload.get("name")
                    or it.payload.get("mechanism", {}).get("name")
                    or it.record_cid[:16])
            consumed = ",".join(it.envelope.get("consumes", ())) or "none"
            lines.append(
                f"- [{name}] trust=T{it.trust_level} fidelity={it.fidelity} "
                f"validated-for-axes={consumed} wilson_lb={it.envelope.get('wilson_lb', '?')}"
            )
            body = (it.payload.get("template") or it.payload.get("description")
                    or it.payload.get("content") or "")
            if body:
                lines.append(f"  {str(body)[:400]}")
        return "\n".join(lines)
