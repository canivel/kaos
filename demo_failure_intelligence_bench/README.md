# demo_failure_intelligence_bench — Real triage validation (M2.5)

A realistic scenario that plants a **mix of failure types** — transient,
config, code, and infra — and validates that KAOS's failure intelligence:

1. **Categorises** each fingerprint correctly (transient/config/code/infra)
2. **Records root cause** and suggested action (not just the symptom)
3. **Tracks fix outcomes** — a "known fix" that keeps failing gets
   automatically downgraded so future agents stop applying it
4. **Fires a systemic alert** when many agents hit the same fingerprint
   in a short window — and halts further action until human intervention

This is the difference between "fingerprint = index" (shallow) and
"diagnose + triage = knowledge" (what we actually want).

## Reproduce

```bash
cd demo_failure_intelligence_bench
uv run python scenario.py
```

Exits 0 only when every validation passes.

## What it plants

| # | Scenario | Error injected | Expected category |
|---|---|---|---|
| 1 | Rate-limited API call | `HTTP 429 Too Many Requests: rate limit` | `transient` |
| 2 | Expired API key | `HTTP 401 Unauthorized: invalid api key` | `config` |
| 3 | Harness mutation bug | `KeyError: 'tried_actions'` | `code` |
| 4 | Typo in state access | `AttributeError: 'NoneType' has no attribute 'grid'` | `code` |
| 5 | Local vLLM down | `ConnectionRefusedError: localhost:8000` | `infra` |
| 6 | Disk exhausted | `OSError: [Errno 28] No space left on device` | `infra` |
| 7 | DNS broken | `Could not resolve hostname api.internal` | `infra` |
| 8 | Bad fix that keeps failing | attaches a "retry" fix, records 5+ failures | fix auto-downgrades |
| 9 | Systemic wave | 4 agents hit the same localhost connection-refused inside 60s | alert fires, `agent_count >= 3` |

## What it validates

- Each planted error gets the **right category** via heuristics alone
  (no LLM calls, pure Python)
- Each fingerprint carries a useful `root_cause` (not just the error string)
- Each fingerprint has a `suggested_action` that a human or agent can
  actually act on
- The "bad fix" case downgrades after ≥5 failed attempts (`fix_success_rate
  < 0.5`) — the `fix_summary` column is cleared so future `failure_lookup`
  calls don't return the known-bad suggestion
- The systemic wave creates one `systemic_alerts` row with
  `agent_count ≥ 3`, and `list_active_alerts` returns it
- `ack_alert` and `resolve_alert` lifecycle works

Total: ~30 validations. Exit 0 on all-green.

## Honest framing

This benchmark uses **real heuristics** (no LLM), so the categorisations
are deterministic. For workloads where the heuristics don't match, you
can register a custom `Diagnoser` (or add an LLM-backed one) and the
same framework applies.

The systemic-alert threshold and window are configurable via env vars
(`KAOS_SYSTEMIC_THRESHOLD`, `KAOS_SYSTEMIC_WINDOW_S`). This scenario
sets them to 3 agents / 60 seconds for deterministic testing.
