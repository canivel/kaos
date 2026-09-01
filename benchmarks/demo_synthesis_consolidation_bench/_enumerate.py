"""One-off: materialise the deterministic workload + queries to freeze the
v2 manifests (judge_audit_sample, shift_split_manifest). No arms, no
synthesis. Pure enumeration so the manifests can be pre-registered.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from workload import build_workload
from queries import build_queries, T_SHIFT, SHIFT_DOMAINS, PER_CLASS

SEED = 20260516
HERE = Path(__file__).parent

idx = build_workload(str(HERE / "_enum.db"), SEED, days=90, incidents_per_day=6)
qs = build_queries(idx)

by_class = {}
for q in qs:
    by_class.setdefault((q.qclass, q.split), 0)
    by_class[(q.qclass, q.split)] += 1

print("incidents:", len(idx.incidents),
      "memories:", len(idx.mem_text),
      "queries:", len(qs))
for k in sorted(by_class):
    print("  ", k, by_class[k])

# Frozen audit sample: first 50 qids in stable sorted order.
audit = sorted(q.qid for q in qs)[:50]
manifest = {
    "seed": SEED,
    "world": {"days": 90, "incidents_per_day": 6,
              "incidents": len(idx.incidents), "memories": len(idx.mem_text)},
    "per_class": PER_CLASS,
    "judge_audit_sample": audit,
    "shift_split_manifest": {
        "domains": SHIFT_DOMAINS,
        "templates": T_SHIFT,
        "note": "topic (infra) AND template wording held out vs in_dist",
    },
}
(HERE / "_manifests.json").write_text(json.dumps(manifest, indent=2))
print("wrote _manifests.json")
Path(HERE / "_enum.db").unlink(missing_ok=True)
