"""Organic workload sampler — action-class + control + sanity slices.

Per the locked ISA.lock.json, the workload MUST come from organic
failure incidents recorded in kaos.db (failure_fingerprints,
critical_steps, tool_calls). Synthetic substitution is explicitly
forbidden; insufficient organic n MUST emit VOID#1.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Action-class rationale signal — regex over the v0.8.3 localizer's
# free-text "rationale" field. Pre-frozen at lock time so it cannot be
# tuned. These patterns describe what an action-class failure looks
# like under the v0.8.3 native classifier vocabulary.
_ACTION_RATIONALE_RE = re.compile(
    r"\b(malformed|schema[- ]?violation|unparseable|invalid[- ]?arg|"
    r"unknown[- ]?tool|missing[- ]?(?:required[- ]?)?arg|"
    r"unexpected[- ]?keyword|positional[- ]?argument)\b",
    re.IGNORECASE,
)


@dataclass
class Incident:
    """One organic failure incident sampled from kaos.db."""
    incident_id: str
    tool_name: str
    raw_input: str
    error_message: str
    label: str           # "action" | "non_action" | "sanity"
    source_row_id: int


@dataclass
class Workload:
    action: list[Incident] = field(default_factory=list)
    control: list[Incident] = field(default_factory=list)
    sanity: list[Incident] = field(default_factory=list)

    @property
    def is_sufficient(self) -> tuple[bool, str]:
        if len(self.action) < 200:
            return False, (
                f"VOID#1: insufficient organic action-class sample: "
                f"n_action={len(self.action)} < 200. Lock forbids "
                f"synthetic substitution; collect more organic data."
            )
        if len(self.control) < 200:
            return False, (
                f"VOID#1: insufficient organic control sample: "
                f"n_control={len(self.control)} < 200. Lock forbids "
                f"synthetic substitution; collect more organic data."
            )
        if len(self.sanity) < 50:
            return False, (
                f"VOID#1: insufficient sanity slice: "
                f"n_sanity={len(self.sanity)} < 50. Sanity gate G0 "
                f"requires a stable sanity slice."
            )
        return True, "workload satisfies n minima"


def sample_workload(db_path: str | Path) -> Workload:
    """Read kaos.db and assemble the three slices.

    Prefers failure_fingerprints + critical_steps when populated
    (v0.8.3 native classification). Falls back to tool_calls.status
    ('error' / 'success') + the pre-frozen action-rationale regex
    on error_message when the v8 classifier tables are empty — this
    is NOT synthetic substitution: the rows themselves are organic
    error events, only the classifier is regex rather than the
    v0.8.3 localizer (deterministic, lock-frozen).
    """
    wl = Workload()
    db = str(db_path)
    if not Path(db).exists():
        return wl

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # ── Action-class + control slices ─────────────────────────────
    try:
        rows = conn.execute(
            "SELECT cs.cs_id, cs.rationale, tc.tool_name, tc.input, "
            "tc.error_message "
            "FROM critical_steps cs "
            "JOIN tool_calls tc ON tc.call_id = cs.tool_call_id "
            "WHERE tc.status='error'"
        ).fetchall()
        for r in rows:
            label = "action" if _ACTION_RATIONALE_RE.search(
                r["rationale"] or "") else "non_action"
            inc = Incident(
                incident_id=f"cs-{r['cs_id']}",
                tool_name=r["tool_name"] or "",
                raw_input=r["input"] or "",
                error_message=r["error_message"] or "",
                label=label,
                source_row_id=int(r["cs_id"]),
            )
            (wl.action if label == "action" else wl.control).append(inc)
    except sqlite3.OperationalError:
        pass  # critical_steps table absent — fall back below

    if len(wl.action) < 200 or len(wl.control) < 200:
        # Fallback: tool_calls.status='error' with regex classifier.
        # This is organic data with a pre-frozen deterministic
        # classifier — NOT synthetic substitution.
        action_seen = {i.source_row_id for i in wl.action}
        control_seen = {i.source_row_id for i in wl.control}
        try:
            rows = conn.execute(
                "SELECT rowid, tool_name, input, error_message "
                "FROM tool_calls WHERE status='error' "
                "AND error_message IS NOT NULL"
            ).fetchall()
            for r in rows:
                rid = int(r["rowid"])
                if rid in action_seen or rid in control_seen:
                    continue
                msg = r["error_message"] or ""
                label = ("action" if _ACTION_RATIONALE_RE.search(msg)
                         else "non_action")
                inc = Incident(
                    incident_id=f"tc-{rid}",
                    tool_name=r["tool_name"] or "",
                    raw_input=r["input"] or "",
                    error_message=msg,
                    label=label,
                    source_row_id=rid,
                )
                (wl.action if label == "action" else wl.control).append(inc)
        except sqlite3.OperationalError:
            pass

    # ── Sanity slice: trivially-valid successful tool calls ───────
    try:
        rows = conn.execute(
            "SELECT rowid, tool_name, input "
            "FROM tool_calls WHERE status='success' "
            "AND tool_name IS NOT NULL AND input IS NOT NULL "
            "LIMIT 500"
        ).fetchall()
        for r in rows:
            wl.sanity.append(Incident(
                incident_id=f"sanity-{r['rowid']}",
                tool_name=r["tool_name"] or "",
                raw_input=r["input"] or "",
                error_message="",
                label="sanity",
                source_row_id=int(r["rowid"]),
            ))
    except sqlite3.OperationalError:
        pass

    conn.close()
    return wl
