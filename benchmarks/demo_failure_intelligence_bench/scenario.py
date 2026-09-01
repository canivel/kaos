"""Failure intelligence scenario (Dream M2.5) — real triage validation.

Plants a mixed bag of realistic failures, verifies KAOS categorises them
correctly, verifies fix-outcome tracking auto-downgrades broken fixes, and
verifies systemic detection halts operations when infrastructure is down.

Run with::

    cd demo_failure_intelligence_bench
    uv run python scenario.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

DB = HERE / "failure-intel.db"

# Tunables for deterministic systemic-detection behaviour.
os.environ["KAOS_SYSTEMIC_THRESHOLD"] = "3"
os.environ["KAOS_SYSTEMIC_WINDOW_S"] = "60"
# Don't trigger auto-consolidation mid-scenario; keeps output clean.
os.environ["KAOS_DREAM_THRESHOLD"] = "1000000"

from kaos import Kaos  # noqa: E402
from kaos.dream.phases import failures as failures_phase  # noqa: E402


class Checks:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed.append(name)
            print(f"  [PASS] {name}")
        else:
            self.failed.append((name, detail))
            print(f"  [FAIL] {name}  {detail}")

    def summary(self) -> int:
        print("")
        total = len(self.passed) + len(self.failed)
        print(f"  {len(self.passed)}/{total} checks passed")
        return 0 if not self.failed else 1


# ── Scenario planted failures ──────────────────────────────────────


PLANTED_FAILURES = [
    # (agent_name, tool, error_message, expected_category)
    ("rate-limited-agent", "http_post",
     "HTTP 429 Too Many Requests: rate limit exceeded, retry after 60s",
     "transient"),
    ("auth-bad-agent", "http_get",
     "HTTP 401 Unauthorized: invalid api key",
     "config"),
    ("mutation-bug-agent", "harness_run",
     "KeyError: 'tried_actions'",
     "code"),
    ("typo-agent", "harness_run",
     "AttributeError: 'NoneType' object has no attribute 'grid'",
     "code"),
    ("vllm-down-agent", "llm_call",
     "ConnectionRefusedError: localhost:8000",
     "infra"),
    ("disk-full-agent", "fs_write",
     "OSError: [Errno 28] No space left on device",
     "infra"),
    ("dns-broken-agent", "http_get",
     "could not resolve hostname api.internal",
     "infra"),
]


def _plant(kaos: Kaos, agent_name: str, tool: str, error: str) -> str:
    aid = kaos.spawn(agent_name)
    call_id = kaos.log_tool_call(aid, tool, {})
    kaos.start_tool_call(call_id)
    kaos.complete_tool_call(call_id, output={}, status="error",
                            error_message=error, token_count=0)
    kaos.fail(aid)
    return aid


# ── Phases ─────────────────────────────────────────────────────────


def phase_reset() -> None:
    print("\n== Reset ==")
    if DB.exists():
        DB.unlink()
    print(f"  DB:    {DB}")
    print(f"  Systemic: threshold={os.environ['KAOS_SYSTEMIC_THRESHOLD']}  "
          f"window={os.environ['KAOS_SYSTEMIC_WINDOW_S']}s")


def phase_categorise(checks: Checks) -> Kaos:
    print("\n== Plant failures + verify categorisation ==")
    kaos = Kaos(db_path=str(DB))
    for agent_name, tool, error, expected_cat in PLANTED_FAILURES:
        _plant(kaos, agent_name, tool, error)

    # Inspect every fingerprint's category
    import sqlite3 as _sq
    kaos.conn.row_factory = _sq.Row
    rows = kaos.conn.execute(
        "SELECT fp_id, tool_name, example_error, category, root_cause, "
        "suggested_action, diagnostic_method FROM failure_fingerprints "
        "ORDER BY fp_id"
    ).fetchall()

    # Index by a discriminating substring of the example_error (tool_name
    # alone is ambiguous because multiple planted errors share a tool).
    def _find(expected_substr: str) -> dict | None:
        expected_lower = expected_substr.lower()
        for r in rows:
            ex = (r["example_error"] or "").lower()
            if expected_lower in ex:
                return dict(r)
        return None

    # Map each planted scenario to a unique discriminator within its error
    discriminators = {
        "rate-limited-agent": "rate limit",
        "auth-bad-agent": "unauthorized",
        "mutation-bug-agent": "keyerror",
        "typo-agent": "attributeerror",
        "vllm-down-agent": "connectionrefused",
        "disk-full-agent": "no space left",
        "dns-broken-agent": "resolve hostname",
    }

    for agent_name, tool, error, expected_cat in PLANTED_FAILURES:
        fp = _find(discriminators[agent_name])
        checks.check(f"fingerprint created for `{agent_name}`", fp is not None)
        if not fp:
            continue
        checks.check(
            f"`{agent_name}` categorised as '{expected_cat}'",
            fp["category"] == expected_cat,
            f"got '{fp['category']}'",
        )
        checks.check(
            f"`{agent_name}` has root_cause recorded",
            bool(fp["root_cause"]),
            f"got {fp['root_cause']!r}",
        )
        checks.check(
            f"`{agent_name}` has suggested_action recorded",
            bool(fp["suggested_action"]),
            f"got {fp['suggested_action']!r}",
        )
        checks.check(
            f"`{agent_name}` diagnostic_method == 'heuristic'",
            fp["diagnostic_method"] == "heuristic",
            f"got {fp['diagnostic_method']!r}",
        )
    kaos.conn.row_factory = None
    return kaos


def phase_fix_outcome(kaos: Kaos, checks: Checks) -> None:
    print("\n== Fix-outcome tracking: bad fix auto-downgrades ==")
    # Pick any fingerprint to attach a bogus fix to
    fp_id = kaos.conn.execute(
        "SELECT fp_id FROM failure_fingerprints LIMIT 1"
    ).fetchone()[0]
    failures_phase.attach_fix(kaos.conn, fp_id,
                              fix_summary="retry with backoff")

    for i in range(4):
        r = failures_phase.record_fix_outcome(kaos.conn, fp_id, succeeded=False)
        checks.check(f"attempt {i + 1}: fix not yet downgraded",
                     r["downgraded"] is False,
                     f"downgraded={r['downgraded']}")

    r = failures_phase.record_fix_outcome(kaos.conn, fp_id, succeeded=False)
    checks.check("5th failed attempt triggers downgrade",
                 r["downgraded"] is True,
                 f"downgraded={r['downgraded']}")

    summary = kaos.conn.execute(
        "SELECT fix_summary FROM failure_fingerprints WHERE fp_id = ?",
        (fp_id,),
    ).fetchone()[0]
    checks.check("fix_summary cleared after downgrade",
                 summary is None,
                 f"got {summary!r}")


def phase_systemic(kaos: Kaos, checks: Checks) -> None:
    print("\n== Systemic detection: 4 agents hit same fp within window ==")
    # Baseline: count alerts before the wave
    before = kaos.conn.execute(
        "SELECT COUNT(*) FROM systemic_alerts"
    ).fetchone()[0]

    # Plant 4 agents all hitting the same LOCAL infra failure, inside
    # the debounce window. Threshold (3) is crossed on the 3rd.
    for i in range(4):
        _plant(kaos, f"systemic-agent-{i}", "llm_call",
               "ConnectionRefusedError: localhost:8000")

    after = kaos.conn.execute(
        "SELECT COUNT(*) FROM systemic_alerts"
    ).fetchone()[0]
    checks.check("systemic alert fired during the wave",
                 after > before, f"before={before} after={after}")

    # Due to debouncing, exactly ONE alert should exist for this fingerprint
    # even though 4 agents triggered it.
    fp_row = kaos.conn.execute(
        "SELECT fp_id FROM failure_fingerprints WHERE tool_name = 'llm_call'"
    ).fetchone()
    assert fp_row, "expected llm_call fingerprint"
    fp_id = fp_row[0]
    alerts_for_fp = kaos.conn.execute(
        "SELECT COUNT(*) FROM systemic_alerts WHERE fp_id = ?",
        (fp_id,),
    ).fetchone()[0]
    checks.check("exactly one alert per fingerprint (debounced)",
                 alerts_for_fp == 1,
                 f"got {alerts_for_fp}")

    # The alert should record the observed agent_count >= threshold
    agent_count = kaos.conn.execute(
        "SELECT MAX(agent_count) FROM systemic_alerts WHERE fp_id = ?",
        (fp_id,),
    ).fetchone()[0]
    checks.check("alert agent_count >= 3 (threshold)",
                 agent_count >= 3, f"got {agent_count}")

    # list_active_alerts returns it
    active = failures_phase.list_active_alerts(kaos.conn)
    checks.check("active alerts list non-empty",
                 len(active) >= 1, f"got {len(active)}")
    if active:
        a = active[0]
        checks.check("active alert carries root_cause from fingerprint",
                     bool(a.get("root_cause")),
                     f"got {a.get('root_cause')!r}")


def phase_alert_lifecycle(kaos: Kaos, checks: Checks) -> None:
    print("\n== Alert lifecycle: ack + resolve ==")
    active = failures_phase.list_active_alerts(kaos.conn)
    if not active:
        checks.check("no active alerts to ack/resolve (unexpected)",
                     False, "previous phase should have created one")
        return
    alert_id = active[0]["alert_id"]
    ok = failures_phase.ack_alert(kaos.conn, alert_id, acked_by="scenario")
    checks.check("ack_alert returns True", ok is True)

    acked_row = kaos.conn.execute(
        "SELECT acked_at, acked_by FROM systemic_alerts WHERE alert_id = ?",
        (alert_id,),
    ).fetchone()
    checks.check("acked_at set",  acked_row and acked_row[0] is not None)
    checks.check("acked_by recorded",
                 acked_row and acked_row[1] == "scenario",
                 f"got {acked_row[1] if acked_row else None}")

    # Acked but not resolved -> still active
    active_after_ack = failures_phase.list_active_alerts(kaos.conn)
    checks.check("acked alerts still listed as active",
                 any(a["alert_id"] == alert_id for a in active_after_ack))

    # Resolve it
    ok = failures_phase.resolve_alert(kaos.conn, alert_id, resolved_by="scenario")
    checks.check("resolve_alert returns True", ok is True)
    still_active = failures_phase.list_active_alerts(kaos.conn)
    checks.check("resolved alert no longer active",
                 not any(a["alert_id"] == alert_id for a in still_active))


def phase_recategorise(kaos: Kaos, checks: Checks) -> None:
    print("\n== Recategorise: new diagnoser catches up old fingerprints ==")
    # Plant a previously-unknown pattern
    _plant(kaos, "mystery-agent", "mystery_tool",
           "zzfoo.CustomMysteryException was raised")
    pre = kaos.conn.execute(
        "SELECT category FROM failure_fingerprints WHERE tool_name = 'mystery_tool'"
    ).fetchone()[0]
    checks.check("new pattern starts as 'unknown'",
                 pre == "unknown", f"got {pre!r}")

    # Register a user-defined diagnoser that recognises this
    from kaos.dream.diagnosis import Diagnosis, register_diagnoser, reset_registry

    class MysteryDiagnoser:
        name = "mystery"

        def try_diagnose(self, tool_name, error, context):
            if "CustomMysteryException" in error:
                return Diagnosis(category="code",
                                 root_cause="CustomMysteryException path",
                                 suggested_action="Check zzfoo.py for the "
                                                   "mystery trigger",
                                 method="heuristic", confidence=0.9)
            return None

    register_diagnoser(MysteryDiagnoser())
    try:
        updated = failures_phase.recategorise_all(kaos.conn)
    finally:
        reset_registry()

    checks.check("recategorise_all found 1 update",
                 updated == 1, f"got {updated}")
    post = kaos.conn.execute(
        "SELECT category, root_cause FROM failure_fingerprints WHERE tool_name = 'mystery_tool'"
    ).fetchone()
    checks.check("mystery fingerprint now categorised as 'code'",
                 post[0] == "code", f"got {post[0]!r}")


def phase_cli_integration(checks: Checks) -> None:
    print("\n== CLI integration ==")
    import json
    import subprocess
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    def run(args):
        return subprocess.run(
            ["uv", "run", "kaos", "--json", *args],
            cwd=str(ROOT), env=env,
            capture_output=True, text=True, encoding="utf-8",
            timeout=60,
        )

    proc = run(["dream", "failures", "--db", str(DB), "--min-count", "1"])
    checks.check("`kaos dream failures` exits 0",
                 proc.returncode == 0, proc.stderr[:200])
    payload = _parse_json(proc.stdout)
    checks.check("failures payload includes category",
                 isinstance(payload, list) and any("category" in r for r in payload))

    # Pick a fp_id and diagnose
    if isinstance(payload, list) and payload:
        fp_id = payload[0]["fp_id"]
        proc = run(["dream", "diagnose", str(fp_id), "--db", str(DB)])
        checks.check(f"`kaos dream diagnose {fp_id}` exits 0",
                     proc.returncode == 0, proc.stderr[:200])
        d = _parse_json(proc.stdout)
        checks.check("diagnose payload has category field",
                     isinstance(d, dict) and "category" in d)

    # systemic — may be empty if prior phase resolved them all
    proc = run(["dream", "systemic", "--db", str(DB)])
    checks.check("`kaos dream systemic` exits 0",
                 proc.returncode == 0, proc.stderr[:200])


def _parse_json(stdout: str):
    import json
    s = stdout.strip()
    if not s:
        return None
    if s.startswith(("[", "{")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    for i, ch in enumerate(s):
        if ch in "[{":
            try:
                return json.loads(s[i:])
            except json.JSONDecodeError:
                return None
    return None


# ── Main ──────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 68)
    print("KAOS — Failure intelligence validation (Dream M2.5)")
    print("=" * 68)

    checks = Checks()

    phase_reset()
    kaos = phase_categorise(checks)
    try:
        phase_fix_outcome(kaos, checks)
        phase_systemic(kaos, checks)
        phase_alert_lifecycle(kaos, checks)
        phase_recategorise(kaos, checks)
    finally:
        kaos.close()
    phase_cli_integration(checks)

    print("\n" + "=" * 68)
    print("Summary")
    print("=" * 68)
    exit_code = checks.summary()
    if exit_code == 0:
        print("\n  [OK]  Failure intelligence validated end-to-end.")
    else:
        print(f"\n  [X]  {len(checks.failed)} validation(s) failed:")
        for name, detail in checks.failed:
            print(f"      - {name}  {detail}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
