# Agent Forensics Bench (AFB) — specification v1.0

AFB measures whether an agent framework can answer, after the fact and with
evidence, the questions a production owner or an auditor asks when an agent
run goes wrong: *what exactly did it do, can I put it back, can I find where
it went wrong, and can I reproduce it?* No existing benchmark measures these
properties; they are orthogonal to recall quality or task success.

Every test runs on **synthetic, seed-determined sessions**
(`generate_session.py`): a fixed number of agents, each executing a fixed
number of tool calls with a known shape — read-only steps, then one decisive
write (the planted culprit), more reads, then a visible error on a path that
does not exist. Because the shape is known, ground truth is known, and the
same seed reproduces the same sessions byte for byte.

The run is governed by `preregistration.json`, whose sha256 is hard-coded in
`run_afb.py`. Editing the gates after seeing results is not possible without
a new hash and a new commit — the verdict is tamper-evident.

## Tests

| # | Test | What is measured | Why it matters | Gate |
|---|------|------------------|----------------|------|
| 1 | Checkpoint fidelity | Hash of the agent's whole file tree after `restore` equals the hash taken at `checkpoint` time, for every agent. | "Put it back exactly" is the basis of safe experimentation and of rollback after a bad run. Byte-exact or it isn't a checkpoint. | 100 % |
| 2 | Journal completeness | Every executed tool call has a durable record (a `tool_calls` row and start/end events). | EU AI Act Art. 12-style automatic logging, SOC 2 change evidence, incident review: a journal with gaps is not evidence. | 100 % |
| 3 | Cross-agent isolation | Agent B cannot read agent A's file (must raise), and a memory written by A is not returned by a search scoped to B. Counted as leaks. | Multi-agent runs on sensitive data need enforced boundaries, not conventions. | 0 leaks |
| 4 | Fault localization | Starting from the framework's critical-step pointer and walking outward, how many journal entries does an auditor inspect before reaching the planted culprit? 1 = exact hit; no pointer = every entry. Median across agents. | The visible error is rarely the cause. Post-mortems are bounded by how fast you find the decisive step. | median ≤ 5 |
| 5 | Cold-start replay | Replaying each agent's journal (recorded tool inputs, in order) into a fresh database reproduces the original file-tree hash; two replays agree. | Reproducibility: can a reviewer rebuild the state from the record alone? | 100 % match, deterministic |
| 6 | Mid-task recovery | Simulate a crash `crash_offset` steps after a mid-session checkpoint, restore, replay the rest. Overhead = redone steps / total steps. | Long runs die. The cost of resuming from a checkpoint should be a small fraction of starting over. | < 20 % |

Verdict rule (from the lock): **ACCEPT** only if every gate holds; **REJECT**
if any fails, with the failing numbers; **VOID** if the generator is not
seed-deterministic or the two replays differ (the instrument itself is
broken — no claim is made).

## Running it against KAOS

```bash
uv run python benchmarks/afb/run_afb.py            # writes results/kaos_v<version>.json
uv run python benchmarks/afb/run_afb.py --output results/afb.json   # what the kaos-eval Action does
```

Exit code is 0 on ACCEPT, 1 otherwise; the result file always carries the
verdict and every per-test number.

## Running it against another framework

Implement `adapter.ForensicsAdapter` (see `compat/run_external.md`) and
call `run_afb.run(lock, db_path)` with your adapter substituted for
`KaosAdapter`. Tests 3 (memory half) and 4 use KAOS-specific surfaces; a
framework without a memory store or a critical-step localizer reports those
as *unsupported*, which is the honest score — "we did not measure" is not
"we passed".

## What AFB does not measure

Task success, recall quality, cost, or latency. It is deliberately narrow:
a framework can be excellent at coding and score zero here, and that is the
point — the properties in this table are the ones you only miss after the
incident.
