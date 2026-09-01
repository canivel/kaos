# Attraktor Loop — Binding Probe (pre-registration)

**Lock:** `ISA.lock.json`, sha256 `4de65deec006d0f4f6815960b790279ce657e655615e687b5a1bd21b2032135e` (v1)
**Pre-registered:** 2026-08-16 — BEFORE any organic arm data existed (bench.db held 3 seed records, 0 arm-assigned episodes).
**Stakes:** ACCEPT gates the Cloudflare SaaS sprint (D6). REJECT means the loop does not ship as a default. This probe can kill Attraktor.

## What it measures

Live flagship-workspace episodes only. `arms_mode: probe` deterministically
assigns every MATCHED pull to an arm by `sha256(agent_id|task_hash)`:

| Arm | Rate | Treatment |
|---|---|---|
| ON | 45% | normal injection (honesty surface, advisory framing) |
| OFF | 45% | match ledgered, nothing injected — causal control |
| SCRAMBLED | 10% | word-shuffled payloads, same tokens — placebo |

Episode outcome = the **runner's** completion status (`outcome_source` CHECK
makes agent self-report unrepresentable). Episode = one arm-assigned
`bench_pulls` row joined to its `outcome_telemetry` rows via `pull_id`.

## Gates (frozen)

- **G0** (VOID): floors on≥30, off≥30, scrambled≥10, pulls≥75; arm shares within ±0.15 of locked rates.
- **G1** (KILL): Newcombe one-sided 90% LB of (p_on − p_off) > 0.
- **G2** (KILL): pull latency p95 < 150 ms over ≥75 arm-assigned pulls.
- **G3** (KILL): match-rate ≥ 0.20 (D1) — served/shadow pulls ÷ all arm-assigned pulls.
- **G4** (KILL): LB of (p_scrambled − p_off) must NOT exceed 0 — padding must not reproduce the gain.

**Falsification self-test:** ON := OFF must fail G1, else the harness is
inadmissible and refuses to bind.

**Verdict:** VOID if G0 fails; ACCEPT iff G1∧G2∧G3∧G4; any kill-gate failure
REJECTS. No retune-and-rerun.

## Running

```bash
uv run kaos bench probe            # progress surface (VOID until floors met)
uv run kaos --json bench probe     # same, machine-readable
uv run kaos bench probe --bind --out demo_attraktor_loop_bench
                                   # THE binding run: writes results.json
```

**Honest prior:** ACCEPT ~0.30. Ranked risks: G3 match famine (brain starts
nearly empty), G1 power at n=30/arm, G4 padding effects. A REJECT or VOID is a
successful probe outcome and is published with its reasoning (D0.1).
