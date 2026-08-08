"""Proposer agent — inspects the search archive and proposes new harness candidates.

The key insight from Meta-Harness is giving the proposer full visibility into all
prior candidates' code, scores, and traces. Rather than a multi-turn tool loop
(which replays the whole conversation per turn and times out on Opus/Sonnet), the
proposer pre-reads the archive into a compacted digest (``_build_archive_digest``)
and runs a single-shot LLM call that writes harness code blocks directly.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from kaos.metaharness.harness import HarnessCandidate
from kaos.metaharness.prompts import build_proposer_prompt, build_pivot_prompt, build_consolidation_prompt, build_reflect_prompt

if TYPE_CHECKING:
    from kaos.core import Kaos
    from kaos.metaharness.pareto import ParetoFrontier
    from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)


class ProposerAgent:
    """Proposes new harness candidates by inspecting the search archive.

    The proposer reads from the search agent's VFS (not its own) when it
    pre-builds the archive digest. Every read is audited in the event journal.
    """

    def __init__(
        self,
        afs: Kaos,
        router: GEPARouter,
        search_agent_id: str,
        proposer_model: str | None = None,
        max_iterations: int = 200,  # accepted for API stability; single-shot path ignores it
    ):
        self.afs = afs
        self.router = router
        self.search_agent_id = search_agent_id
        self.proposer_model = proposer_model
        self._submitted: list[HarnessCandidate] = []

    def _assemble_prompt(
        self,
        *,
        iteration: int,
        n_candidates: int,
        benchmark_name: str,
        frontier: ParetoFrontier,
        compaction_level: int = 5,
        pivot_pending: bool = False,
    ) -> str:
        """Assemble the full proposer prompt (proposer + digest + reflect +
        optional pivot + optional consolidation).

        The CORAL Tier-1 pivot is driven by a single ``pivot_pending`` flag
        raised by ``MetaHarnessSearch._update_stagnation`` — the SOLE authority
        for the pivot decision. Previously both this method and
        _update_stagnation recomputed the same stagnation predicate; the latter
        stamped pivot_fired_at first, which made this predicate permanently
        False (the reproduced "pivot is dead code" P0). When the flag is set we
        fire the pivot prompt and CONSUME the flag so it does not re-fire every
        subsequent iteration.
        """
        objective_summary = ", ".join(
            f"{name} ({direction})"
            for name, direction in frontier.objectives.items()
        )
        frontier_lines = []
        for p in frontier.points:
            scores_str = ", ".join(f"{k}={v:.4f}" for k, v in p.scores.items())
            frontier_lines.append(f"  {p.harness_id[:12]}... (iter {p.iteration}): {scores_str}")
        frontier_summary = "\n".join(frontier_lines) if frontier_lines else "  (empty — seeds not yet evaluated)"

        # Pre-build archive digest so the proposer doesn't need multiple
        # tool calls to read the archive (reduces turns from 5-10 to 1-2)
        archive_digest = self._build_archive_digest(compaction_level)

        prompt = build_proposer_prompt(
            iteration=iteration,
            n_candidates=n_candidates,
            benchmark_name=benchmark_name,
            objective_summary=objective_summary,
            frontier_summary=frontier_summary,
        )

        if archive_digest:
            skills_text = self._load_skills_text()
            memory_context = self._load_memory_context(benchmark_name)
            prompt += (
                "\n\n## Pre-loaded Archive Digest\n\n"
                "The following is a compacted summary of ALL prior harnesses, "
                "their scores, error patterns, and source code. This digest has "
                "everything you need to propose improvements.\n\n"
                + (skills_text + "\n" if skills_text else "")
                + (memory_context + "\n" if memory_context else "")
                + archive_digest
            )

        # CORAL: per-iteration reflect (always fires)
        prompt += build_reflect_prompt(iteration)

        # CORAL Tier 1: stagnation pivot — fire iff the single authority raised
        # the flag, then consume it.
        if pivot_pending and frontier.points:
            best_src = ""
            try:
                best_hid = frontier.points[0].harness_id
                raw = self.afs.read(self.search_agent_id, f"/harnesses/{best_hid}/source.py").decode()
                best_src = raw[:300] + ("..." if len(raw) > 300 else "")
            except Exception:
                pass
            # stagnant count is informational in the pivot prompt; the flag is
            # the decision. Read the current count for the message only.
            stagnant = self.afs.get_state_or(self.search_agent_id, "stagnant_iterations") or 0
            prompt += build_pivot_prompt(stagnant, best_src)
            self.afs.set_state(self.search_agent_id, "pivot_pending", False)

        # CORAL Tier 2: consolidation heartbeat
        try:
            cfg_data = json.loads(self.afs.read(self.search_agent_id, "/config.json").decode())
            cons_interval = cfg_data.get("consolidation_interval", 5)
        except Exception:
            cons_interval = 5
        if iteration > 0 and iteration % cons_interval == 0:
            prompt += build_consolidation_prompt(iteration)

        return prompt

    async def propose(
        self,
        iteration: int,
        n_candidates: int,
        benchmark_name: str,
        frontier: ParetoFrontier,
        compaction_level: int = 5,
        stagnant_iterations: int = 0,
        stagnation_threshold: int = 3,
        pivot_fired_at: int | None = None,
        pivot_pending: bool = False,
    ) -> list[HarnessCandidate]:
        """Run the proposer agent and collect submitted harness candidates.

        Returns a list of HarnessCandidate objects extracted from the response.
        """
        self._submitted = []

        prompt = self._assemble_prompt(
            iteration=iteration,
            n_candidates=n_candidates,
            benchmark_name=benchmark_name,
            frontier=frontier,
            compaction_level=compaction_level,
            pivot_pending=pivot_pending,
        )

        # Single-shot mode: send the full prompt once, extract python blocks.
        # This avoids the multi-turn CCR loop where each turn replays the
        # entire conversation via claude --print (causing timeouts on Opus/Sonnet).
        config = {}
        if self.proposer_model:
            config["force_model"] = self.proposer_model

        agent_id = self.afs.spawn(
            f"proposer-iter-{iteration}",
            config=config,
        )

        # Tell the model to write the code directly — no tool calls needed
        single_shot_prompt = (
            prompt + "\n\n"
            "IMPORTANT: Write your proposed harness(es) as complete ```python code blocks "
            "in your response. Each block must define a `def run(problem)` function. "
            "Do NOT try to call tools — just write the code directly."
        )

        try:
            # Single LLM call — no CCR loop, no conversation replay
            model_name = config.get("force_model") or self.router.fallback_model
            response = await self.router.route(
                agent_id=agent_id,
                messages=[
                    {"role": "system", "content": "You are a Meta-Harness proposer. Write Python harness code."},
                    {"role": "user", "content": single_shot_prompt},
                ],
                tools=[],  # no tools — single-shot
                config=config,
            )
            # Store the response as conversation for debugging/extraction
            conversation = [
                {"role": "system", "content": "proposer"},
                {"role": "user", "content": single_shot_prompt},
                {"role": "assistant", "content": response.content},
            ]
            self.afs.set_state(agent_id, "conversation", conversation)
            self.afs.complete(agent_id)
        except Exception as e:
            logger.error("Proposer agent failed at iteration %d: %s", iteration, e)
            self.afs.fail(agent_id, error=str(e))

        # Log the proposer conversation for debugging
        conversation = self.afs.get_state_or(agent_id, "conversation")
        if conversation:
            self.afs.write(
                self.search_agent_id,
                f"/iterations/{iteration}/proposer_conversation.json",
                json.dumps(conversation, indent=2).encode(),
            )

        # Fallback: if no tool-call submissions (e.g. claude --print doesn't
        # support tool-use), extract ```python blocks from the response text
        if not self._submitted and conversation:
            self._extract_from_text(conversation, n_candidates)

        # Set iteration on all submitted candidates
        for h in self._submitted:
            h.iteration = iteration

        logger.info(
            "Proposer iteration %d: %d candidates submitted",
            iteration, len(self._submitted),
        )
        return self._submitted

    def _extract_from_text(self, conversation: list[dict], max_candidates: int) -> None:
        """Extract harness candidates from plain text when tool-use isn't available.

        Scans assistant messages for ```python blocks containing a run() function.
        This is how the single-shot proposer path collects candidates. The block
        is expected to open with a `# HYPOTHESIS: ...` comment (per the proposer
        prompt); that line, or failing that the prose immediately preceding the
        block, is recorded as the candidate's rationale so the attempt archive and
        memory store carry a real hypothesis instead of a placeholder.
        """
        import re

        python_block_re = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
        # Iterate matches (not findall) so we can read the prose before each block.
        for msg in reversed(conversation):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if not content:
                continue

            last_end = 0
            for m in python_block_re.finditer(content):
                block = m.group(1).strip()
                preceding = content[last_end:m.start()]
                last_end = m.end()
                if "def run(" not in block:
                    continue
                if len(self._submitted) >= max_candidates:
                    break

                rationale = self._extract_rationale(block, preceding)
                candidate = HarnessCandidate.create(
                    source_code=block,
                    metadata={"source": "text_extraction", "rationale": rationale},
                )
                valid, err = candidate.validate_interface()
                if valid:
                    self._submitted.append(candidate)
                    logger.info(
                        "Extracted harness from text: %s (%d chars)",
                        candidate.harness_id[:12], len(block),
                    )
                else:
                    logger.debug("Extracted block failed validation: %s", err)

    @staticmethod
    def _extract_rationale(block: str, preceding: str) -> str:
        """Recover the candidate's improvement hypothesis for the record.

        Preference order: an explicit ``# HYPOTHESIS:`` comment in the code block,
        then the last non-empty prose line before the block, then a plain marker
        so downstream readers can tell the model gave no rationale (rather than a
        misleading placeholder that looks intentional)."""
        import re

        m = re.search(r"#\s*HYPOTHESIS:\s*(.+)", block, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:500]
        for line in reversed(preceding.strip().splitlines()):
            line = line.strip().lstrip("#").strip()
            # skip markdown headers/fences and empty lines
            if line and not line.startswith("```"):
                return line[:500]
        return "(no rationale stated by proposer)"

    # ── Skills ──────────────────────────────────────────────────

    def _load_skills_text(self, max_skills: int = 10) -> str:
        """Load reusable skills from /skills/ and format them for the prompt."""
        try:
            entries = self.afs.ls(self.search_agent_id, "/skills")
            skills = []
            for entry in entries:
                if entry.get("is_dir") or not entry["path"].endswith(".json"):
                    continue
                try:
                    skill = json.loads(self.afs.read(self.search_agent_id, entry["path"]).decode())
                    skills.append(skill)
                except Exception:
                    continue
            if not skills:
                return ""
            skills = skills[:max_skills]
            lines = ["## Reusable Skills (distilled from prior iterations)"]
            for s in skills:
                lines.append(f"- **{s['name']}**: {s['description']}")
                if s.get("code_template"):
                    snippet = s["code_template"][:200]
                    lines.append(f"  ```python\n  {snippet}\n  ```")
            return "\n".join(lines)
        except Exception:
            return ""

    def _load_memory_context(self, benchmark_name: str, limit: int = 5) -> str:
        """Query cross-agent memory for relevant prior results (claude-mem inspired).

        Looks for 'result' and 'error' type entries related to this benchmark
        to give the proposer cross-session context.
        """
        try:
            from kaos.memory import MemoryStore
            mem = MemoryStore(self.afs.conn)
            hits = mem.search(query=benchmark_name, limit=limit)
            if not hits:
                return ""
            lines = ["## Cross-Session Memory (from shared memory store)"]
            for h in hits:
                lines.append(f"- [{h.type}] {h.content[:200]}")
            return "\n".join(lines)
        except Exception:
            return ""

    # ── Archive digest ───────────────────────────────────────────

    def _build_archive_digest(self, compaction_level: int) -> str:
        """Pre-read the archive and build a compacted digest."""
        from kaos.metaharness.compactor import Compactor

        try:
            compactor = Compactor(level=compaction_level)
            harness_dirs = self.afs.ls(self.search_agent_id, "/harnesses")

            harness_data = []
            for entry in harness_dirs:
                if not entry.get("is_dir"):
                    continue
                hid = entry["name"]
                h: dict = {"harness_id": hid}

                try:
                    h["scores"] = json.loads(
                        self.afs.read(self.search_agent_id, f"/harnesses/{hid}/scores.json").decode()
                    )
                except FileNotFoundError:
                    h["scores"] = {}

                try:
                    meta = json.loads(
                        self.afs.read(self.search_agent_id, f"/harnesses/{hid}/metadata.json").decode()
                    )
                    h["iteration"] = meta.get("iteration", 0)
                    h["error"] = meta.get("error")
                except FileNotFoundError:
                    h["iteration"] = 0

                try:
                    h["source"] = self.afs.read(
                        self.search_agent_id, f"/harnesses/{hid}/source.py"
                    ).decode()
                except FileNotFoundError:
                    h["source"] = ""

                try:
                    pp_raw = self.afs.read(
                        self.search_agent_id, f"/harnesses/{hid}/per_problem.jsonl"
                    ).decode()
                    h["per_problem"] = [
                        json.loads(line) for line in pp_raw.strip().split("\n") if line.strip()
                    ]
                except FileNotFoundError:
                    h["per_problem"] = []

                harness_data.append(h)

            if not harness_data:
                return ""

            # Read frontier
            try:
                frontier_data = json.loads(
                    self.afs.read(self.search_agent_id, "/pareto/frontier.json").decode()
                )
            except FileNotFoundError:
                frontier_data = None

            digest, metrics = compactor.build_digest(harness_data, frontier_data)

            # Store metrics for debugging
            self.afs.write(
                self.search_agent_id,
                f"/compaction_metrics.json",
                json.dumps({
                    **metrics.to_dict(),
                    "effective_compaction_level": compaction_level,
                    "harness_count": len(harness_data),
                }, indent=2).encode(),
            )

            logger.info(
                "Archive digest: %d→%d chars (%.0f%% saved, retention=%.0f%%, level=%d, harnesses=%d)",
                metrics.original_chars, metrics.compacted_chars,
                metrics.savings_pct, metrics.retention_score * 100,
                compaction_level, len(harness_data),
            )

            return digest

        except Exception as e:
            logger.warning("Failed to build archive digest: %s", e)
            return ""

    # ── Archive tool handlers ────────────────────────────────────
