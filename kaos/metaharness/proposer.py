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
from kaos.metaharness.prompts import build_proposer_prompt

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

        prompt = build_proposer_prompt(
            iteration=iteration,
            n_candidates=n_candidates,
            benchmark_name=benchmark_name,
            objective_summary=objective_summary,
            frontier_summary=frontier_summary,
        )

        # Spawn and run the proposer agent
        config = {}
        if self.proposer_model:
            config["force_model"] = self.proposer_model

        agent_id = self.afs.spawn(
            f"proposer-iter-{iteration}",
            config=config,
        )

        try:
            await self.ccr.run_agent(agent_id, prompt)
        except Exception as e:
            logger.error("Proposer agent failed at iteration %d: %s", iteration, e)

        # Log the proposer conversation for debugging
        conversation = self.afs.get_state(agent_id, "conversation")
        if conversation:
            self.afs.write(
                self.search_agent_id,
                f"/iterations/{iteration}/proposer_conversation.json",
                json.dumps(conversation, indent=2).encode(),
            )

        # Set iteration on all submitted candidates
        for h in self._submitted:
            h.iteration = iteration

        logger.info(
            "Proposer iteration %d: %d candidates submitted",
            iteration, len(self._submitted),
        )
        return self._submitted

    # ── Archive tool handlers ────────────────────────────────────

    def _ls_archive(self, path: str = "/", **kwargs) -> str:
        """List files in the search agent's VFS."""
        try:
            entries = self.afs.ls(self.search_agent_id, path)
            return json.dumps(entries, indent=2)
        except Exception as e:
            return f"Error listing {path}: {e}"

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
