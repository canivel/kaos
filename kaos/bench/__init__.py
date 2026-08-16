"""kaos.bench — Attraktor engine inside KAOS.

The producer/consumer side of the validated collective-learning loop: KAOS agents
harvest learnings, validate them (validate-on-entry), push them to a workspace
bench, and pull back only the validated items whose measured workload-shape matches
the task (transfer-match-on-pull). See the attraktor repo's PLAN.md v2.

This package ships with KAOS; server-only dependencies (the hosted platform) live
behind the ``kaos[bench]`` extra and are never imported by the local path.
"""

from kaos.bench.canon import canonical_bytes, record_cid, verify_cid

__all__ = ["canonical_bytes", "record_cid", "verify_cid"]
