"""Read-only statistics over a completed mh_search archive (PSI).

Distilled from Sara/lenz (arXiv:2608.00316): the agent decides, a statistical
backend quantifies. KAOS already owns the backend — ``cluster``/``bootstrap``
CIs and the append-only archive — so this is purely an interface: a deterministic
read that turns the archive's per-problem correctness labels into
candidate-vs-incumbent bootstrap confidence intervals, so a human (or, later and
only behind a probe, the proposer) can see which apparent improvements are within
noise.

Behavior-neutral infrastructure: it reads archive files, computes, and returns —
it never proposes, evaluates, or mutates the frontier. All inference uses the same
seeded ``bootstrap_diff_ci`` every KAOS gate uses, so output is reproducible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from kaos.eval.harness.stats import bootstrap_diff_ci

MIN_LABELS = 2  # below this a bootstrap CI is meaningless


@dataclass
class CandidateStat:
    harness_id: str
    n_problems: int
    accuracy: float
    scores: dict[str, float]
    # vs-incumbent diff on the shared correctness labels (None if not computable)
    mean_diff: float | None = None
    ci_lo: float | None = None
    ci_hi: float | None = None
    distinguishable: bool | None = None  # CI excludes 0?
    is_incumbent: bool = False


@dataclass
class SearchStats:
    search_agent_id: str
    objectives: dict[str, str]
    incumbent_id: str | None
    candidates: list[CandidateStat] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "search_agent_id": self.search_agent_id,
            "objectives": self.objectives,
            "incumbent_id": self.incumbent_id,
            "candidates": [vars(c) for c in self.candidates],
            "notes": self.notes,
        }


def _read_json(afs, agent_id: str, path: str):
    try:
        return json.loads(afs.read(agent_id, path).decode())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _read_labels(afs, agent_id: str, hid: str) -> list[int]:
    """0/1 correctness labels from a harness's per_problem.jsonl (ordered)."""
    try:
        raw = afs.read(agent_id, f"/harnesses/{hid}/per_problem.jsonl").decode()
    except FileNotFoundError:
        return []
    labels: list[int] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            labels.append(1 if json.loads(line).get("correct") else 0)
        except json.JSONDecodeError:
            continue
    return labels


def compute_search_stats(afs, search_agent_id: str) -> SearchStats:
    """Deterministic read-only stats for one mh_search archive.

    Incumbent = the frontier's best point on the first (primary) objective,
    direction-aware. Each candidate's correctness labels are bootstrapped against
    the incumbent's labels; ``distinguishable`` is True iff the 95% CI excludes 0.
    """
    frontier = _read_json(afs, search_agent_id, "/pareto/frontier.json") or {}
    objectives: dict[str, str] = frontier.get("objectives", {})
    fpoints = frontier.get("points", [])

    stats = SearchStats(
        search_agent_id=search_agent_id,
        objectives=objectives,
        incumbent_id=None,
    )

    # discover all evaluated harnesses
    try:
        entries = [e for e in afs.ls(search_agent_id, "/harnesses") if e.get("is_dir")]
    except FileNotFoundError:
        stats.notes.append("no /harnesses archive found")
        return stats
    hids = [e["name"] for e in entries]
    if not hids:
        stats.notes.append("archive contains no harnesses")
        return stats

    # incumbent: best frontier point on the primary objective, direction-aware
    incumbent_id = None
    if fpoints and objectives:
        primary = next(iter(objectives))
        direction = objectives[primary]
        key = lambda p: p.get("scores", {}).get(primary, 0.0)  # noqa: E731
        best = (min if direction == "minimize" else max)(fpoints, key=key)
        incumbent_id = best.get("harness_id")
    stats.incumbent_id = incumbent_id

    incumbent_labels = _read_labels(afs, search_agent_id, incumbent_id) if incumbent_id else []

    for hid in sorted(hids):
        scores = _read_json(afs, search_agent_id, f"/harnesses/{hid}/scores.json") or {}
        labels = _read_labels(afs, search_agent_id, hid)
        acc = sum(labels) / len(labels) if labels else 0.0
        cs = CandidateStat(
            harness_id=hid,
            n_problems=len(labels),
            accuracy=acc,
            scores=scores,
            is_incumbent=(hid == incumbent_id),
        )
        if (
            not cs.is_incumbent
            and len(labels) >= MIN_LABELS
            and len(incumbent_labels) >= MIN_LABELS
        ):
            md, lo, hi = bootstrap_diff_ci(labels, incumbent_labels)
            cs.mean_diff, cs.ci_lo, cs.ci_hi = md, lo, hi
            cs.distinguishable = not (lo <= 0.0 <= hi)
        stats.candidates.append(cs)

    n_cmp = sum(1 for c in stats.candidates if c.mean_diff is not None)
    n_distinct = sum(1 for c in stats.candidates if c.distinguishable)
    if incumbent_id is None:
        stats.notes.append("no frontier incumbent — CIs not computed")
    elif n_cmp == 0:
        stats.notes.append(
            "no candidate had >=2 per-problem labels alongside the incumbent; "
            "CIs uncomputable (underpowered archive)"
        )
    else:
        stats.notes.append(
            f"{n_distinct}/{n_cmp} candidates distinguishable from incumbent "
            f"at 95% CI; the rest are within noise"
        )
    return stats
