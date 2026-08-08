# Acceptance criteria — `kaos eval verify-numerics` (pre-registered 2026-08-08)

Per the v0.10 panel, verify-numerics is **verification infrastructure** (like the
eval harness itself), not a performance mechanism — so it takes no hash-locked
probe. But its acceptance gates are pre-registered here BEFORE the verification
logic is written, and the test suite encodes exactly these thresholds. No
post-hoc softening (that would be the retune-and-rerun the discipline bans).

## What it does

Extract **measurement-shaped numeric claims** from a text artifact (blog, probe
report, README, paper) and classify each against a corpus of recorded
measurements (the experiments journal + any given `results.json` files):

- **verified** — the number resolves to a recorded measurement.
- **unverifiable** — a measurement-shaped number with no trace. (Flagged.)
- **allowlisted** — provably not a measurement claim: semver, dates, years,
  `file.py:123` line refs, URLs, commit hashes, `#`-ordinals/ranks. (Skipped.)

Bare small integers with no unit/decimal/measurement context are treated as
ambiguous and skipped (reported separately), not counted as claims — this is the
precision rescue the panel named.

## Gates (frozen)

- **G-FALSIFY (load-bearing).** Inject a fabricated measurement number (a decimal
  absent from every corpus source) into a copy of a real probe report. The tool
  MUST classify it `unverifiable`. If it ever reports `verified`, the tool is
  INADMISSIBLE. Symmetrically: no fabricated number may be reported verified.
- **G-RECALL.** On a hand-labeled fixture where the ground-truth answers are
  known, the tool must flag 100% of the planted unverifiable numbers.
- **G-PRECISION.** On a hand-labeled set of numbers that DO trace to recorded
  measurements, the false-unverifiable rate must be < 20% and the false-verified
  rate must be < 5% (the false-verified bar is the hard one — a verifier that
  blesses fabrications is worse than none).
- **G-OFFLINE.** The tool runs with all providers/network disabled (regex-only
  core) and produces identical partitions on repeated runs — deterministic, no
  LLM required. LLM segmentation, if ever added, is off by default.

## Non-goals (v1)

Numbers that trace to sources outside kaos.db (leaderboard ranks, third-party
figures) are out of scope and allowlisted, not verified. The tool is a
precision-first lint/gate, not an omniscient fact-checker.
