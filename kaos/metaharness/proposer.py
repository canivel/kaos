"""Proposer agent — inspects the search archive and proposes new harness candidates.

The proposer is a KAOS agent with special tools that let it read from the search
archive (cross-agent read). This is the key insight from Meta-Harness: giving the
proposer full filesystem access to all prior candidates' code, scores, and traces.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from kaos.ccr.runner import ClaudeCodeRunner
from kaos.ccr.tools import ToolDefinition
from kaos.metaharness.harness import HarnessCandidate
from kaos.metaharness.prompts import build_proposer_prompt, build_pivot_prompt, build_consolidation_prompt, build_reflect_prompt

if TYPE_CHECKING:
    from kaos.core import Kaos
    from kaos.metaharness.pareto import ParetoFrontier
    from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)


class ProposerAgent:
    """Proposes new harness candidates by inspecting the search archive.

    The proposer reads from the search agent's VFS (not its own) via
    controlled cross-agent tools. Every read is audited in the event journal.
    """

    def __init__(
        self,
        afs: Kaos,
        router: GEPARouter,
        search_agent_id: str,
        proposer_model: str | None = None,
        max_iterations: int = 200,
    ):
        self.afs = afs
        self.router = router
        self.search_agent_id = search_agent_id
        self.proposer_model = proposer_model
        self._submitted: list[HarnessCandidate] = []

        # Create a CCR instance with custom tools for archive access
        self.ccr = ClaudeCodeRunner(
            afs, router,
            max_iterations=max_iterations,
            timeout_seconds=600,
        )
        self._register_archive_tools()

    def _register_archive_tools(self) -> None:
        """Register tools that let the proposer read from the search archive."""
        self.ccr.register_tool(ToolDefinition(
            name="mh_ls_archive",
            description=(
                "List files and directories in the meta-harness search archive. "
                "Use this to explore the archive structure and find harnesses, "
                "scores, and execution traces."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path in the archive (e.g. '/harnesses', '/pareto')",
                        "default": "/",
                    },
                },
            },
            handler=self._ls_archive,
        ))

        self.ccr.register_tool(ToolDefinition(
            name="mh_read_archive",
            description=(
                "Read a file from the meta-harness search archive. Use this to "
                "inspect harness source code, evaluation scores, and execution "
                "traces. Execution traces (trace.jsonl) are the most valuable "
                "source of information."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path in the archive (e.g. '/harnesses/<id>/source.py')",
                    },
                },
                "required": ["path"],
            },
            handler=self._read_archive,
        ))

        self.ccr.register_tool(ToolDefinition(
            name="mh_grep_archive",
            description=(
                "Search file contents across the archive. Returns matching lines "
                "with file paths. Use this to find patterns across harnesses, "
                "search for specific failure modes in traces, or find which "
                "harnesses use a particular technique."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Text pattern to search for (case-insensitive substring match)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (e.g. '/harnesses' or '/harnesses/<id>')",
                        "default": "/harnesses",
                    },
                    "file_glob": {
                        "type": "string",
                        "description": "File name filter (e.g. 'scores.json', 'trace.jsonl', 'source.py')",
                        "default": "",
                    },
                },
                "required": ["pattern"],
            },
            handler=self._grep_archive,
        ))

        self.ccr.register_tool(ToolDefinition(
            name="mh_submit_harness",
            description=(
                "Submit a new harness candidate. The source code must define a "
                "run(problem) function. Include a rationale explaining your "
                "hypothesis for why this harness will improve on prior candidates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source_code": {
                        "type": "string",
                        "description": "Complete Python source code for the harness",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Explanation of the improvement hypothesis",
                    },
                },
                "required": ["source_code", "rationale"],
            },
            handler=self._submit_harness,
        ))

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
    ) -> list[HarnessCandidate]:
        """Run the proposer agent and collect submitted harness candidates.

        Returns a list of HarnessCandidate objects submitted via mh_submit_harness.
        """
        self._submitted = []

        # Build the frontier summary for the prompt
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
            # Prepend any reusable skills discovered so far
            skills_text = self._load_skills_text()
            prompt += (
                "\n\n## Pre-loaded Archive Digest\n\n"
                "The following is a compacted summary of ALL prior harnesses, "
                "their scores, error patterns, and source code. You can still "
                "use the archive tools for details, but this digest should have "
                "everything you need to propose improvements.\n\n"
                + (skills_text + "\n" if skills_text else "")
                + archive_digest
            )

        # CORAL: per-iteration reflect (always fires)
        prompt += build_reflect_prompt(iteration)

        # CORAL Tier 1: stagnation pivot — cooldown-protected
        # Only fire if stagnant >= threshold AND (never fired OR enough new stagnant iters since last fire)
        should_pivot = (
            stagnant_iterations >= stagnation_threshold
            and (pivot_fired_at is None or stagnant_iterations - pivot_fired_at >= stagnation_threshold)
        )
        if should_pivot and frontier.points:
            best_src = ""
            try:
                best_hid = frontier.points[0].harness_id
                raw = self.afs.read(self.search_agent_id, f"/harnesses/{best_hid}/source.py").decode()
                best_src = raw[:300] + ("..." if len(raw) > 300 else "")
            except Exception:
                pass
            prompt += build_pivot_prompt(stagnant_iterations, best_src)

        # CORAL Tier 2: consolidation heartbeat
        try:
            cfg_data = json.loads(self.afs.read(self.search_agent_id, "/config.json").decode())
            cons_interval = cfg_data.get("consolidation_interval", 5)
        except Exception:
            cons_interval = 5
        if iteration > 0 and iteration % cons_interval == 0:
            prompt += build_consolidation_prompt(iteration)

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
        This is the fallback for providers like claude --print that don't support
        structured tool calling.
        """
        import re

        python_block_re = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)

        for msg in reversed(conversation):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if not content:
                continue

            blocks = python_block_re.findall(content)
            for block in blocks:
                block = block.strip()
                if "def run(" not in block:
                    continue
                if len(self._submitted) >= max_candidates:
                    break

                candidate = HarnessCandidate.create(
                    source_code=block,
                    metadata={"source": "text_extraction", "rationale": "extracted from plain text response"},
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

    def _ls_archive(self, path: str = "/", **kwargs) -> str:
        """List files in the search agent's VFS."""
        try:
            entries = self.afs.ls(self.search_agent_id, path)
            return json.dumps(entries, indent=2)
        except Exception as e:
            return f"Error listing {path}: {e}"

    def _grep_archive(self, pattern: str, path: str = "/harnesses", file_glob: str = "", **kwargs) -> str:
        """Search file contents across the search agent's VFS."""
        try:
            entries = self.afs.ls(self.search_agent_id, path)
            matches = []
            pattern_lower = pattern.lower()

            for entry in entries:
                entry_path = entry.get("path", "")
                if entry.get("is_dir"):
                    # Recurse into subdirectories (one level)
                    try:
                        sub_entries = self.afs.ls(self.search_agent_id, entry_path)
                        for sub in sub_entries:
                            if sub.get("is_dir"):
                                continue
                            sub_path = sub.get("path", "")
                            if file_glob and not sub_path.endswith(file_glob):
                                continue
                            self._grep_file(sub_path, pattern_lower, matches)
                    except Exception:
                        continue
                else:
                    if file_glob and not entry_path.endswith(file_glob):
                        continue
                    self._grep_file(entry_path, pattern_lower, matches)

            if not matches:
                return f"No matches for '{pattern}' in {path}"
            # Cap output to avoid flooding context
            if len(matches) > 50:
                return "\n".join(matches[:50]) + f"\n... ({len(matches) - 50} more matches)"
            return "\n".join(matches)
        except Exception as e:
            return f"Error searching {path}: {e}"

    def _grep_file(self, path: str, pattern: str, matches: list) -> None:
        """Search a single file for a pattern."""
        try:
            content = self.afs.read(self.search_agent_id, path).decode("utf-8", errors="replace")
            for i, line in enumerate(content.split("\n"), 1):
                if pattern in line.lower():
                    matches.append(f"{path}:{i}: {line.strip()[:120]}")
        except Exception:
            pass

    def _read_archive(self, path: str, **kwargs) -> str:
        """Read a file from the search agent's VFS."""
        try:
            content = self.afs.read(self.search_agent_id, path)
            return content.decode("utf-8", errors="replace")
        except FileNotFoundError:
            return f"File not found: {path}"
        except Exception as e:
            return f"Error reading {path}: {e}"

    def _submit_harness(self, source_code: str, rationale: str = "", **kwargs) -> str:
        """Accept a harness submission from the proposer."""
        candidate = HarnessCandidate.create(
            source_code=source_code,
            metadata={"rationale": rationale},
        )

        # Validate interface before accepting
        valid, err = candidate.validate_interface()
        if not valid:
            return f"Rejected: {err}. Fix the harness and resubmit."

        self._submitted.append(candidate)
        return (
            f"Harness {candidate.harness_id[:12]}... accepted "
            f"({len(self._submitted)} submitted so far). "
            f"Validation passed: run() function found."
        )
