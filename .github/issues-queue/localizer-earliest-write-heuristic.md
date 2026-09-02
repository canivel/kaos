# Critical-step localizer REJECTed by AFB v1: "earliest write before the first error" points at session set-up

**Found by:** `benchmarks/afb` self-run, KAOS 2.1.0 (2026-09-02), lock `018a9fff…`, experiment `afb-v1-self`.

**Result:** fault-localization median **9.5** entries inspected before the planted decisive
step (gate ≤ 5), 0/12 exact hits — every other AFB test passed (checkpoint fidelity 100 %,
journal completeness 100 %, isolation 0 leaks, replay deterministic, recovery overhead 8 %).

**Why:** `kaos/dream/phases/localize.py::_heuristic_localize` takes the *earliest* decision
step (write-like tool call) before the first error. Real sessions begin with set-up writes,
so the pointer lands on step 0 and the auditor walks 7–11 entries to the culprit. The
"a bug that festered N steps" assumption is the wrong prior when the session's first writes
are benign scaffolding.

**Constraints for a fix (falsifiable-eval discipline):**
- Must ACCEPT against the *same* AFB lock (no gate changes) **and** not regress the v0.8.3
  localizer bench (5/5 planted bugs within ±1 step).
- Candidate heuristics to probe: prefer the latest decision step that shares a target
  (path / label) with the error step; down-weight decisions that precede a long run of
  successful steps; fall back to "earliest" only when no shared-target decision exists.
- Register the candidate as a probe in `kaos experiment log` before running.

Priority: P1 · Type: bug · Area: kaos/dream/phases/localize.py, benchmarks/afb

Reported by AI agent
