"""Dream — system-wide consolidation cycle (neuroplasticity substrate).

Dream replays the KAOS event journal, derives per-entity signals, and scores
every rankable entity (skills, memory, eventually harnesses and policies)
with a recency-weighted success function. It is idempotent, read-mostly in
``--dry-run`` mode, and writes a human-readable digest on every run.

This is the M1 cut: replay → weights → narrative. Structural consolidation
(promote/prune/merge/split), association graphs, failure-fingerprint indexing,
and active execution feedback are later milestones.

Usage (CLI)::

    kaos dream --dry-run                 # write digest, no mutations
    kaos dream --apply                   # persist episode_signals rows
    kaos dream show <run_id>             # re-print a past digest

Usage (Python)::

    from kaos.dream import DreamCycle
    cycle = DreamCycle(kaos)
    result = cycle.run(dry_run=True)
    print(result.digest_markdown)
"""

from kaos.dream.cycle import DreamCycle, DreamResult

__all__ = ["DreamCycle", "DreamResult"]
