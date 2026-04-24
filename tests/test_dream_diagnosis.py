"""Tests for M2.5: diagnosis + fix-outcome + systemic detection."""

from __future__ import annotations

import time

import pytest

from kaos.core import Kaos
from kaos.dream import auto
from kaos.dream.diagnosis import (
    Diagnosis,
    diagnose,
    list_diagnosers,
    register_diagnoser,
    reset_registry,
)
from kaos.dream.phases import failures as failures_phase


@pytest.fixture
def afs(tmp_path, monkeypatch):
    # Lower systemic threshold & window for deterministic tests
    monkeypatch.setenv("KAOS_SYSTEMIC_THRESHOLD", "3")
    monkeypatch.setenv("KAOS_SYSTEMIC_WINDOW_S", "60")
    monkeypatch.setenv("KAOS_DREAM_THRESHOLD", "1000000")  # don't trigger consolidation
    fs = Kaos(db_path=str(tmp_path / "diag.db"))
    yield fs
    fs.close()
    reset_registry()


def _plant_fail(afs: Kaos, agent_name: str, tool: str, error: str) -> str:
    """Spawn an agent, plant an errored tool_call, and fail it."""
    aid = afs.spawn(agent_name)
    call_id = afs.log_tool_call(aid, tool, {})
    afs.start_tool_call(call_id)
    afs.complete_tool_call(call_id, output={}, status="error",
                           error_message=error, token_count=0)
    afs.fail(aid)
    return aid


# ── Heuristic diagnosers (pure unit) ────────────────────────────────


class TestHeuristicDiagnosis:
    def test_connection_refused_local_is_infra(self):
        d = diagnose("http_get", "ConnectionRefusedError: localhost:8000")
        assert d.category == "infra"
        assert d.confidence >= 0.85
        assert "local" in d.root_cause.lower()

    def test_connection_refused_remote_is_infra(self):
        d = diagnose("http_get", "Connection refused to api.example.com:443")
        assert d.category == "infra"
        assert "remote" in d.root_cause.lower() or "unreachable" in d.root_cause.lower()

    def test_rate_limit_is_transient(self):
        d = diagnose("http_post", "HTTP 429 Too Many Requests: rate limit exceeded")
        assert d.category == "transient"
        assert d.confidence >= 0.9

    def test_timeout_is_transient_by_default(self):
        d = diagnose("http_get", "Request timed out after 30s")
        assert d.category == "transient"

    def test_timeout_with_hang_hint_is_code(self):
        d = diagnose("process", "deadlock detected, operation timed out waiting")
        assert d.category == "code"

    def test_auth_401_is_config(self):
        d = diagnose("http_get", "HTTP 401 Unauthorized: invalid api key")
        assert d.category == "config"
        assert "credential" in d.root_cause.lower() or "key" in d.root_cause.lower()

    def test_keyerror_is_code(self):
        d = diagnose("harness_run", "KeyError: 'tried_actions'")
        assert d.category == "code"

    def test_typeerror_is_code(self):
        d = diagnose("harness_run",
                     "TypeError: click requires data dict, got None")
        assert d.category == "code"

    def test_disk_full_is_infra(self):
        d = diagnose("fs_write", "OSError: [Errno 28] No space left on device")
        assert d.category == "infra"

    def test_dns_is_infra(self):
        d = diagnose("http_get", "could not resolve hostname api.example.com")
        assert d.category == "infra"

    def test_missing_data_is_code(self):
        d = diagnose("call", "missing required argument: 'x'")
        assert d.category == "code"

    def test_unknown_falls_through(self):
        d = diagnose("random_tool", "Some weird error that no heuristic knows")
        assert d.category == "unknown"
        assert d.confidence == 0.0


class TestRegistryPluggability:
    def test_user_diagnoser_beats_builtin(self):
        class CustomDiagnoser:
            name = "custom_override"

            def try_diagnose(self, tool_name, error, context):
                if "custom-flag" in error:
                    return Diagnosis(category="config",
                                     root_cause="Custom rule matched",
                                     suggested_action="do nothing",
                                     method="heuristic",
                                     confidence=1.0)
                return None

        register_diagnoser(CustomDiagnoser())
        try:
            d = diagnose("tool", "custom-flag encountered")
            assert d.root_cause == "Custom rule matched"
            assert d.method == "heuristic"
        finally:
            reset_registry()

    def test_reset_registry_restores_builtins(self):
        class X:
            name = "x"

            def try_diagnose(self, *args, **kwargs):
                return None

        before = set(list_diagnosers())
        register_diagnoser(X())
        assert "x" in list_diagnosers()
        reset_registry()
        assert set(list_diagnosers()) == before


# ── Integration: fingerprint flow ──────────────────────────────────


class TestFingerprintWithDiagnosis:
    def test_new_fingerprint_gets_diagnosed(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused: localhost:8000")
        row = afs.conn.execute(
            "SELECT category, root_cause, diagnostic_method FROM failure_fingerprints"
        ).fetchone()
        assert row is not None
        assert row[0] == "infra"
        assert row[1] is not None
        assert row[2] == "heuristic"

    def test_unknown_fingerprint_records_only_timestamp(self, afs):
        _plant_fail(afs, "a1", "exotic_tool", "totally unique error nobody's seen")
        row = afs.conn.execute(
            "SELECT category, root_cause, diagnosed_at FROM failure_fingerprints"
        ).fetchone()
        assert row[0] == "unknown"
        assert row[1] is None
        assert row[2] is not None  # timestamp set so we don't re-diagnose forever

    def test_occurrences_recorded(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused")
        _plant_fail(afs, "a2", "http_get", "Connection refused")
        n = afs.conn.execute("SELECT COUNT(*) FROM failure_occurrences").fetchone()[0]
        assert n == 2

    def test_recategorise_all_fills_unknown(self, afs):
        # Plant an error, plant a second diagnoser that catches it later
        _plant_fail(afs, "a1", "tool_x", "exotic pattern-xyz")
        cat_before = afs.conn.execute(
            "SELECT category FROM failure_fingerprints"
        ).fetchone()[0]
        assert cat_before == "unknown"

        class PatternXyzDiagnoser:
            name = "pattern_xyz"

            def try_diagnose(self, tool_name, error, context):
                if "pattern-xyz" in error:
                    return Diagnosis(category="code",
                                     root_cause="Pattern-xyz triggered",
                                     suggested_action="...",
                                     method="heuristic",
                                     confidence=0.9)
                return None

        register_diagnoser(PatternXyzDiagnoser())
        try:
            updated = failures_phase.recategorise_all(afs.conn)
            assert updated == 1
            cat_after = afs.conn.execute(
                "SELECT category FROM failure_fingerprints"
            ).fetchone()[0]
            assert cat_after == "code"
        finally:
            reset_registry()


# ── Fix-outcome tracking ────────────────────────────────────────────


class TestFixOutcomeTracking:
    def test_success_bumps_counts(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused")
        fp_id = afs.conn.execute(
            "SELECT fp_id FROM failure_fingerprints"
        ).fetchone()[0]
        result = failures_phase.record_fix_outcome(afs.conn, fp_id,
                                                    succeeded=True)
        assert result["fix_attempts"] == 1
        assert result["fix_success_count"] == 1
        assert result["fix_success_rate"] == 1.0
        assert result["downgraded"] is False

    def test_failure_not_counted_as_success(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused")
        fp_id = afs.conn.execute("SELECT fp_id FROM failure_fingerprints").fetchone()[0]
        r = failures_phase.record_fix_outcome(afs.conn, fp_id, succeeded=False)
        assert r["fix_attempts"] == 1
        assert r["fix_success_count"] == 0

    def test_low_success_rate_downgrades_fix(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused")
        fp_id = afs.conn.execute("SELECT fp_id FROM failure_fingerprints").fetchone()[0]
        failures_phase.attach_fix(afs.conn, fp_id,
                                  fix_summary="retry with backoff")
        # 5 failed attempts -> below 50% -> downgrade
        for _ in range(4):
            r = failures_phase.record_fix_outcome(afs.conn, fp_id, succeeded=False)
            assert r["downgraded"] is False
        r = failures_phase.record_fix_outcome(afs.conn, fp_id, succeeded=False)
        assert r["downgraded"] is True
        # fix_summary should be cleared
        summary = afs.conn.execute(
            "SELECT fix_summary FROM failure_fingerprints WHERE fp_id = ?",
            (fp_id,),
        ).fetchone()[0]
        assert summary is None

    def test_good_fix_not_downgraded(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused")
        fp_id = afs.conn.execute("SELECT fp_id FROM failure_fingerprints").fetchone()[0]
        failures_phase.attach_fix(afs.conn, fp_id, fix_summary="retry")
        for _ in range(6):
            r = failures_phase.record_fix_outcome(afs.conn, fp_id, succeeded=True)
            assert r["downgraded"] is False


# ── Systemic detection ─────────────────────────────────────────────


class TestSystemicDetection:
    def test_three_agents_same_fp_fires_alert(self, afs):
        # SYSTEMIC_THRESHOLD=3 from fixture
        _plant_fail(afs, "a1", "http_get", "Connection refused: upstream")
        _plant_fail(afs, "a2", "http_get", "Connection refused: upstream")
        assert afs.conn.execute(
            "SELECT COUNT(*) FROM systemic_alerts"
        ).fetchone()[0] == 0

        _plant_fail(afs, "a3", "http_get", "Connection refused: upstream")
        rows = afs.conn.execute(
            "SELECT agent_count, window_seconds, root_cause FROM systemic_alerts"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 3  # agent_count
        assert rows[0][1] == 60  # window_seconds from env

    def test_different_fingerprints_dont_combine(self, afs):
        _plant_fail(afs, "a1", "http_get", "Connection refused")
        _plant_fail(afs, "a2", "http_post", "something entirely different")
        _plant_fail(afs, "a3", "http_delete", "third distinct error pattern")
        assert afs.conn.execute(
            "SELECT COUNT(*) FROM systemic_alerts"
        ).fetchone()[0] == 0

    def test_alert_debounced(self, afs):
        # Fire alert once, then add another occurrence immediately.
        # Debounce window is 60s — second alert should NOT fire.
        for i in range(3):
            _plant_fail(afs, f"a{i}", "http_get", "Connection refused")
        count_after_first = afs.conn.execute(
            "SELECT COUNT(*) FROM systemic_alerts"
        ).fetchone()[0]
        assert count_after_first == 1

        _plant_fail(afs, "a4", "http_get", "Connection refused")
        count_after_more = afs.conn.execute(
            "SELECT COUNT(*) FROM systemic_alerts"
        ).fetchone()[0]
        assert count_after_more == 1  # still just one alert


class TestAlertLifecycle:
    def test_list_active_returns_unresolved(self, afs):
        for i in range(3):
            _plant_fail(afs, f"a{i}", "http_get", "Connection refused")
        alerts = failures_phase.list_active_alerts(afs.conn)
        assert len(alerts) == 1

    def test_ack_updates_acked_at(self, afs):
        for i in range(3):
            _plant_fail(afs, f"a{i}", "http_get", "Connection refused")
        alert_id = afs.conn.execute(
            "SELECT alert_id FROM systemic_alerts"
        ).fetchone()[0]
        ok = failures_phase.ack_alert(afs.conn, alert_id, acked_by="danilo")
        assert ok is True
        acked_at, acked_by = afs.conn.execute(
            "SELECT acked_at, acked_by FROM systemic_alerts WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()
        assert acked_at is not None
        assert acked_by == "danilo"

    def test_resolve_removes_from_active_list(self, afs):
        for i in range(3):
            _plant_fail(afs, f"a{i}", "http_get", "Connection refused")
        alert_id = afs.conn.execute(
            "SELECT alert_id FROM systemic_alerts"
        ).fetchone()[0]
        failures_phase.resolve_alert(afs.conn, alert_id, resolved_by="danilo")
        assert failures_phase.list_active_alerts(afs.conn) == []

    def test_resolve_nonexistent_returns_false(self, afs):
        ok = failures_phase.resolve_alert(afs.conn, 999)
        assert ok is False


class TestSetCategory:
    def test_manual_override(self, afs):
        _plant_fail(afs, "a1", "exotic", "totally unique error")
        fp_id = afs.conn.execute(
            "SELECT fp_id FROM failure_fingerprints"
        ).fetchone()[0]
        assert failures_phase.set_category(
            afs.conn, fp_id, category="config",
            root_cause="manually determined: wrong env var",
            suggested_action="set FOO=bar",
        ) is True
        row = afs.conn.execute(
            "SELECT category, root_cause, diagnostic_method "
            "FROM failure_fingerprints WHERE fp_id = ?",
            (fp_id,),
        ).fetchone()
        assert row[0] == "config"
        assert "wrong env var" in row[1]
        assert row[2] == "user"
