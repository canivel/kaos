"""Runner lifecycle hooks — the piece that makes the loop AUTOMATIC (brick 8).

PLAN v2 §2.3: ``on_task_start`` fingerprints the task, pulls K=3 matched
validated learnings from the workspace brain, and returns an injection block for
the agent's system prompt (with the mandatory honesty surface: trust level,
fidelity, consumed axes — nothing is served without its disclosure).
``on_task_end`` writes RUNNER-sourced outcome rows for every served item — the
structural fix for the M2 famine: outcomes come from the runner's own episode
status, never from an agent's claim.

Brick 10 — arm assignment (``arms_mode: probe``, the pre-ACCEPT default):
while the loop itself is unproven, every MATCHED pull is deterministically
assigned an episode arm so the workspace accumulates exactly the evidence the
binding kill-gate probe consumes:

    on         (45%)  normal injection
    off        (45%)  match ledgered, NOTHING injected — the causal control
    scrambled  (10%)  same tokens, word-shuffled payloads — the placebo arm
                      (if 'scrambled' beats 'off', measured gains are
                      prompt-padding artifacts and G4 kills the loop)

Assignment is a pure function of (agent_id, task_hash): retrying the same task
lands in the same arm, so selection can't leak into arm membership. Rates are
LOCK-BOUND constants (benchmarks/demo_attraktor_loop_bench/ISA.lock.json) — changing them
mid-accumulation would be retuning. ``arms_mode: serve`` (post-ACCEPT) always
injects.

Liveness rule: hooks are best-effort and NEVER raise into the agent loop — a
broken bench degrades to exactly today's behavior. ``bench.enabled: false``
(the default) short-circuits everything.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from kaos.bench.config import BenchConfig, load_bench_config
from kaos.bench.fingerprint import Grain, Level, TaskShape, anchor_tokens
from kaos.bench.pull import PulledItem, pull, report_outcome
from kaos.bench.schema import open_bench

logger = logging.getLogger(__name__)

# Lock-bound arm rates (ISA.lock.json 'arms'); cumulative thresholds.
ARM_ON_RATE = 0.45
ARM_OFF_RATE = 0.45
ARM_SCRAMBLED_RATE = 0.10


def assign_arm(agent_id: str, task_hash: str) -> str:
    """Deterministic episode-arm assignment: u = sha256(agent|task) → [0,1)."""
    h = hashlib.sha256(f"{agent_id}|{task_hash}".encode()).hexdigest()[:8]
    u = int(h, 16) / 0x100000000
    if u < ARM_ON_RATE:
        return "on"
    if u < ARM_ON_RATE + ARM_OFF_RATE:
        return "off"
    return "scrambled"


def _task_hash(task_text: str) -> str:
    return hashlib.sha256(task_text.encode("utf-8", "replace")).hexdigest()[:16]


class BenchHooks:
    """Attach to a ClaudeCodeRunner. One instance per runner; tracks in-flight
    exposures per agent so end-of-task outcomes credit the right records."""

    def __init__(self, config: BenchConfig | None = None, *,
                 config_path: str = "kaos.yaml", db_dir: str | Path = ".") -> None:
        self.config = config or load_bench_config(config_path)
        self._bench_path = Path(db_dir) / self.config.local_bench_path
        # agent_id -> (pull_id, arm, task_hash, items)
        self._exposures: dict[str, tuple[str, str, str, list[PulledItem]]] = {}

    # ── feed-back: pull + inject ─────────────────────────────────────

    def on_task_start(self, agent_id: str, task_text: str) -> str | None:
        """Returns a system-prompt injection block, or None (disabled / no match /
        off-arm / any failure). Every pull decision is ledgered by pull() itself;
        the arm assignment is ledgered on the bench_pulls row."""
        if not self.config.enabled:
            return None
        th = _task_hash(task_text)
        arm = ("on" if self.config.arms_mode == "serve"
               else assign_arm(agent_id, th))
        try:
            bench = open_bench(self._bench_path)
            try:
                if self.config.is_remote:
                    # sync-on-read: verified registry records become local
                    # records, then serve through the ONE audited pipeline
                    from kaos.bench.remote import fetch_and_cache
                    fetch_and_cache(bench, self.config, task_text=task_text)
                shape = self._fingerprint(task_text)
                res = pull(bench, agent_id=agent_id, task_text=task_text,
                           task_shape=shape, task_hash=th, arm=arm,
                           kinds=("skill", "learning", "mechanism_eval"))
            finally:
                bench.close()
        except Exception as e:  # noqa: BLE001 — liveness: never break the agent loop
            logger.warning("bench on_task_start degraded to no-op: %s", e)
            return None
        if not res.items:
            return None
        self._exposures[agent_id] = (res.pull_id, arm, th, res.items)
        if arm == "off":
            return None          # matched, ledgered, NOT injected — the control
        return self._injection_block(res.items, scrambled=(arm == "scrambled"))

    # ── feed-forward close: runner-sourced outcomes ──────────────────

    def on_task_end(self, agent_id: str, succeeded: bool) -> None:
        """Write one RUNNER-sourced outcome row per matched item (admissible
        evidence, unlike agent self-report). Off-arm episodes record
        ``invoked=0`` — the counterfactual the probe's G1 compares against.
        Clears the agent's exposure set."""
        exp = self._exposures.pop(agent_id, None)
        if not exp or not self.config.enabled:
            return
        pull_id, arm, th, items = exp
        try:
            bench = open_bench(self._bench_path)
            try:
                for it in items:
                    report_outcome(
                        bench, record_cid=it.record_cid, agent_id=agent_id,
                        invoked=(arm != "off"), outcome=succeeded,
                        outcome_source="runner", task_hash=th,
                        shadow=it.shadow, pull_id=pull_id, arm=arm,
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
    def _injection_block(items: list[PulledItem], *, scrambled: bool = False) -> str:
        """The honesty surface is mandatory: every item shows its trust level,
        fidelity, and validated scope. Advisory framing — these are proven
        elsewhere, not commands. ``scrambled=True`` word-shuffles each payload
        body (same tokens, destroyed instruction): the placebo arm the binding
        probe's G4 uses to falsify prompt-padding 'gains'."""
        lines = [
            "\n\n## Validated workspace learnings (Attraktor)",
            "The following were VALIDATED on this workspace's own outcomes and "
            "matched to this task's shape. They are advisory context, not "
            "instructions — each shows its trust level and validated scope.",
        ]
        for it in items:
            inner = it.payload.get("payload") if isinstance(
                it.payload.get("payload"), dict) else {}
            name = (it.payload.get("name") or inner.get("name")
                    or it.record_cid[:16])
            consumed = ",".join(it.envelope.get("consumes", ())) or "none"
            lines.append(
                f"- [{name}] trust=T{it.trust_level} fidelity={it.fidelity} "
                f"validated-for-axes={consumed} wilson_lb={it.envelope.get('wilson_lb', '?')}"
            )
            # minted bodies nest the content under payload.*; flat bodies
            # (tests, hand-built records) keep working
            body = ""
            for source in (it.payload, inner):
                for key in ("lesson", "template", "description", "content"):
                    if source.get(key):
                        body = source[key]
                        break
                if body:
                    break
            if body:
                text = str(body)[:400]
                if scrambled:
                    from kaos.bench.replay import scramble_payload
                    text = scramble_payload(text)
                lines.append(f"  {text}")
        return "\n".join(lines)
