"""MCP Server — exposes KAOS as an MCP server for Claude Code integration.

Provides 25 tools covering:
- Agent lifecycle: spawn, spawn_only, kill, pause, resume, status
- Agent VFS: read, write, ls
- Checkpoints: checkpoint, restore, diff, list_checkpoints
- Query: SQL read-only queries
- Orchestration: parallel execution
- Meta-Harness: search, frontier, inspect
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from kaos.core import Kaos
from kaos.ccr.runner import ClaudeCodeRunner
from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)

# Module-level references set during server initialization
_afs: Kaos | None = None
_ccr: ClaudeCodeRunner | None = None

server = Server("kaos")


def init_server(afs: Kaos, ccr: ClaudeCodeRunner) -> Server:
    """Initialize the MCP server with Kaos and CCR instances."""
    global _afs, _ccr
    _afs = afs
    _ccr = ccr
    return server


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Kaos tools."""
    return [
        # ── Agent Lifecycle ──────────────────────────────────────
        Tool(
            name="agent_spawn",
            description="Spawn a new agent with an isolated virtual filesystem and run a task",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the agent"},
                    "task": {"type": "string", "description": "Task description for the agent to execute"},
                    "config": {"type": "object", "description": "Agent configuration (model, temperature, etc.)", "default": {}},
                },
                "required": ["name", "task"],
            },
        ),
        Tool(
            name="agent_spawn_only",
            description="Spawn a new agent without running it (returns agent_id for later use)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the agent"},
                    "config": {"type": "object", "description": "Agent configuration", "default": {}},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="agent_kill",
            description="Kill a running agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to kill"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_pause",
            description="Pause a running agent (can be resumed later)",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to pause"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_resume",
            description="Resume a paused agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to resume"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_status",
            description="Get status of one agent or list all agents. Omit agent_id to list all.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID (omit for all agents)"},
                    "status_filter": {"type": "string", "description": "Filter by status (running, completed, failed, paused, killed)"},
                },
            },
        ),
        # ── Agent VFS ────────────────────────────────────────────
        Tool(
            name="agent_read",
            description="Read a file from an agent's virtual filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["agent_id", "path"],
            },
        ),
        Tool(
            name="agent_write",
            description="Write a file to an agent's virtual filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["agent_id", "path", "content"],
            },
        ),
        Tool(
            name="agent_ls",
            description="List files in an agent's virtual filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "path": {"type": "string", "description": "Directory path", "default": "/"},
                },
                "required": ["agent_id"],
            },
        ),
        # ── Checkpoints ──────────────────────────────────────────
        Tool(
            name="agent_checkpoint",
            description="Create a snapshot of an agent's current state (files + KV store)",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "label": {"type": "string", "description": "Optional label for the checkpoint"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_restore",
            description="Restore an agent to a previous checkpoint",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "checkpoint_id": {"type": "string", "description": "Checkpoint ID to restore"},
                },
                "required": ["agent_id", "checkpoint_id"],
            },
        ),
        Tool(
            name="agent_diff",
            description="Compare two checkpoints — shows file changes, state changes, and tool calls between them",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "from_checkpoint": {"type": "string", "description": "Source checkpoint ID"},
                    "to_checkpoint": {"type": "string", "description": "Target checkpoint ID"},
                },
                "required": ["agent_id", "from_checkpoint", "to_checkpoint"],
            },
        ),
        Tool(
            name="agent_checkpoints",
            description="List all checkpoints for an agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                },
                "required": ["agent_id"],
            },
        ),
        # ── Query ────────────────────────────────────────────────
        Tool(
            name="agent_query",
            description="Run a read-only SQL query against the agent database (SELECT only)",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL SELECT query"},
                },
                "required": ["sql"],
            },
        ),
        # ── Orchestration ────────────────────────────────────────
        Tool(
            name="agent_parallel",
            description="Spawn and run multiple agents in parallel, each with its own isolated VFS",
            inputSchema={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "prompt": {"type": "string"},
                                "config": {"type": "object", "default": {}},
                            },
                            "required": ["name", "prompt"],
                        },
                        "description": "List of tasks to run in parallel",
                    },
                },
                "required": ["tasks"],
            },
        ),
        # ── Meta-Harness ────────────────────────────────────────
        Tool(
            name="mh_search",
            description="Run a Meta-Harness search to automatically optimize a harness for a benchmark. Returns the Pareto frontier of best harnesses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "benchmark": {
                        "type": "string",
                        "description": "Benchmark name: text_classify, math_rag, agentic_coding, or a custom registered benchmark",
                    },
                    "max_iterations": {"type": "integer", "description": "Number of search iterations", "default": 10},
                    "candidates_per_iteration": {"type": "integer", "description": "Candidates proposed per iteration", "default": 2},
                    "config": {"type": "object", "description": "Additional SearchConfig overrides", "default": {}},
                },
                "required": ["benchmark"],
            },
        ),
        Tool(
            name="mh_frontier",
            description="Get the Pareto frontier of a Meta-Harness search — the best harnesses found",
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string", "description": "Search agent ID from mh_search"},
                },
                "required": ["search_agent_id"],
            },
        ),
        Tool(
            name="mh_resume",
            description="Resume an interrupted Meta-Harness search from its last completed iteration. Restores all prior results and continues the search loop.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string", "description": "Search agent ID to resume"},
                    "benchmark": {"type": "string", "description": "Benchmark name (must match original search)"},
                },
                "required": ["search_agent_id", "benchmark"],
            },
        ),
        # ── Collaborative Meta-Harness ──────────────────────────
        Tool(
            name="mh_start_search",
            description=(
                "Start a collaborative Meta-Harness search. Evaluates seed harnesses "
                "and returns an archive digest. YOU (Claude Code) read the digest, "
                "write improved harness code, and submit it via mh_submit_candidate. "
                "Then call mh_next_iteration to evaluate and get the next digest. "
                "This avoids all subprocess/timeout issues — inference happens in "
                "YOUR session, zero extra cost."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "benchmark": {"type": "string", "description": "Benchmark name"},
                    "eval_subset": {"type": "integer", "description": "Subsample problems for faster eval"},
                    "compaction_level": {"type": "integer", "description": "Digest compaction 0-10", "default": 5},
                },
                "required": ["benchmark"],
            },
        ),
        Tool(
            name="mh_submit_candidate",
            description=(
                "Submit a harness candidate to a collaborative search. "
                "The source_code must define a def run(problem) function. "
                "Call mh_next_iteration after submitting to evaluate it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string", "description": "Search agent ID from mh_start_search"},
                    "source_code": {"type": "string", "description": "Complete Python source code with def run(problem)"},
                    "rationale": {"type": "string", "description": "Why this harness should improve on prior candidates"},
                },
                "required": ["search_agent_id", "source_code"],
            },
        ),
        Tool(
            name="mh_next_iteration",
            description=(
                "Evaluate all pending candidates submitted via mh_submit_candidate, "
                "update the Pareto frontier, and return the updated archive digest. "
                "Read the digest, propose new harnesses, submit via mh_submit_candidate, repeat."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string", "description": "Search agent ID"},
                    "compaction_level": {"type": "integer", "description": "Digest compaction 0-10", "default": 5},
                },
                "required": ["search_agent_id"],
            },
        ),
        # ── CORAL: Skills ────────────────────────────────────────
        Tool(
            name="mh_write_skill",
            description=(
                "Write a reusable skill (pattern/template) discovered during search. "
                "Skills are stored in the search agent VFS (/skills/) AND the persistent "
                "knowledge agent so future searches start with them. Call this during "
                "consolidation heartbeats or any time you discover a reliable pattern."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string"},
                    "name": {"type": "string", "description": "Skill identifier (snake_case)"},
                    "description": {"type": "string", "description": "What the skill does and when to use it"},
                    "code_template": {"type": "string", "description": "Code template or example (optional)"},
                },
                "required": ["search_agent_id", "name", "description"],
            },
        ),
        # ── CORAL: Co-Evolution ──────────────────────────────────
        Tool(
            name="mh_spawn_coevolution",
            description=(
                "Spawn N co-evolving search agents sharing a hub. Returns agent IDs and "
                "the hub ID. Drive each agent independently with mh_submit_candidate + "
                "mh_next_iteration. Call mh_hub_sync periodically to share discoveries "
                "across agents. Best results with N=2-4 agents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "benchmark": {"type": "string", "description": "Benchmark name"},
                    "n_agents": {"type": "integer", "default": 2, "description": "Number of co-evolving agents (2-4)"},
                    "eval_subset": {"type": "integer", "description": "Subsample problems per eval"},
                    "compaction_level": {"type": "integer", "default": 5},
                    "hub_sync_interval": {"type": "integer", "default": 2, "description": "Auto-sync every N iterations"},
                },
                "required": ["benchmark"],
            },
        ),
        Tool(
            name="mh_hub_sync",
            description=(
                "Push this agent's best harnesses + skills to the shared hub, and pull "
                "other agents' best discoveries into this agent's archive. Call every "
                "hub_sync_interval iterations to enable cross-agent learning. "
                "Only works for agents spawned with mh_spawn_coevolution."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string"},
                },
                "required": ["search_agent_id"],
            },
        ),
        # -- Cross-Agent Memory (claude-mem, Alex Newman @thedotmack) --
        Tool(
            name="agent_memory_write",
            description=(
                "Persist a memory entry to the shared cross-agent memory store. "
                "Any agent in this project can later retrieve it via agent_memory_search. "
                "Use type='result' for final outputs, 'skill' for reusable patterns, "
                "'observation' for runtime findings, 'insight' for analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent writing the memory"},
                    "content": {"type": "string", "description": "Free-text content to store (FTS5 indexed)"},
                    "type": {
                        "type": "string",
                        "enum": ["observation", "result", "skill", "insight", "error"],
                        "default": "observation",
                        "description": "Memory type",
                    },
                    "key": {"type": "string", "description": "Optional human-readable identifier"},
                    "metadata": {"type": "object", "description": "Extra JSON metadata", "default": {}},
                },
                "required": ["agent_id", "content"],
            },
        ),
        Tool(
            name="agent_memory_search",
            description=(
                "Full-text search across all agents' memory entries using SQLite FTS5 "
                "with porter stemming. Returns the most relevant entries ranked by BM25. "
                "Supports FTS5 query syntax: phrases, NOT, OR, wildcard *."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "FTS5 search query"},
                    "limit": {"type": "integer", "default": 10, "description": "Max results"},
                    "type": {
                        "type": "string",
                        "enum": ["observation", "result", "skill", "insight", "error"],
                        "description": "Filter by memory type (optional)",
                    },
                    "agent_id": {"type": "string", "description": "Restrict to one agent (optional)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="agent_memory_read",
            description="Read a single memory entry by its memory_id, or list recent entries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "integer", "description": "Specific memory_id to fetch (omit to list)"},
                    "agent_id": {"type": "string", "description": "Filter by agent (for listing)"},
                    "type": {
                        "type": "string",
                        "enum": ["observation", "result", "skill", "insight", "error"],
                        "description": "Filter by type (for listing)",
                    },
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        # -- Shared Log / LogAct (Balakrishnan et al. 2026, arXiv:2604.07988, Meta) --
        Tool(
            name="shared_log_intent",
            description=(
                "Broadcast an intent to the shared coordination log (LogAct Stage 1). "
                "Other agents vote on it before the action is taken. Returns the intent's log_id. "
                "After broadcasting, collect votes then call shared_log_decide."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent declaring the intent"},
                    "action": {"type": "string", "description": "Description of what the agent plans to do"},
                    "metadata": {"type": "object", "description": "Extra context", "default": {}},
                },
                "required": ["agent_id", "action"],
            },
        ),
        Tool(
            name="shared_log_vote",
            description=(
                "Cast a vote on an intent (LogAct Stage 2). "
                "approve=true to approve, false to reject."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Voting agent"},
                    "intent_id": {"type": "integer", "description": "log_id of the intent"},
                    "approve": {"type": "boolean", "description": "True = approve, False = reject"},
                    "reason": {"type": "string", "default": "", "description": "Optional rationale"},
                },
                "required": ["agent_id", "intent_id", "approve"],
            },
        ),
        Tool(
            name="shared_log_decide",
            description=(
                "Record the decision after vote tally (LogAct Stage 3). "
                "Returns passed=true/false and the vote counts. Idempotent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent recording the decision"},
                    "intent_id": {"type": "integer", "description": "log_id of the intent"},
                },
                "required": ["agent_id", "intent_id"],
            },
        ),
        Tool(
            name="shared_log_append",
            description=(
                "Append an entry to the shared coordination log. "
                "Use typed helpers (intent/vote/decide) for structured coordination. "
                "This tool handles commit, result, abort, policy, mail types."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["commit", "result", "abort", "policy", "mail"],
                        "description": "Entry type",
                    },
                    "payload": {"type": "object", "description": "Entry payload", "default": {}},
                    "ref_id": {"type": "integer", "description": "Reference to a prior log_id (optional)"},
                },
                "required": ["agent_id", "type"],
            },
        ),
        Tool(
            name="shared_log_read",
            description="Read entries from the shared coordination log in position order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "since_position": {"type": "integer", "default": 0},
                    "limit": {"type": "integer", "default": 50},
                    "type": {"type": "string", "description": "Filter by entry type"},
                    "agent_id": {"type": "string", "description": "Filter by agent"},
                    "tail": {"type": "integer", "description": "Return last N entries (overrides since_position)"},
                },
            },
        ),
        # -- Cross-Agent Skill Library (Zhou et al. 2026, arXiv:2604.08224) --
        Tool(
            name="skill_save",
            description=(
                "Save a reusable skill to the cross-agent skill library. "
                "Skills are procedural templates — parameterized patterns that encode "
                "reliable solution strategies. Use {param} placeholders in the template. "
                "Distinct from memory (episodic facts): skills are reusable procedures."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short snake_case identifier"},
                    "description": {"type": "string", "description": "What the skill does and when to use it"},
                    "template": {"type": "string", "description": "Prompt template with {param} placeholders"},
                    "source_agent_id": {"type": "string", "description": "Agent that discovered this skill"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topic tags for faceted search",
                        "default": [],
                    },
                },
                "required": ["name", "description", "template"],
            },
        ),
        Tool(
            name="skill_search",
            description=(
                "Search the cross-agent skill library using SQLite FTS5 with porter stemming. "
                "Searches across name, description, tags, and template. "
                "Returns skills ranked by BM25 relevance. "
                "Call this before starting a task to find relevant reusable patterns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "FTS5 search query"},
                    "limit": {"type": "integer", "default": 10, "description": "Max results"},
                    "tag": {"type": "string", "description": "Filter by exact tag (applied after FTS ranking)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="skill_apply",
            description=(
                "Render a skill template with parameters. "
                "Returns the filled prompt ready to use as agent instructions. "
                "Also records the use (increments use_count). "
                "Call skill_search first to find the right skill_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer", "description": "Skill ID from skill_search or skill_list"},
                    "params": {"type": "object", "description": "Parameter values for the template placeholders"},
                    "outcome": {
                        "type": "string",
                        "enum": ["success", "failure", "pending"],
                        "default": "pending",
                        "description": "Record outcome immediately (or use skill_outcome later)",
                    },
                },
                "required": ["skill_id"],
            },
        ),
        Tool(
            name="skill_list",
            description="List skills in the cross-agent skill library with optional filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "source_agent_id": {"type": "string", "description": "Filter by source agent"},
                    "order_by": {
                        "type": "string",
                        "enum": ["created_at", "success_count", "use_count", "name"],
                        "default": "created_at",
                    },
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="skill_outcome",
            description=(
                "Record whether applying a skill succeeded or failed. "
                "Increments use_count and (on success) success_count. "
                "Used to rank skills by reliability over time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer", "description": "Skill ID"},
                    "success": {"type": "boolean", "description": "True = succeeded, False = failed"},
                },
                "required": ["skill_id", "success"],
            },
        ),
        # ── Neuroplasticity / Dream (v0.8.0) ─────────────────────
        Tool(
            name="dream_run",
            description=(
                "Run one dream cycle (replay + weights + associations + failures + "
                "consolidation + policies + narrative). Returns a run_id and summary. "
                "Default mode is dry_run — pass apply=true to persist episode_signals "
                "and execute safe structural proposals (prune + promote)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "apply": {"type": "boolean", "default": False,
                              "description": "Apply safe proposals; False = dry-run only."},
                    "since_ts": {"type": "string",
                                 "description": "ISO timestamp to limit replay to agents created at/after."},
                },
            },
        ),
        Tool(
            name="dream_related",
            description=(
                "Hebbian association lookup. Given a skill or memory entity, return the "
                "top-N entities that most strongly co-fire with it (recency-decayed)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["skill", "memory"],
                             "description": "Entity kind"},
                    "id": {"type": "integer",
                           "description": "Entity id (skill_id or memory_id)"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["kind", "id"],
            },
        ),
        Tool(
            name="failure_lookup",
            description=(
                "Agent-time fast path: given a tool_name + error_message, return the "
                "matching failure fingerprint and any recorded fix. Agents should call "
                "this BEFORE invoking the LLM to diagnose a failure — if a known fix "
                "exists it can be applied directly."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                    "error_message": {"type": "string"},
                },
                "required": ["tool_name", "error_message"],
            },
        ),
        Tool(
            name="failure_list",
            description="List recurring failure fingerprints with count and fix status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_count": {"type": "integer", "default": 2,
                                  "description": "Only return fingerprints seen N+ times"},
                },
            },
        ),
        Tool(
            name="dream_consolidate",
            description=(
                "Identify structural consolidation proposals (promote memory→skill, "
                "prune low-success skills, merge near-duplicates). Safe proposals "
                "(prune, promote) execute in apply mode; merges always stay as "
                "proposals for human review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "apply": {"type": "boolean", "default": False},
                    "merge_threshold": {"type": "number", "default": 0.65,
                                         "description": "Jaccard similarity threshold for merge proposals"},
                },
            },
        ),
        Tool(
            name="dream_merges",
            description=(
                "List pending merge proposals; accept or reject by proposal_id. "
                "Merge proposals are never auto-applied — a human (or an agent "
                "with explicit authority) reviews each one. Accept migrates "
                "skill_uses, collapses associations, rolls counters, and soft-"
                "deprecates the retired skill. Reject marks the proposal so it "
                "does not re-appear in the pending list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "accept": {"type": "integer",
                               "description": "proposal_id to accept"},
                    "reject": {"type": "integer",
                               "description": "proposal_id to reject"},
                    "keep": {"type": "integer",
                             "description": "When accepting: skill_id to keep "
                                            "(default: lower id)"},
                    "reason": {"type": "string",
                               "description": "When rejecting: stored rationale"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        # ── Failure intelligence (M2.5) ──────────────────────────
        Tool(
            name="failure_diagnose",
            description=(
                "Return the diagnosis for a failure fingerprint (category, root "
                "cause, suggested action) or manually set one. Categories: "
                "transient (retry), config (human action), code (pattern bug), "
                "infra (systemic), unknown (needs triage)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fp_id": {"type": "integer", "description": "Fingerprint id"},
                    "category": {
                        "type": "string",
                        "enum": ["transient", "config", "code", "infra", "unknown"],
                        "description": "Override the category (optional)",
                    },
                    "root_cause": {"type": "string"},
                    "suggested_action": {"type": "string"},
                },
                "required": ["fp_id"],
            },
        ),
        Tool(
            name="failure_fix_outcome",
            description=(
                "Record whether a previously-suggested fix actually resolved "
                "the error. Agents should call this after trying a known fix. "
                "Fixes that drop below 50% success after 5+ attempts auto-"
                "downgrade so future agents stop applying broken suggestions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fp_id": {"type": "integer"},
                    "succeeded": {"type": "boolean"},
                },
                "required": ["fp_id", "succeeded"],
            },
        ),
        Tool(
            name="systemic_alerts",
            description=(
                "List active systemic alerts. An alert fires when >=N agents "
                "hit the same fingerprint in a short window — usually means "
                "infrastructure is down and auto-spawning more agents will "
                "make it worse. Callers should refuse to spawn when alerts "
                "are unresolved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "ack": {"type": "integer",
                            "description": "Acknowledge alert by id"},
                    "resolve": {"type": "integer",
                                "description": "Resolve alert by id"},
                    "by": {"type": "string",
                           "description": "Who is acking/resolving"},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle MCP tool calls."""
    assert _afs is not None, "Server not initialized — call init_server() first"

    try:
        result = await _dispatch(name, arguments)
        return [TextContent(type="text", text=result)]
    except Exception as e:
        logger.exception("Tool call failed: %s", name)
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


def _import_benchmarks() -> None:
    """Import all benchmark modules to trigger registration."""
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    try:
        import kaos.metaharness.benchmarks.arc_agi3  # noqa: F401
    except ImportError:
        pass


def _do_hub_sync(search_agent_id: str, hub_id: str, afs: Kaos) -> dict:
    """CORAL Tier 3: push this agent's best harnesses+skills to hub, pull others' best.

    Synchronous — called from mh_hub_sync and auto-triggered in mh_next_iteration.
    Returns a summary dict with pushed/pulled counts.
    """
    agent_index = afs.get_state_or(search_agent_id, "agent_index") or 0
    n_agents = afs.get_state_or(hub_id, "n_agents") or 1
    iteration = afs.get_state_or(search_agent_id, "current_iteration") or 0
    pushed_harnesses: list[str] = []
    pulled_harnesses: list[str] = []

    # ── Push: best harnesses → hub ──────────────────────────────
    try:
        frontier_data = json.loads(afs.read(search_agent_id, "/pareto/frontier.json").decode())
        for point in frontier_data.get("points", [])[:3]:
            hid = point["harness_id"]
            try:
                src = afs.read(search_agent_id, f"/harnesses/{hid}/source.py")
                scores_b = afs.read(search_agent_id, f"/harnesses/{hid}/scores.json")
                afs.write(hub_id, f"/best_per_agent/agent_{agent_index}/{hid}.py", src)
                afs.write(hub_id, f"/best_per_agent/agent_{agent_index}/{hid}.scores.json", scores_b)
                pushed_harnesses.append(hid[:12])
            except Exception:
                pass
    except Exception:
        pass

    # ── Push: skills → hub ──────────────────────────────────────
    try:
        for se in afs.ls(search_agent_id, "/skills"):
            if se.get("is_dir") or not se["path"].endswith(".json"):
                continue
            try:
                afs.write(hub_id, f"/shared_skills/{se['name']}", afs.read(search_agent_id, se["path"]))
            except Exception:
                pass
    except Exception:
        pass

    # ── Pull: other agents' best → this archive ─────────────────
    for other_idx in range(n_agents):
        if other_idx == agent_index:
            continue
        try:
            other_dir = f"/best_per_agent/agent_{other_idx}"
            for fe in afs.ls(hub_id, other_dir):
                if fe.get("is_dir") or not fe["path"].endswith(".py"):
                    continue
                hid = fe["name"].replace(".py", "")
                if _agent_has_harness(afs, search_agent_id, hid):
                    continue
                try:
                    src = afs.read(hub_id, fe["path"])
                    scores_path = fe["path"].replace(".py", ".scores.json")
                    scores_b = afs.read(hub_id, scores_path)
                    afs.write(search_agent_id, f"/harnesses/{hid}/source.py", src)
                    afs.write(search_agent_id, f"/harnesses/{hid}/scores.json", scores_b)
                    afs.write(search_agent_id, f"/harnesses/{hid}/metadata.json",
                              json.dumps({"harness_id": hid, "iteration": iteration,
                                          "metadata": {"source": f"hub_agent_{other_idx}"},
                                          "is_success": True, "error": None,
                                          "duration_ms": 0}, indent=2).encode())
                    pulled_harnesses.append(hid[:12])
                except Exception:
                    pass
        except Exception:
            pass

    # ── Pull: shared skills ──────────────────────────────────────
    try:
        for se in afs.ls(hub_id, "/shared_skills"):
            if se.get("is_dir") or not se["path"].endswith(".json"):
                continue
            try:
                afs.write(search_agent_id, f"/skills/{se['name']}", afs.read(hub_id, se["path"]))
            except Exception:
                pass
    except Exception:
        pass

    return {
        "status": "synced",
        "agent_index": agent_index,
        "pushed_harnesses": pushed_harnesses,
        "pulled_harnesses": pulled_harnesses,
        "iteration": iteration,
        "message": (
            f"Pushed {len(pushed_harnesses)} harnesses, "
            f"pulled {len(pulled_harnesses)} from other agents. "
            "Pulled harnesses appear in the next digest."
        ),
    }


def _agent_has_harness(afs: Kaos, agent_id: str, harness_id: str) -> bool:
    """Check if agent already has a harness stored (avoid duplicate imports)."""
    try:
        afs.read(agent_id, f"/harnesses/{harness_id}/scores.json")
        return True
    except Exception:
        return False


async def _dispatch(name: str, args: dict[str, Any]) -> str:
    """Dispatch a tool call to the appropriate handler."""
    assert _afs is not None
    assert _ccr is not None

    # ── Agent Lifecycle ──────────────────────────────────────
    if name == "agent_spawn":
        agent_id = _afs.spawn(name=args["name"], config=args.get("config", {}))
        result = await _ccr.run_agent(agent_id, args["task"])
        # Store full result in VFS for large outputs; return truncated preview
        if len(result) > 4000:
            _afs.write(agent_id, "/result.txt", result.encode("utf-8", errors="replace"))
            return json.dumps({
                "agent_id": agent_id,
                "result_preview": result[:3500] + "\n\n... [truncated — full result in agent VFS /result.txt]",
                "result_size": len(result),
                "full_result_path": f"Use agent_read(agent_id='{agent_id}', path='/result.txt') for the full output",
            }, indent=2)
        return json.dumps({"agent_id": agent_id, "result": result}, indent=2)

    elif name == "agent_spawn_only":
        agent_id = _afs.spawn(name=args["name"], config=args.get("config", {}))
        return json.dumps({"agent_id": agent_id, "status": "initialized"}, indent=2)

    elif name == "agent_kill":
        _afs.kill(args["agent_id"])
        return f"Agent {args['agent_id']} killed"

    elif name == "agent_pause":
        _afs.pause(args["agent_id"])
        return f"Agent {args['agent_id']} paused"

    elif name == "agent_resume":
        _afs.resume(args["agent_id"])
        return f"Agent {args['agent_id']} resumed"

    elif name == "agent_status":
        if args.get("agent_id"):
            return json.dumps(_afs.status(args["agent_id"]), indent=2)
        return json.dumps(
            _afs.list_agents(status_filter=args.get("status_filter")), indent=2
        )

    # ── Agent VFS ────────────────────────────────────────────
    elif name == "agent_read":
        content = _afs.read(args["agent_id"], args["path"])
        return content.decode("utf-8", errors="replace")

    elif name == "agent_write":
        _afs.write(args["agent_id"], args["path"], args["content"].encode())
        return f"Written {len(args['content'])} bytes to {args['agent_id']}:{args['path']}"

    elif name == "agent_ls":
        entries = _afs.ls(args["agent_id"], args.get("path", "/"))
        return json.dumps(entries, indent=2)

    # ── Checkpoints ──────────────────────────────────────────
    elif name == "agent_checkpoint":
        cp_id = _afs.checkpoint(args["agent_id"], label=args.get("label"))
        return f"Checkpoint {cp_id} created for agent {args['agent_id']}"

    elif name == "agent_restore":
        _afs.restore(args["agent_id"], args["checkpoint_id"])
        return f"Agent {args['agent_id']} restored to checkpoint {args['checkpoint_id']}"

    elif name == "agent_diff":
        diff = _afs.diff_checkpoints(
            args["agent_id"], args["from_checkpoint"], args["to_checkpoint"]
        )
        return json.dumps(diff, indent=2)

    elif name == "agent_checkpoints":
        checkpoints = _afs.list_checkpoints(args["agent_id"])
        return json.dumps(checkpoints, indent=2)

    # ── Query ────────────────────────────────────────────────
    elif name == "agent_query":
        results = _afs.query(args["sql"])
        return json.dumps(results, indent=2)

    # ── Orchestration ────────────────────────────────────────
    elif name == "agent_parallel":
        results = await _ccr.run_parallel(args["tasks"])
        return json.dumps(
            [{"index": i, "result": r} for i, r in enumerate(results)],
            indent=2,
        )

    # ── Meta-Harness ────────────────────────────────────────
    elif name == "mh_search":
        import subprocess as _sp

        benchmark_name = args["benchmark"]
        config_file = args.get("config_file", "") or os.environ.get("KAOS_CONFIG", "./kaos.yaml")

        # Launch as a detached worker process — completely decoupled from
        # the MCP event loop. If the MCP connection drops, the worker continues.
        cmd = [
            sys.executable, "-m", "kaos.metaharness.worker",
            "--db", _afs.db_path,
            "--config-file", config_file,
            "--benchmark", benchmark_name,
            "--iterations", str(args.get("max_iterations", 10)),
            "--candidates", str(args.get("candidates_per_iteration", 2)),
            "--max-parallel", str(args.get("config", {}).get("max_parallel_evals", 4)),
        ]
        eval_subset = args.get("config", {}).get("eval_subset_size")
        if eval_subset:
            cmd += ["--eval-subset", str(eval_subset)]
        proposer_model = args.get("config", {}).get("proposer_model")
        if proposer_model:
            cmd += ["--proposer-model", proposer_model]

        # Strip CLAUDECODE so nested claude subprocess works
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        kwargs: dict[str, Any] = {"env": env}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        import time as _time
        log_dir = os.path.dirname(os.path.abspath(_afs.db_path))
        log_path = os.path.join(log_dir, f"kaos-worker-{int(_time.time())}.log")
        log_file = open(log_path, "w")
        proc = _sp.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)
        logger.info("MH search worker launched: PID %d, log=%s", proc.pid, log_path)

        return json.dumps({
            "status": "running",
            "pid": proc.pid,
            "log_path": log_path,
            "message": (
                f"Search worker launched (PID {proc.pid}). "
                f"Log: {log_path}. "
                "Poll with mh_frontier or agent_status."
            ),
        }, indent=2)

    elif name == "mh_frontier":
        search_agent_id = args["search_agent_id"]
        info = _afs.status(search_agent_id)
        iteration = _afs.get_state_or(search_agent_id, "current_iteration", 0)

        # Build a rich status response
        result: dict[str, Any] = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "current_iteration": iteration,
        }

        # Frontier data (may not exist yet if seeds are still evaluating)
        try:
            frontier = json.loads(
                _afs.read(search_agent_id, "/pareto/frontier.json").decode()
            )
            result["frontier"] = frontier
        except FileNotFoundError:
            result["frontier"] = None
            result["message"] = "Frontier not yet computed — seeds may still be evaluating."

        # Count harnesses evaluated so far
        harness_dirs = _afs.ls(search_agent_id, "/harnesses")
        result["harnesses_evaluated"] = len(harness_dirs)

        return json.dumps(result, indent=2)

    elif name == "mh_resume":
        import subprocess as _sp

        search_agent_id = args["search_agent_id"]
        benchmark_name = args["benchmark"]
        config_file = os.environ.get("KAOS_CONFIG", "./kaos.yaml")

        cmd = [
            sys.executable, "-m", "kaos.metaharness.worker",
            "--db", _afs.db_path,
            "--config-file", config_file,
            "--benchmark", benchmark_name,
            "--search-agent-id", search_agent_id,
        ]

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        kwargs: dict[str, Any] = {"env": env}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        import time as _time
        log_dir = os.path.dirname(os.path.abspath(_afs.db_path))
        log_path = os.path.join(log_dir, f"kaos-worker-{int(_time.time())}.log")
        log_file = open(log_path, "w")
        proc = _sp.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)
        logger.info("MH resume worker launched: PID %d, log=%s", proc.pid, log_path)

        return json.dumps({
            "search_agent_id": search_agent_id,
            "status": "resuming",
            "pid": proc.pid,
            "log_path": log_path,
            "message": f"Resume worker launched (PID {proc.pid}). Log: {log_path}.",
        }, indent=2)

    # ── Collaborative Meta-Harness ────────────────────────────
    elif name == "mh_start_search":
        from kaos.metaharness.harness import SearchConfig, HarnessCandidate
        from kaos.metaharness.search import MetaHarnessSearch
        from kaos.metaharness.benchmarks import get_benchmark
        from kaos.metaharness.compactor import Compactor
        _import_benchmarks()

        benchmark_name = args["benchmark"]
        bench = get_benchmark(benchmark_name)
        eval_subset = args.get("eval_subset")
        compaction_level = args.get("compaction_level", 5)

        config = SearchConfig(
            benchmark=benchmark_name,
            eval_subset_size=eval_subset,
            compaction_level=compaction_level,
        )

        search = MetaHarnessSearch(_afs, _ccr.router, bench, config)

        # Step 1: init archive + evaluate seeds
        import asyncio as _asyncio
        search.search_agent_id = search._init_archive()
        seeds = search._load_seeds()

        problems = bench.get_search_set()
        if eval_subset:
            problems = bench.get_subset(problems, eval_subset)

        seed_results = await search.evaluator.evaluate_parallel(
            seeds, problems=problems,
            max_parallel=config.max_parallel_evals,
        )
        for harness, result in zip(seeds, seed_results):
            search._store_result(harness, result, iteration=0)

        frontier = search._compute_frontier()
        search._store_frontier(frontier, iteration=0)
        _afs.set_state(search.search_agent_id, "current_iteration", 0)
        _afs.set_state(search.search_agent_id, "pending_candidates", [])
        _afs.set_state(search.search_agent_id, "collaborative", True)
        _afs.set_state(search.search_agent_id, "benchmark", benchmark_name)
        # CORAL stagnation state init
        _afs.set_state(search.search_agent_id, "stagnant_iterations", 0)
        _afs.set_state(search.search_agent_id, "prev_best_scores", {})
        _afs.set_state(search.search_agent_id, "prev_frontier_size", 0)

        # Build digest for Claude Code to read
        compactor = Compactor(level=compaction_level)
        harness_data = []
        for harness, result in zip(seeds, seed_results):
            harness_data.append({
                "harness_id": harness.harness_id,
                "iteration": 0,
                "scores": result.scores,
                "source": harness.source_code,
                "per_problem": result.per_problem,
                "error": result.error,
            })
        digest, metrics = compactor.build_digest(harness_data, frontier.to_dict())

        return json.dumps({
            "search_agent_id": search.search_agent_id,
            "status": "seeds_evaluated",
            "seeds_evaluated": len(seeds),
            "frontier_size": len(frontier.points),
            "digest_chars": metrics.compacted_chars,
            "compaction_savings": f"{metrics.savings_pct:.0f}%",
            "digest": digest,
            "instructions": (
                "Read the digest above. Write an improved harness as a Python function "
                "def run(problem) that fixes the failure modes you see. "
                "Submit it with mh_submit_candidate(search_agent_id, source_code, rationale). "
                "Then call mh_next_iteration(search_agent_id) to evaluate and get the next digest."
            ),
        }, indent=2)

    elif name == "mh_submit_candidate":
        from kaos.metaharness.harness import HarnessCandidate

        search_agent_id = args["search_agent_id"]
        source_code = args["source_code"]
        rationale = args.get("rationale", "")

        candidate = HarnessCandidate.create(
            source_code=source_code,
            metadata={"rationale": rationale, "source": "collaborative"},
        )

        valid, err = candidate.validate_interface()
        if not valid:
            return json.dumps({"error": f"Invalid harness: {err}. Fix and resubmit."})

        # CORAL Tier 2: persist notes if provided
        notes = args.get("notes", "")
        if notes:
            iteration = (_afs.get_state_or(search_agent_id, "current_iteration") or 0) + 1
            note_path = f"/notes/iter_{iteration}_{candidate.harness_id[:8]}.md"
            try:
                _afs.write(search_agent_id, note_path, notes.encode())
            except Exception as e:
                logger.warning("Failed to write notes: %s", e)

        # Store in pending list
        pending = _afs.get_state_or(search_agent_id, "pending_candidates", [])
        pending.append(candidate.to_dict())
        _afs.set_state(search_agent_id, "pending_candidates", pending)

        return json.dumps({
            "status": "accepted",
            "harness_id": candidate.harness_id,
            "pending_count": len(pending),
            "message": f"Harness accepted ({len(pending)} pending). Call mh_next_iteration to evaluate.",
        }, indent=2)

    elif name == "mh_next_iteration":
        from kaos.metaharness.harness import HarnessCandidate, SearchConfig
        from kaos.metaharness.evaluator import HarnessEvaluator
        from kaos.metaharness.benchmarks import get_benchmark
        from kaos.metaharness.compactor import Compactor
        from kaos.metaharness.pareto import compute_pareto
        _import_benchmarks()

        search_agent_id = args["search_agent_id"]
        compaction_level = args.get("compaction_level", 5)

        # Load pending candidates
        pending_dicts = _afs.get_state_or(search_agent_id, "pending_candidates", [])
        if not pending_dicts:
            return json.dumps({"error": "No pending candidates. Submit harnesses with mh_submit_candidate first."})

        candidates = [HarnessCandidate.from_dict(d) for d in pending_dicts]
        iteration = (_afs.get_state_or(search_agent_id, "current_iteration", 0) or 0) + 1

        # Get benchmark
        benchmark_name = _afs.get_state_or(search_agent_id, "benchmark", "text_classify")
        bench = get_benchmark(benchmark_name)

        # Read config
        try:
            config_data = json.loads(_afs.read(search_agent_id, "/config.json").decode())
            config = SearchConfig.from_dict(config_data)
        except FileNotFoundError:
            config = SearchConfig(benchmark=benchmark_name)
        if config.objectives is None:
            config.objectives = bench.objectives

        # Evaluate
        evaluator = HarnessEvaluator(
            _afs, _ccr.router, bench,
            timeout_seconds=config.harness_timeout_seconds,
        )
        problems = bench.get_search_set()
        if config.eval_subset_size:
            problems = bench.get_subset(problems, config.eval_subset_size)

        results = await evaluator.evaluate_parallel(
            candidates, problems=problems,
            max_parallel=config.max_parallel_evals,
        )

        # Store results in archive
        for harness, result in zip(candidates, results):
            harness.iteration = iteration
            hid = harness.harness_id
            base = f"/harnesses/{hid}"
            _afs.write(search_agent_id, f"{base}/source.py", harness.source_code.encode())
            _afs.write(search_agent_id, f"{base}/scores.json", result.to_scores_json().encode())
            if result.per_problem:
                _afs.write(search_agent_id, f"{base}/per_problem.jsonl",
                           "\n".join(json.dumps(p) for p in result.per_problem).encode())
            _afs.write(search_agent_id, f"{base}/metadata.json", json.dumps({
                "harness_id": hid, "iteration": iteration,
                "metadata": harness.metadata,
                "is_success": result.is_success, "error": result.error,
                "duration_ms": result.duration_ms,
            }, indent=2).encode())
            # Store verifier diagnosis
            if hasattr(result, "diagnosis") and result.diagnosis:
                _afs.write(search_agent_id, f"{base}/diagnosis.json",
                           json.dumps(result.diagnosis.to_dict(), indent=2).encode())

        # Recompute frontier from ALL harnesses
        all_scores_files = [
            f["path"] for f in _afs.query(
                f"SELECT path FROM files WHERE agent_id='{search_agent_id}' "
                f"AND path LIKE '/harnesses/%/scores.json' AND deleted=0"
            )
        ]
        all_results_for_pareto = []
        from kaos.metaharness.harness import EvaluationResult
        for path in all_scores_files:
            hid = path.split("/")[2]
            try:
                scores = json.loads(_afs.read(search_agent_id, path).decode())
                if scores:
                    all_results_for_pareto.append(EvaluationResult(harness_id=hid, scores=scores))
            except Exception:
                pass

        objectives = config.objective_directions()
        frontier = compute_pareto(all_results_for_pareto, objectives)

        # Store frontier
        _afs.write(search_agent_id, "/pareto/frontier.json",
                   json.dumps(frontier.to_dict(), indent=2).encode())

        # CORAL Tier 1: stagnation detection with plateau cooldown
        from kaos.metaharness.prompts import build_pivot_prompt, build_consolidation_prompt, build_reflect_prompt
        prev_best: dict = _afs.get_state_or(search_agent_id, "prev_best_scores") or {}
        stagnant: int = _afs.get_state_or(search_agent_id, "stagnant_iterations") or 0
        pivot_fired_at: int | None = _afs.get_state_or(search_agent_id, "pivot_fired_at")
        curr_best: dict = {}
        for obj_name in objectives:
            vals = [p.scores.get(obj_name, 0.0) for p in frontier.points]
            curr_best[obj_name] = max(vals) if vals else 0.0
        epsilon = 0.001
        frontier_improved = any(
            abs(curr_best.get(o, 0.0) - prev_best.get(o, 0.0)) > epsilon for o in curr_best
        ) or (len(frontier.points) > (_afs.get_state_or(search_agent_id, "prev_frontier_size") or 0))
        if frontier_improved:
            stagnant = 0
            pivot_fired_at = None
        else:
            stagnant += 1
        _afs.set_state(search_agent_id, "stagnant_iterations", stagnant)
        _afs.set_state(search_agent_id, "prev_best_scores", curr_best)
        _afs.set_state(search_agent_id, "prev_frontier_size", len(frontier.points))
        # Update pivot_fired_at: fire when stagnant >= threshold and cooldown expired
        stagnation_threshold = config.stagnation_threshold
        should_pivot = (
            stagnant >= stagnation_threshold
            and (pivot_fired_at is None or stagnant - pivot_fired_at >= stagnation_threshold)
        )
        if should_pivot:
            _afs.set_state(search_agent_id, "pivot_fired_at", stagnant)
            pivot_fired_at = stagnant
        elif frontier_improved:
            _afs.set_state(search_agent_id, "pivot_fired_at", None)
        delta = {"prev_best": prev_best, "curr_best": curr_best,
                 "stagnant_iterations": stagnant, "frontier_improved": frontier_improved}

        _afs.set_state(search_agent_id, "current_iteration", iteration)
        _afs.set_state(search_agent_id, "pending_candidates", [])  # clear pending

        # CORAL Tier 3: auto hub-sync if this agent is part of a co-evolution run
        hub_id = _afs.get_state_or(search_agent_id, "hub_id")
        hub_sync_interval = _afs.get_state_or(search_agent_id, "hub_sync_interval") or 2
        if hub_id and iteration % hub_sync_interval == 0:
            _do_hub_sync(search_agent_id, hub_id, _afs)

        # Build updated digest
        harness_data = []
        for path in all_scores_files:
            hid = path.split("/")[2]
            h: dict[str, Any] = {"harness_id": hid}
            try:
                h["scores"] = json.loads(_afs.read(search_agent_id, path).decode())
            except Exception:
                h["scores"] = {}
            try:
                meta = json.loads(_afs.read(search_agent_id, f"/harnesses/{hid}/metadata.json").decode())
                h["iteration"] = meta.get("iteration", 0)
                h["error"] = meta.get("error")
            except FileNotFoundError:
                h["iteration"] = 0
            try:
                h["source"] = _afs.read(search_agent_id, f"/harnesses/{hid}/source.py").decode()
            except FileNotFoundError:
                h["source"] = ""
            try:
                pp = _afs.read(search_agent_id, f"/harnesses/{hid}/per_problem.jsonl").decode()
                h["per_problem"] = [json.loads(l) for l in pp.strip().split("\n") if l.strip()]
            except FileNotFoundError:
                h["per_problem"] = []
            harness_data.append(h)

        compactor = Compactor(level=compaction_level)

        # CORAL Tier 2: load skills and prepend to harness context
        skills_prefix = ""
        try:
            skill_entries = _afs.ls(search_agent_id, "/skills")
            skill_lines = []
            for se in skill_entries[:10]:  # cap at 10 to avoid context bloat
                if se.get("is_dir") or not se["path"].endswith(".json"):
                    continue
                try:
                    sk = json.loads(_afs.read(search_agent_id, se["path"]).decode())
                    skill_lines.append(f"- **{sk['name']}**: {sk['description']}")
                    if sk.get("code_template"):
                        skill_lines.append(f"  ```python\n  {sk['code_template'][:200]}\n  ```")
                except Exception:
                    continue
            if skill_lines:
                skills_prefix = "## Reusable Skills\n\n" + "\n".join(skill_lines) + "\n\n"
        except Exception:
            pass

        digest, metrics = compactor.build_digest(harness_data, frontier.to_dict())

        # Results + diagnoses for this iteration
        iter_results = []
        diagnoses = []
        for harness, result in zip(candidates, results):
            iter_results.append({
                "harness_id": harness.harness_id,
                "scores": result.scores,
                "is_success": result.is_success,
                "error": result.error,
            })
            if hasattr(result, "diagnosis") and result.diagnosis:
                diagnoses.append(result.diagnosis.to_text())
            # CORAL Tier 2: write to /attempts/ with status field
            try:
                ep = 0.001
                if not prev_best:
                    attempt_status = "neutral"
                elif any(result.scores.get(o, 0.0) - prev_best.get(o, 0.0) > ep for o in result.scores):
                    attempt_status = "improved"
                elif any(prev_best.get(o, 0.0) - result.scores.get(o, 0.0) > ep for o in result.scores):
                    attempt_status = "regression"
                else:
                    attempt_status = "neutral"
                _afs.write(search_agent_id, f"/attempts/{harness.harness_id}.json",
                           json.dumps({
                               "harness_id": harness.harness_id, "iteration": iteration,
                               "scores": result.scores, "status": attempt_status,
                               "is_success": result.is_success, "error": result.error,
                               "approach": harness.source_code[:200],
                               "rationale": harness.metadata.get("rationale", ""),
                           }, indent=2).encode())
            except Exception:
                pass

        diagnosis_text = ""
        if diagnoses:
            diagnosis_text = "\n\n## Verifier Diagnosis\n\n" + "\n\n".join(diagnoses)

        # CORAL: per-iteration reflect (always fires)
        reflect_text = build_reflect_prompt(iteration)

        # CORAL Tier 1: pivot prompt — cooldown-protected (only fires when should_pivot)
        pivot_text = ""
        if should_pivot:
            best_src = ""
            if frontier.points:
                try:
                    raw = _afs.read(search_agent_id, f"/harnesses/{frontier.points[0].harness_id}/source.py").decode()
                    best_src = raw[:300] + ("..." if len(raw) > 300 else "")
                except Exception:
                    pass
            pivot_text = build_pivot_prompt(stagnant, best_src)

        # CORAL Tier 2: consolidation heartbeat
        consolidation_text = ""
        cons_interval = config.consolidation_interval
        if iteration > 0 and iteration % cons_interval == 0:
            consolidation_text = build_consolidation_prompt(iteration)

        full_digest = skills_prefix + digest + diagnosis_text + reflect_text + pivot_text + consolidation_text

        return json.dumps({
            "search_agent_id": search_agent_id,
            "iteration": iteration,
            "evaluated": len(candidates),
            "results": iter_results,
            "frontier_size": len(frontier.points),
            "total_harnesses": len(all_scores_files),
            "stagnant_iterations": stagnant,
            "delta": delta,
            "digest": full_digest,
            "instructions": (
                "Read the updated digest, verifier diagnosis, and any pivot/consolidation prompts above. "
                "Propose improved harnesses and submit with mh_submit_candidate(search_agent_id, source_code, "
                "rationale, notes='...your observations...'). "
                "Use mh_write_skill(search_agent_id, name, description) to record reusable patterns. "
                "Then call mh_next_iteration again."
            ),
        }, indent=2)

    elif name == "mh_write_skill":
        search_agent_id = args["search_agent_id"]
        skill_name = args["name"].replace(" ", "_").lower()
        skill_data = {
            "name": skill_name,
            "description": args["description"],
            "code_template": args.get("code_template", ""),
            "created_at_iteration": _afs.get_state_or(search_agent_id, "current_iteration") or 0,
        }
        payload = json.dumps(skill_data, indent=2).encode()
        _afs.write(search_agent_id, f"/skills/{skill_name}.json", payload)
        # Persist to knowledge agent
        try:
            knowledge_id = _afs.get_or_create_singleton("kaos-knowledge")
            benchmark_name = _afs.get_state_or(search_agent_id, "benchmark") or "unknown"
            _afs.write(knowledge_id, f"/skills/{benchmark_name}/{skill_name}.json", payload)
        except Exception as e:
            logger.warning("Failed to persist skill to knowledge agent: %s", e)
        return json.dumps({"status": "ok", "skill": skill_name,
                           "message": f"Skill '{skill_name}' saved and persisted to knowledge agent."}, indent=2)

    elif name == "mh_spawn_coevolution":
        from kaos.metaharness.harness import SearchConfig
        from kaos.metaharness.search import MetaHarnessSearch
        from kaos.metaharness.benchmarks import get_benchmark
        from kaos.metaharness.compactor import Compactor
        _import_benchmarks()

        benchmark_name = args["benchmark"]
        n_agents = args.get("n_agents", 2)
        eval_subset = args.get("eval_subset")
        compaction_level = args.get("compaction_level", 5)
        hub_sync_interval = args.get("hub_sync_interval", 2)

        bench = get_benchmark(benchmark_name)

        # Create hub agent
        hub_id = _afs.spawn("mh-hub", config={"benchmark": benchmark_name})
        _afs.mkdir(hub_id, "/best_per_agent")
        _afs.mkdir(hub_id, "/shared_skills")
        _afs.mkdir(hub_id, "/shared_attempts")
        _afs.set_state(hub_id, "benchmark", benchmark_name)
        _afs.set_state(hub_id, "n_agents", n_agents)

        search_agent_ids = []
        seed_digests = []
        for i in range(n_agents):
            config_i = SearchConfig(
                benchmark=benchmark_name,
                eval_subset_size=eval_subset,
                compaction_level=compaction_level,
            )
            search_i = MetaHarnessSearch(_afs, _ccr.router, bench, config_i)
            search_i.search_agent_id = search_i._init_archive()

            seeds_i = search_i._load_seeds()
            problems_i = bench.get_search_set()
            if eval_subset:
                problems_i = bench.get_subset(problems_i, eval_subset)

            seed_results_i = await search_i.evaluator.evaluate_parallel(
                seeds_i, problems=problems_i, max_parallel=config_i.max_parallel_evals,
            )
            for h, r in zip(seeds_i, seed_results_i):
                search_i._store_result(h, r, iteration=0)

            frontier_i = search_i._compute_frontier()
            search_i._store_frontier(frontier_i, iteration=0)

            sid = search_i.search_agent_id
            _afs.set_state(sid, "current_iteration", 0)
            _afs.set_state(sid, "pending_candidates", [])
            _afs.set_state(sid, "collaborative", True)
            _afs.set_state(sid, "benchmark", benchmark_name)
            _afs.set_state(sid, "hub_id", hub_id)
            _afs.set_state(sid, "hub_sync_interval", hub_sync_interval)
            _afs.set_state(sid, "agent_index", i)
            _afs.set_state(sid, "stagnant_iterations", 0)
            _afs.set_state(sid, "prev_best_scores", {})
            _afs.set_state(sid, "prev_frontier_size", 0)
            search_agent_ids.append(sid)

            compactor_i = Compactor(level=compaction_level)
            hdata_i = [{"harness_id": h.harness_id, "iteration": 0,
                        "scores": r.scores, "source": h.source_code,
                        "per_problem": r.per_problem, "error": r.error}
                       for h, r in zip(seeds_i, seed_results_i)]
            d_i, _ = compactor_i.build_digest(hdata_i, frontier_i.to_dict())
            seed_digests.append({"agent_index": i, "agent_id": sid, "digest": d_i})

        return json.dumps({
            "hub_id": hub_id,
            "search_agent_ids": search_agent_ids,
            "n_agents": n_agents,
            "benchmark": benchmark_name,
            "hub_sync_interval": hub_sync_interval,
            "seed_digests": seed_digests,
            "instructions": (
                f"You have {n_agents} co-evolving agents. Drive each with "
                "mh_submit_candidate + mh_next_iteration independently. "
                f"Call mh_hub_sync(search_agent_id) every {hub_sync_interval} iterations "
                "to share discoveries across agents. Agents that build on each other's "
                "best work get 2x the improvement rate (CORAL paper result)."
            ),
        }, indent=2)

    elif name == "mh_hub_sync":
        search_agent_id = args["search_agent_id"]
        hub_id = _afs.get_state_or(search_agent_id, "hub_id")
        if not hub_id:
            return json.dumps({"error": "Agent not in a co-evolution run. Use mh_spawn_coevolution first."})
        result = _do_hub_sync(search_agent_id, hub_id, _afs)
        return json.dumps(result, indent=2)

    # -- Cross-Agent Memory --
    elif name == "agent_memory_write":
        from kaos.memory import MemoryStore
        mem = MemoryStore(_afs.conn)
        mid = mem.write(
            agent_id=args["agent_id"],
            content=args["content"],
            type=args.get("type", "observation"),
            key=args.get("key"),
            metadata=args.get("metadata"),
        )
        return json.dumps({"memory_id": mid, "status": "written"}, indent=2)

    elif name == "agent_memory_search":
        from kaos.memory import MemoryStore
        mem = MemoryStore(_afs.conn)
        hits = mem.search(
            query=args["query"],
            limit=args.get("limit", 10),
            type=args.get("type"),
            agent_id=args.get("agent_id"),
        )
        return json.dumps([h.to_dict() for h in hits], indent=2)

    elif name == "agent_memory_read":
        from kaos.memory import MemoryStore
        mem = MemoryStore(_afs.conn)
        if args.get("memory_id") is not None:
            entry = mem.get(args["memory_id"])
            return json.dumps(entry.to_dict() if entry else None, indent=2)
        entries = mem.list(
            agent_id=args.get("agent_id"),
            type=args.get("type"),
            limit=args.get("limit", 20),
        )
        return json.dumps([e.to_dict() for e in entries], indent=2)

    # -- Shared Log (LogAct) --
    elif name == "shared_log_intent":
        from kaos.shared_log import SharedLog
        log = SharedLog(_afs.conn)
        intent_id = log.intent(
            agent_id=args["agent_id"],
            action=args["action"],
            metadata=args.get("metadata"),
        )
        return json.dumps({"intent_id": intent_id, "status": "intent_broadcast"}, indent=2)

    elif name == "shared_log_vote":
        from kaos.shared_log import SharedLog
        log = SharedLog(_afs.conn)
        entry = log.vote(
            agent_id=args["agent_id"],
            intent_id=args["intent_id"],
            approve=args["approve"],
            reason=args.get("reason", ""),
        )
        return json.dumps(entry.to_dict(), indent=2)

    elif name == "shared_log_decide":
        from kaos.shared_log import SharedLog
        log = SharedLog(_afs.conn)
        entry = log.decide(intent_id=args["intent_id"], agent_id=args["agent_id"])
        return json.dumps(entry.to_dict(), indent=2)

    elif name == "shared_log_append":
        from kaos.shared_log import SharedLog
        log = SharedLog(_afs.conn)
        entry = log.append(
            agent_id=args["agent_id"],
            type=args["type"],
            payload=args.get("payload"),
            ref_id=args.get("ref_id"),
        )
        return json.dumps(entry.to_dict(), indent=2)

    elif name == "shared_log_read":
        from kaos.shared_log import SharedLog
        log = SharedLog(_afs.conn)
        if args.get("tail") is not None:
            entries = log.tail(args["tail"])
        else:
            entries = log.read(
                since_position=args.get("since_position", 0),
                limit=args.get("limit", 50),
                type=args.get("type"),
                agent_id=args.get("agent_id"),
            )
        return json.dumps([e.to_dict() for e in entries], indent=2)

    # -- Cross-Agent Skill Library (Zhou et al. 2026, arXiv:2604.08224) --
    elif name == "skill_save":
        from kaos.skills import SkillStore
        sk = SkillStore(_afs.conn)
        sid = sk.save(
            name=args["name"],
            description=args["description"],
            template=args["template"],
            source_agent_id=args.get("source_agent_id"),
            tags=args.get("tags", []),
        )
        skill = sk.get(sid)
        return json.dumps({
            "skill_id": sid,
            "params": skill.params() if skill else [],
            "status": "saved",
        }, indent=2)

    elif name == "skill_search":
        from kaos.skills import SkillStore
        sk = SkillStore(_afs.conn)
        hits = sk.search(
            query=args["query"],
            limit=args.get("limit", 10),
            tag=args.get("tag"),
        )
        return json.dumps([s.to_dict() for s in hits], indent=2)

    elif name == "skill_apply":
        from kaos.skills import SkillStore
        sk = SkillStore(_afs.conn)
        skill = sk.get(args["skill_id"])
        if not skill:
            return json.dumps({"error": f"Skill {args['skill_id']} not found"})
        params = args.get("params") or {}
        rendered = skill.apply(**params)
        outcome = args.get("outcome", "pending")
        if outcome == "success":
            sk.record_outcome(skill.skill_id, success=True)
        elif outcome == "failure":
            sk.record_outcome(skill.skill_id, success=False)
        # "pending" — caller will use skill_outcome later
        return json.dumps({
            "skill_id": skill.skill_id,
            "name": skill.name,
            "rendered": rendered,
        }, indent=2)

    elif name == "skill_list":
        from kaos.skills import SkillStore
        sk = SkillStore(_afs.conn)
        skills = sk.list(
            tag=args.get("tag"),
            source_agent_id=args.get("source_agent_id"),
            order_by=args.get("order_by", "created_at"),
            limit=args.get("limit", 20),
        )
        return json.dumps([s.to_dict() for s in skills], indent=2)

    elif name == "skill_outcome":
        from kaos.skills import SkillStore
        sk = SkillStore(_afs.conn)
        sk.record_outcome(args["skill_id"], success=args["success"])
        skill = sk.get(args["skill_id"])
        return json.dumps({
            "skill_id": args["skill_id"],
            "use_count": skill.use_count if skill else None,
            "success_count": skill.success_count if skill else None,
            "success_rate": round(skill.success_count / skill.use_count, 3) if skill and skill.use_count else None,
        }, indent=2)

    # ── Neuroplasticity / Dream (v0.8.0) ─────────────────────
    elif name == "dream_run":
        from kaos.dream import DreamCycle
        cycle = DreamCycle(_afs)
        result = cycle.run(dry_run=not args.get("apply", False),
                           since_ts=args.get("since_ts"),
                           write_digest=False)
        return json.dumps(result.summary(), indent=2)

    elif name == "dream_related":
        from kaos.dream.phases.associations import related
        edges = related(_afs.conn, args["kind"], args["id"],
                        limit=args.get("limit", 10))
        return json.dumps([
            {
                "kind": e.kind_b, "id": e.id_b, "label": e.label_b,
                "weight": round(e.decayed_weight, 4),
                "uses": e.uses, "last_seen": e.last_seen,
            } for e in edges
        ], indent=2)

    elif name == "failure_lookup":
        from kaos.dream.phases.failures import lookup
        row = lookup(_afs.conn, args["tool_name"], args["error_message"])
        return json.dumps(row, indent=2)

    elif name == "failure_list":
        from kaos.dream.phases.failures import run as run_failures
        report = run_failures(_afs.conn,
                              min_count_for_recurring=args.get("min_count", 2))
        return json.dumps([
            {
                "fp_id": e.fp_id, "fingerprint": e.fingerprint,
                "tool": e.tool_name, "count": e.count,
                "has_fix": bool(e.fix_summary or e.fix_skill_id),
                "example": e.example_error,
                "last_seen": e.last_seen,
            } for e in report.recurring
        ], indent=2)

    elif name == "failure_diagnose":
        from kaos.dream.phases.failures import set_category
        fp_id = args["fp_id"]
        if args.get("category"):
            set_category(
                _afs.conn, fp_id,
                category=args["category"],
                root_cause=args.get("root_cause"),
                suggested_action=args.get("suggested_action"),
            )
        # Always return the current state
        import sqlite3 as _sq
        prev = _afs.conn.row_factory
        _afs.conn.row_factory = _sq.Row
        try:
            row = _afs.conn.execute(
                "SELECT fp_id, fingerprint, tool_name, example_error, count, "
                "category, root_cause, suggested_action, diagnostic_method, "
                "diagnosed_at, fix_attempts, fix_success_count, fix_summary "
                "FROM failure_fingerprints WHERE fp_id = ?",
                (fp_id,),
            ).fetchone()
        finally:
            _afs.conn.row_factory = prev
        return json.dumps(dict(row) if row else None, indent=2)

    elif name == "failure_fix_outcome":
        from kaos.dream.phases.failures import record_fix_outcome
        result = record_fix_outcome(
            _afs.conn, args["fp_id"], succeeded=args["succeeded"],
        )
        return json.dumps(result, indent=2)

    elif name == "systemic_alerts":
        from kaos.dream.phases.failures import (
            ack_alert, list_active_alerts, resolve_alert,
        )
        if args.get("ack") is not None:
            ok = ack_alert(_afs.conn, args["ack"], acked_by=args.get("by"))
            return json.dumps({"alert_id": args["ack"], "acked": ok}, indent=2)
        if args.get("resolve") is not None:
            ok = resolve_alert(_afs.conn, args["resolve"],
                               resolved_by=args.get("by"))
            return json.dumps({"alert_id": args["resolve"], "resolved": ok},
                              indent=2)
        alerts = list_active_alerts(_afs.conn, limit=args.get("limit", 20))
        return json.dumps(alerts, indent=2)

    elif name == "dream_consolidate":
        from kaos.dream.phases.consolidation import run as run_consolidation
        from kaos.dream.phases.policies import run as run_policies
        cons = run_consolidation(
            _afs.conn, dry_run=not args.get("apply", False),
            trigger_reason="mcp",
            merge_threshold=args.get("merge_threshold", 0.65),
        )
        pol = run_policies(_afs.conn, dry_run=not args.get("apply", False))
        return json.dumps({
            "mode": "apply" if args.get("apply") else "dry_run",
            "consolidation": {
                "promote": cons.promoted,
                "prune": cons.pruned,
                "merge_candidates": cons.merge_candidates,
                "applied": cons.applied,
                "proposals": [
                    {"kind": p.kind, "rationale": p.rationale,
                     "targets": p.targets, "applied": p.applied}
                    for p in cons.proposals
                ],
            },
            "policies": {
                "promoted": pol.total_promoted,
                "skipped_existing": pol.skipped_existing,
            },
        }, indent=2)

    elif name == "dream_merges":
        from kaos.dream.phases.consolidation import (
            accept_merge, list_pending_merges, reject_merge,
        )
        if args.get("accept") is not None and args.get("reject") is not None:
            return json.dumps({"error": "accept and reject are mutually exclusive"},
                              indent=2)
        if args.get("accept") is not None:
            result = accept_merge(_afs.conn, args["accept"],
                                  keep_skill_id=args.get("keep"))
            return json.dumps(result, indent=2)
        if args.get("reject") is not None:
            result = reject_merge(_afs.conn, args["reject"],
                                  reason=args.get("reason"))
            return json.dumps(result, indent=2)
        pending = list_pending_merges(_afs.conn, limit=args.get("limit", 20))
        return json.dumps({"pending": pending}, indent=2)

    else:
        raise ValueError(f"Unknown tool: {name}")
