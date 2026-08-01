"""PFA arms: FULL (claude CLI auditor), DET (frozen 3-rule detector),
RAND (matched-rate seeded control), B0 (never flags — self-test only).

All frozen by ISA.lock.json. The auditor never sees outcomes (blind
rendering is upstream in workload.py).
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import sqlite3
import subprocess

from demo_process_flag_bench.workload import SEED, TERMINAL

FLAGS = [
    "give_up_shaped_candidate",
    "insufficient_search_coverage",
    "evidence_lost_before_synthesis",
    "duplicate_state_mutation",
    "missing_validator",
    "unsupported_impossibility_claim",
]

PROMPT = """You are a process auditor for AI-agent execution traces. You judge PROCESS QUALITY only — you have no information about, and must not guess, whether the episode ultimately succeeded.

Scan the trace below for process anomalies. The ONLY flags you may emit (emit each at most once, only with concrete evidence):
- give_up_shaped_candidate: the agent set up, then did essentially no substantive work toward the task
- insufficient_search_coverage: the task implies exploration/reading, but the trace shows little or none
- evidence_lost_before_synthesis: information was gathered (reads/tool results) but never used in any later write/output
- duplicate_state_mutation: the same state mutation (e.g. same file path written) is repeated redundantly
- missing_validator: the trace mutates state or produces output with no verification/check step of any kind
- unsupported_impossibility_claim: an output/log asserts something cannot be done without evidence of an attempt

Respond with STRICT JSON only, no prose, no code fences:
{"flags": [{"flag": "<one of the six>", "evidence_event_ids": [<int event ids from the trace>], "confidence": <0..1>, "rationale": "<one sentence>"}]}
An empty flags array means the trace looks procedurally clean.

TRACE:
"""


def audit_episode(trace: str, timeout: int = 120) -> dict | None:
    """One claude CLI call. Returns parsed dict or None (parse/exec failure
    after one retry)."""
    exe = shutil.which("claude.cmd") or shutil.which("claude")
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    for _attempt in range(2):
        try:
            r = subprocess.run(
                [exe, "-p", "--output-format", "text"],
                input=PROMPT + trace, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace", env=env,
            )
            out = (r.stdout or "").strip()
            m = re.search(r"\{.*\}", out, re.S)
            if not m:
                continue
            d = json.loads(m.group(0))
            flags = d.get("flags")
            if not isinstance(flags, list):
                continue
            clean = [f for f in flags
                     if isinstance(f, dict) and f.get("flag") in FLAGS]
            return {"flags": clean, "raw": out[:2000]}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            continue
    return None


def det_flag(conn: sqlite3.Connection, agent_id: str) -> bool:
    """Frozen deterministic detector: zero file_write OR any tool error OR
    zero tool_call_start (over non-terminal events)."""
    n_fw = conn.execute(
        "SELECT COUNT(*) FROM events WHERE agent_id=? AND event_type='file_write'",
        (agent_id,)).fetchone()[0]
    n_tc = conn.execute(
        "SELECT COUNT(*) FROM events WHERE agent_id=? AND event_type='tool_call_start'",
        (agent_id,)).fetchone()[0]
    n_err = conn.execute(
        "SELECT COUNT(*) FROM tool_calls WHERE agent_id=? AND "
        "(status='error' OR error_message IS NOT NULL)", (agent_id,)).fetchone()[0]
    return n_fw == 0 or n_err > 0 or n_tc == 0


def rand_flags(agent_ids: list[str], rate: float) -> dict[str, bool]:
    rng = random.Random(SEED)
    k = round(rate * len(agent_ids))
    chosen = set(rng.sample(agent_ids, k)) if k else set()
    return {a: a in chosen for a in agent_ids}
