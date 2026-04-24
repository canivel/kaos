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

import re
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
) -> Diagnosis:
    """Try every registered diagnoser in order. Return the first hit, or a
    ``category='unknown'`` diagnosis if no heuristic matches.

    Deterministic: no randomness, no I/O. Safe to call from hot paths.
    """
    ctx = context or {}
    for d in _registry:
        try:
            result = d.try_diagnose(tool_name, error, ctx)
        except Exception:
            continue
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
