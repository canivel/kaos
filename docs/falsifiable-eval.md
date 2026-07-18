# Falsifiable Eval — the kill-switch primitive

> How KAOS gates its own development: no mechanism ships without passing a probe it could fail. This doc covers the discipline, the `kaos.eval.harness` API, the CLI/MCP surfaces, and the experiments journal.

**The problem.** Harness engineering's open critique is that changes get shipped on the demo that worked — there's no verification that a change *actually helped* ([Böckeler, martinfowler.com](https://martinfowler.com/articles/exploring-gen-ai/harness-engineering-memo.html)). Post-hoc evals don't fix this: if the gates are written after the results are seen, the gates move.

**The KAOS answer.** Pre-registration with tamper evidence. The kill gates are written *before* any feature code exists, hash-locked, and the harness mechanically refuses to run against an edited lock. The verdict is binding. Ten mechanism candidates have been evaluated this way since v0.7 — **zero shipped on hope**; the REJECT/VOID verdicts live in the repo with their full audit trails (`demo_synthesis_consolidation_bench/`, `demo_action_realization_bench/`).

---

## The lifecycle

```
1. PRE-REGISTER   Write ISA.lock.json: arms, workload invariants, kill gates
                  G1..GN with exact thresholds, verdict rule. Compute its
                  sha256. Commit it. Add the hash to the probe's
                  known_sha256 allow-list.
                        │
2. FALSIFY        Substitute the feature arm with its baseline (FULL := B0).
   (self-test)    The kill gate MUST fire. A harness in which the feature
                  cannot lose is INADMISSIBLE — its later "pass" means nothing.
                        │
3. RUN            Execute all arms, judge blindly, compute gates, emit the
                  binding verdict: ACCEPT / REJECT / VOID. No retune-and-rerun.
                        │
4. VERIFY         Recompute the verdict from the saved results.json against
                  the gate code at HEAD — confirms nothing drifted.
                        │
5. JOURNAL        kaos experiment log — the run is recorded with git_sha,
                  lock_sha256, arms, gates, verdict. Queryable forever.
```

**Verdict rule** (uniform, in `compute_verdict` — no probe can override it):

- **VOID** — no kill-gates registered, judge kappa below threshold, a sanity (non-kill) gate failed, or the multi-run power budget was unmet. The run is *uninterpretable*, not a feature verdict.
- **ACCEPT** — at least one kill-gate exists and every kill-gate passed.
- **REJECT** — any kill-gate failed.

REJECT and VOID are *successful outcomes* of the process: they keep unproven mechanisms out of the framework.

---

## Writing a probe

Minimal working shape (full runnable version: [`examples/falsifiable_probe.py`](../examples/falsifiable_probe.py)):

```python
from kaos.eval.harness import Probe, GateOutcome, bootstrap_diff_ci

class MyProbe(Probe):
    lock_path    = "ISA.lock.json"          # gates written BEFORE any code
    known_sha256 = {"5aa9c10d...": "v1"}    # edited lock -> LockTamperError

    def arms(self):
        return ["B0", "L1", "FULL"]         # baseline, lesion, feature

    def gates(self, arms):
        md, lo, hi = bootstrap_diff_ci(arms["FULL"].labels({"hard"}),
                                       arms["B0"].labels({"hard"}))
        return [GateOutcome("G1", "beats baseline",
                            passed=md >= 0.10 and lo > 0.0, kill=True,
                            detail=f"diff={md:+.3f} lo={lo:+.3f}")]

    def run(self, *, out_dir, **kw):
        ...  # execute arms, persist results.json (include per_query per arm
             # so verify() can reconstruct), return the result dict
```

Design rules that keep probes honest:

- **Arms include lesions.** A never-fire lesion (L1) separates "library presence" from "intervention"; a random-fire lesion (L2) controls for "any intervention helps". A lift that lesions reproduce is not causal.
- **The baseline is KAOS-native, not a straw man.** Beating plain ReAct proves nothing; the bar is the strongest scaffold the framework already ships.
- **Workload invariants are locked too** — e.g. "organic incidents only, synthetic substitution forbidden, n ≥ 200 or VOID". The action-realization probe VOIDed exactly this way (n=2 organic incidents), and per the lock that verdict could not be rescued by generating synthetic data.

## Statistics

`kaos.eval.harness.stats` is the only inferential machinery gates may use — one place, seeded, so "lo > 0" means the same thing in every probe:

- `bootstrap_diff_ci(a, b)` — within-run bootstrap over query labels. Valid for single-run probes.
- `cluster_bootstrap_diff_ci(runs_a, runs_b)` — resamples **runs** (clusters), for multi-run probes. Single-run pass@1 varies 2.2–6.0pp between runs even at temperature 0 — inside the margin of a +4pp gate — so a within-run CI can be confidently wrong about a run-unstable effect.
- `check_power_budget(lock, runs_executed)` — if the lock declares `statistics.runs_per_condition: N`, executing fewer than N runs **VOIDs the verdict**. The power budget is binding like gates are; there is no quiet weakening of the interval.

## Blind judging

`judge_arm` routes per-query outcomes through `SurrogateVerifier` on an **anonymised, shuffled stream** — the judge never sees arm identity, so arm leakage is impossible by construction. Kappa is a real agreement statistic against an optional independent second label; probes with purely mechanical ground truth (set-membership, canonical equality) are explicitly **kappa-exempt** (`None`) rather than reporting a fake 1.0.

---

## CLI

```bash
kaos eval probe falsify --probe pkg.module:MyProbe          # admissibility self-test
kaos eval probe run     --probe pkg.module:MyProbe --out-dir out/
kaos eval probe verify  --probe pkg.module:MyProbe --results out/results.json
```

`run` and `verify` **exit non-zero on REJECT/VOID** — wire them into CI and your harness changes gate like code:

```yaml
# e.g. in CI
- run: uv run kaos eval probe run --probe bench.my_probe:MyProbe --out-dir out/
  # job fails unless the binding verdict is ACCEPT
```

## Experiments journal

Every run should be journaled (schema v9 `experiments` table):

```bash
kaos experiment log  --name my-probe --family probe \
    --verdict "REJECT: kill gate(s) failed: G1" \
    --lock-sha256 5aa9c10d... --results-path out/results.json
kaos experiment list --verdict-prefix REJECT     # what have we tried?
kaos experiment compare 41 42                    # what changed between runs?
kaos experiment show 42
```

`git_sha` auto-fills from `git rev-parse HEAD`. The journal is append-only — it is the queryable institutional memory behind "didn't we already evaluate that?"

## MCP

All surfaces are MCP tools since v0.9.1: `eval_probe_{falsify,run,verify}`, `experiment_{log,list,show,compare}`, plus `doctor_proposer` for provider smoke checks. See [mcp-integration.md](mcp-integration.md).

---

## The ledger

The discipline's track record is the proof it works. Candidates evaluated since v0.7: SAGE (REJECT — hard-constraint conflict), synthesis-as-consolidation LLM + extractive (REJECT + DO-NOT-BUILD — the FTS-without-embeddings structural impossibility), AutoResearchClaw (orthogonal), HASP (REJECT — absorbed by native baseline), Life-Harness action-realization (VOID — insufficient organic data, lock forbade synthetic), UserHarness (PARK), per-agent-DB sharding (REJECT-by-measurement — `demo_storage_scale_bench/`), MATM (REJECT — embedding-dependent), Atomic Task Graph (PARK — probe-candidate). **Zero shipped on hope.**
