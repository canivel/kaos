"""Failure diagnosis — classify errors into actionable categories.

Pattern-matching alone tells you that an error has happened before.
Diagnosis tells you **why** — and what to do about it.

Every failure fingerprint gets diagnosed ONCE when it's first observed.
The diagnosis records:

    category         : transient | config | code | infra | unknown
    root_cause       : human-readable summary of what actually went wrong
    suggested_action : one-line guidance for the human or agent
    method           : how we arrived at the diagnosis (heuristic | llm | user)
    confidence       : 0..1

Diagnosers are pluggable. KAOS ships a registry of heuristic diagnosers
(pure Python, fast, deterministic, no API cost) plus an optional LLM
diagnoser that routes through the configured model. Users can register
their own project-specific diagnosers via ``register_diagnoser``.

The heuristics catch the high-volume cases — connection refused, rate
limits, auth failures, common Python tracebacks — which cover the vast
majority of real agent failures without ever calling a model.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Protocol


# ── Diagnosis shape ────────────────────────────────────────────────


CATEGORIES = ("transient", "config", "code", "infra", "unknown")


@dataclass
class Diagnosis:
    category: str
    root_cause: str
    suggested_action: str | None
    method: str          # "heuristic" | "llm" | "user" | "structured"
    confidence: float    # 0..1

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "root_cause": self.root_cause,
            "suggested_action": self.suggested_action,
            "method": self.method,
            "confidence": round(self.confidence, 3),
        }


class Diagnoser(Protocol):
    """Protocol for a failure diagnoser. Return None if the diagnoser doesn't
    recognise the error — the registry will try the next one."""

    name: str

    def try_diagnose(
        self,
        tool_name: str,
        error: str,
        context: dict[str, Any],
    ) -> Diagnosis | None: ...


# ── Built-in heuristic diagnosers ─────────────────────────────────


def _matches(error: str, *patterns: str) -> bool:
    lo = error.lower()
    return any(p in lo for p in patterns)


class ConnectionRefusedDiagnoser:
    """ECONNREFUSED, ConnectionRefusedError, etc. Almost always infrastructure."""

    name = "connection_refused"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error, "connection refused", "connectionrefused",
                        "econnrefused", "connection reset",
                        "no route to host"):
            return None
        lo = error.lower()
        local = any(h in lo for h in ("localhost", "127.0.0.1", "::1"))
        if local:
            return Diagnosis(
                category="infra",
                root_cause=("Local service not reachable. A service KAOS or an "
                            "agent is calling on localhost is not running."),
                suggested_action=("Check whether the expected local server "
                                  "(e.g. vLLM, MCP, local DB) is running on "
                                  "the configured port."),
                method="heuristic", confidence=0.9,
            )
        return Diagnosis(
            category="infra",
            root_cause=("Remote endpoint unreachable. DNS, firewall, or "
                        "upstream service may be down."),
            suggested_action="Verify network connectivity and upstream service status.",
            method="heuristic", confidence=0.75,
        )


class RateLimitDiagnoser:
    """HTTP 429, "rate limit", throttling messages. Transient by definition."""

    name = "rate_limit"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error, "rate limit", "too many requests",
                        " 429", "quota exceeded", "throttle"):
            return None
        return Diagnosis(
            category="transient",
            root_cause="Upstream API rate limit hit.",
            suggested_action=("Retry with exponential backoff + jitter. "
                              "If this is recurrent, add request budgeting."),
            method="heuristic", confidence=0.95,
        )


class TimeoutDiagnoser:
    """Timeout errors — could be transient (network blip) or code (infinite loop)."""

    name = "timeout"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error, "timeout", "timed out", "deadline exceeded"):
            return None
        # If error mentions "infinite" or duration >= a huge number, more likely code
        if _matches(error, "infinite", "hang", "deadlock"):
            return Diagnosis(
                category="code",
                root_cause="Operation hit a hang or infinite loop.",
                suggested_action=("Inspect the tool's control flow for a missing "
                                  "exit condition. Add a bounded retry counter."),
                method="heuristic", confidence=0.7,
            )
        return Diagnosis(
            category="transient",
            root_cause="Request timed out before response.",
            suggested_action=("Retry with a longer timeout. If it recurs, "
                              "upstream service may be degraded."),
            method="heuristic", confidence=0.6,
        )


class AuthFailureDiagnoser:
    """401 / 403 / 'unauthorized' / 'invalid api key' — config, needs human."""

    name = "auth_failure"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error, " 401", " 403", "unauthorized", "unauthorised",
                        "forbidden", "invalid api key", "invalid token",
                        "authentication fail", "credentials"):
            return None
        return Diagnosis(
            category="config",
            root_cause=("Authentication failed. API key, token, or credentials "
                        "are missing, expired, or wrong."),
            suggested_action=("Check the relevant environment variable or "
                              "config. Retrying without fixing credentials "
                              "will not resolve this."),
            method="heuristic", confidence=0.95,
        )


class CodeErrorDiagnoser:
    """Python-style exceptions that look like code bugs rather than env issues."""

    name = "code_error"

    _CODE_PATTERNS = (
        "keyerror", "attributeerror", "typeerror", "valueerror",
        "indexerror", "nameerror", "zerodivisionerror", "unboundlocalerror",
        "assertionerror",
    )

    def try_diagnose(self, tool_name, error, context):
        lo = error.lower()
        matched = next((p for p in self._CODE_PATTERNS if p in lo), None)
        if matched is None:
            return None
        return Diagnosis(
            category="code",
            root_cause=f"Python {matched.title()} — likely a bug in the agent's "
                       "tool sequence or a mutation in the harness.",
            suggested_action=("Inspect the recent tool_calls for the failing "
                              "agent. A single known-good variation of this "
                              "tool usage may already exist as a skill."),
            method="heuristic", confidence=0.85,
        )


class MissingDataDiagnoser:
    """'click requires data', 'missing required field', 'expected ...'."""

    name = "missing_data"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error,
                        "missing required", "required argument", "required field",
                        "requires data", "expected", "must provide"):
            return None
        return Diagnosis(
            category="code",
            root_cause=("A tool call was made without a required argument. "
                        "The agent did not satisfy the tool's schema."),
            suggested_action=("Check the tool's input schema. Likely a prompt "
                              "issue — the agent didn't know the argument was "
                              "mandatory. Saving a skill with the correct "
                              "call pattern prevents recurrence."),
            method="heuristic", confidence=0.8,
        )


class DiskOrResourceDiagnoser:
    """Disk full, out of memory, process limits — infra, often systemic."""

    name = "resource_exhausted"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error, "no space left", "disk full", "out of memory",
                        "oom ", "resource temporarily unavailable",
                        "too many open files"):
            return None
        return Diagnosis(
            category="infra",
            root_cause="Host resource exhausted (disk, memory, or file descriptors).",
            suggested_action=("Free resources on the host. Spawning more agents "
                              "will make it worse, not better."),
            method="heuristic", confidence=0.95,
        )


class DNSResolutionDiagnoser:
    """DNS errors — infra."""

    name = "dns"

    def try_diagnose(self, tool_name, error, context):
        if not _matches(error, "nodename nor servname", "name or service not known",
                        "could not resolve", "dns resolution", "getaddrinfo"):
            return None
        return Diagnosis(
            category="infra",
            root_cause="DNS resolution failed for the target hostname.",
            suggested_action=("Check /etc/resolv.conf, the hostname spelling, "
                              "and the network."),
            method="heuristic", confidence=0.9,
        )


# ── LLM-backed diagnoser (opt-in) ─────────────────────────────────


LLM_DIAGNOSIS_PROMPT = """You are KAOS's failure diagnoser. Classify the following agent-tool failure and suggest one actionable next step.

Tool: {tool_name}
Error: {error}

Respond as STRICT JSON with these keys:
  "category":         one of "transient", "config", "code", "infra", "unknown"
  "root_cause":       one-sentence explanation of what went wrong
  "suggested_action": one-sentence concrete next step
  "confidence":       float in [0, 1]

Return the JSON object and nothing else."""


class LLMDiagnoser:
    """Opt-in diagnoser that asks an LLM to categorise errors the heuristics
    missed. Results are cached in ``llm_diagnosis_cache`` keyed by the error
    fingerprint so each unique failure pays the LLM cost at most once.

    Parameters
    ----------
    call_fn:
        Callable that takes a prompt string and returns the model's raw text
        response. Synchronous. Pass ``None`` to disable network calls (the
        diagnoser will only serve cache hits).
    conn:
        Optional SQLite connection. When provided, cache lookups and writes
        are served from ``llm_diagnosis_cache``. Pass ``None`` for pure
        pass-through (e.g. inside unit tests that don't want persistence).
    model:
        Label recorded alongside cache entries.

    This class does NOT import anthropic / openai / httpx. The caller wires
    the model by passing an arbitrary ``call_fn``. This keeps the module
    fast to import and easy to mock in tests.
    """

    name = "llm"

    def __init__(
        self,
        call_fn: Callable[[str], str] | None,
        conn: sqlite3.Connection | None = None,
        model: str = "claude",
    ) -> None:
        self._call_fn = call_fn
        self._conn = conn
        self._model = model

    def try_diagnose(
        self,
        tool_name: str,
        error: str,
        context: dict[str, Any],
    ) -> Diagnosis | None:
        # Lazy import to avoid a cycle (auto imports diagnosis, diagnosis
        # imports fingerprint_of from auto).
        from kaos.dream.auto import fingerprint_of
        fp = fingerprint_of(tool_name, error)

        cached = self._cache_get(fp)
        if cached is not None:
            return cached

        if self._call_fn is None:
            return None

        prompt = LLM_DIAGNOSIS_PROMPT.format(tool_name=tool_name, error=error)
        try:
            raw = self._call_fn(prompt)
        except Exception:
            return None

        parsed = _safe_parse_llm_json(raw)
        if parsed is None:
            return None

        diag = Diagnosis(
            category=parsed.get("category", "unknown"),
            root_cause=parsed.get("root_cause") or "LLM could not determine root cause.",
            suggested_action=parsed.get("suggested_action"),
            method="llm",
            confidence=float(parsed.get("confidence", 0.7) or 0.7),
        )
        if diag.category not in CATEGORIES:
            diag.category = "unknown"
        self._cache_put(fp, diag)
        return diag

    def _cache_get(self, fp: str) -> Diagnosis | None:
        if self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT category, root_cause, suggested_action, confidence "
                "FROM llm_diagnosis_cache WHERE fingerprint = ?",
                (fp,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        return Diagnosis(
            category=row[0],
            root_cause=row[1] or "",
            suggested_action=row[2],
            method="llm-cached",
            confidence=float(row[3] or 0.7),
        )

    def _cache_put(self, fp: str, diag: Diagnosis) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO llm_diagnosis_cache "
                "(fingerprint, category, root_cause, suggested_action, "
                "confidence, model) VALUES (?, ?, ?, ?, ?, ?)",
                (fp, diag.category, diag.root_cause, diag.suggested_action,
                 diag.confidence, self._model),
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _safe_parse_llm_json(raw: str) -> dict | None:
    """Extract the first JSON object from a model response. Robust to
    markdown fencing, leading/trailing prose, or trailing punctuation."""
    if not raw:
        return None
    match = _JSON_BLOCK.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


# ── Registry ───────────────────────────────────────────────────────


_BUILTIN_DIAGNOSERS: list[Diagnoser] = [
    ConnectionRefusedDiagnoser(),
    RateLimitDiagnoser(),
    AuthFailureDiagnoser(),
    DiskOrResourceDiagnoser(),
    DNSResolutionDiagnoser(),
    TimeoutDiagnoser(),
    CodeErrorDiagnoser(),
    MissingDataDiagnoser(),
]


_registry: list[Diagnoser] = list(_BUILTIN_DIAGNOSERS)


def register_diagnoser(diagnoser: Diagnoser, *, prepend: bool = True) -> None:
    """Add a user-defined diagnoser to the registry.

    Defaults to prepend=True so user diagnosers beat the built-in heuristics.
    """
    if prepend:
        _registry.insert(0, diagnoser)
    else:
        _registry.append(diagnoser)


def reset_registry() -> None:
    """Restore the built-in registry. Useful for tests."""
    _registry.clear()
    _registry.extend(_BUILTIN_DIAGNOSERS)


def list_diagnosers() -> list[str]:
    return [d.name for d in _registry]


# ── Main entry point ──────────────────────────────────────────────


def diagnose(
    tool_name: str,
    error: str,
    context: dict[str, Any] | None = None,
    *,
    llm_fallback: LLMDiagnoser | None = None,
) -> Diagnosis:
    """Try every registered diagnoser in order. Return the first hit, or a
    ``category='unknown'`` diagnosis if no heuristic matches.

    Deterministic by default: no randomness, no I/O.

    If ``llm_fallback`` is provided and no heuristic matches, the LLM
    diagnoser is consulted (cache-first). Keep heuristics primary so we pay
    the LLM cost only for genuinely novel failures.
    """
    ctx = context or {}
    for d in _registry:
        try:
            result = d.try_diagnose(tool_name, error, ctx)
        except Exception:
            continue
        if result is not None:
            return result
    if llm_fallback is not None:
        try:
            result = llm_fallback.try_diagnose(tool_name, error, ctx)
        except Exception:
            result = None
        if result is not None:
            return result
    return Diagnosis(
        category="unknown",
        root_cause="No matching diagnostic rule. Needs manual triage or LLM analysis.",
        suggested_action=("Run `kaos dream diagnose <fp_id>` with an LLM "
                          "diagnoser registered, or inspect the agent's "
                          "recent tool_calls manually."),
        method="heuristic",
        confidence=0.0,
    )
