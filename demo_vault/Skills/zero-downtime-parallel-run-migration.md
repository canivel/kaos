---
type: skill
skill_id: 5
name: zero-downtime-parallel-run-migration
source_agent: "[[payment-engine-agent]]"
use_count: 0
success_count: 0
success_rate: ""
created_at: "2026-04-15T17:12:25.811"
updated_at: "2026-04-15T17:12:25.811"
tags: [skill, migration, zero-downtime, parallel-run, monolith, rollback]
---

# zero-downtime-parallel-run-migration

> [!kaos-skill] Dual-write parallel-run router for zero-downtime monolith cutover. Result diffing, per-cohort feature flags, automatic rollback on drift.
> Source: [[payment-engine-agent]]  ·  use_count: 0

## Template
```
Migrate {project} from {legacy_system} using parallel-run strategy. Dual-write for {parallel_run_days} days, diff tolerance {diff_threshold}%, per-client feature flags, auto-rollback trigger.
```

## Applied by
_(no recorded applications yet)_