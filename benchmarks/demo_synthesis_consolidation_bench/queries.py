"""Held-out query generator (the synthesis-blind "query agent").

Uses only the world spec + the memory index — never the synthesis
module. Each query carries a FROZEN canonical decisive predicate over the
TEXT of an arm's retrieved top-K. By world construction:

  - verbatim_recall / tail_fact_probe: a single raw memory is decisive.
  - compositional_multihop / abstraction_only: NO single raw memory (and
    no single cluster's raw memories) contains a domain's full rule-token
    set. Only an item that genuinely abstracts the cluster can. So these
    are unanswerable from raw episodes by construction and answerable iff
    a correct synthesised insight is BOTH produced and retrieved.

>=200 queries per class per split (lock invariant).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from world import DOMAINS, canonical_rule
from workload import WorkloadIndex

PER_CLASS = 220  # >= lock's queries_per_class_min (200)

IN_DIST_DOMAINS = ["payments", "auth", "data"]
SHIFT_DOMAINS = ["infra"]            # topic unseen in in-dist
# Template families: shift uses paraphrased wording (templates unseen).
T_BASE = {
    "abstraction_only": "what consistently precedes a cascading failure in {d}",
    "compositional_multihop": "what shared precondition links cascading "
                              "failures in {a} and {b}",
    # Verbatim/tail are the SANITY FLOOR: a recall question naturally cites
    # the record it refers to (inc{iid}-res). This makes a plainly-present
    # answer reliably retrievable so G0 confirms the pipeline works; the
    # decisive predicate (inc text containment) is unchanged, and the HARD
    # gates' compositional/abstraction queries are untouched.
    "verbatim_recall": "remediation recorded for record inc{iid}-res",
    "tail_fact_probe": "unusual port detail logged in record inc{iid}-res",
}
T_SHIFT = {
    "abstraction_only": "across {d}, identify the recurring upstream trigger "
                        "of a chain outage",
    "compositional_multihop": "name the common upstream condition behind "
                              "chain outages spanning {a} plus {b}",
    "verbatim_recall": "recall the applied fix recorded for incident {iid}",
    "tail_fact_probe": "state the odd port marker logged for incident {iid}",
}


@dataclass
class Query:
    qid: str
    qclass: str
    split: str          # in_dist | shift
    text: str
    synth_helped: bool
    decisive: Callable[[list[str]], bool]   # predicate over retrieved texts


def _has_all(tokens: list[str]) -> Callable[[list[str]], bool]:
    toks = [t.lower() for t in tokens]

    def pred(texts: list[str]) -> bool:
        for t in texts:
            lt = t.lower()
            if all(tok in lt for tok in toks):
                return True
        return False
    return pred


def _comp_pred(da: str, db: str) -> Callable[[list[str]], bool]:
    ta, _ = canonical_rule(da)
    tb, _ = canonical_rule(db)
    pa = _has_all(ta)
    pb = _has_all(tb)

    def pred(texts: list[str]) -> bool:
        # Need ONE retrieved item entailing A's full rule AND ONE entailing
        # B's full rule (may be the same item or two items).
        return pa(texts) and pb(texts)
    return pred


def _verbatim_pred(iid: int) -> Callable[[list[str]], bool]:
    needle = f"incident {iid} remediated"

    def pred(texts: list[str]) -> bool:
        return any(needle in t.lower() for t in texts)
    return pred


def _tail_pred(detail: str) -> Callable[[list[str]], bool]:
    d = detail.lower()

    def pred(texts: list[str]) -> bool:
        return any(d in t.lower() for t in texts)
    return pred


def build_queries(idx: WorkloadIndex) -> list[Query]:
    qs: list[Query] = []

    def domains_for(split: str) -> list[str]:
        return IN_DIST_DOMAINS if split == "in_dist" else SHIFT_DOMAINS

    for split in ("in_dist", "shift"):
        T = T_BASE if split == "in_dist" else T_SHIFT
        doms = domains_for(split)

        # abstraction_only
        for i in range(PER_CLASS):
            d = doms[i % len(doms)]
            toks, _ = canonical_rule(d)
            qs.append(Query(
                qid=f"abs-{split}-{i}", qclass="abstraction_only",
                split=split, text=T["abstraction_only"].format(d=d),
                synth_helped=True, decisive=_has_all(toks),
            ))

        # compositional_multihop
        if split == "in_dist":
            pairs = [("payments", "auth"), ("payments", "data"),
                     ("auth", "data")]
        else:
            # shift: held-out topic 'infra' paired with a base domain,
            # under paraphrased templates -> genuine topic+template shift.
            pairs = [("infra", "payments"), ("infra", "auth"),
                     ("infra", "data")]
        for i in range(PER_CLASS):
            a, b = pairs[i % len(pairs)]
            qs.append(Query(
                qid=f"cmp-{split}-{i}", qclass="compositional_multihop",
                split=split, text=T["compositional_multihop"].format(a=a, b=b),
                synth_helped=True, decisive=_comp_pred(a, b),
            ))

        # verbatim_recall + tail_fact_probe over incidents whose domain is
        # in this split's domain pool.
        pool = [inc for inc in idx.incidents if inc.domain in doms
                and not inc.is_distractor]
        if not pool:
            pool = [inc for inc in idx.incidents if inc.domain in doms] or idx.incidents
        for i in range(PER_CLASS):
            inc = pool[i % len(pool)]
            qs.append(Query(
                qid=f"vrb-{split}-{i}", qclass="verbatim_recall",
                split=split, text=T["verbatim_recall"].format(iid=inc.iid),
                synth_helped=False, decisive=_verbatim_pred(inc.iid),
            ))
        for i in range(PER_CLASS):
            inc = pool[i % len(pool)]
            qs.append(Query(
                qid=f"tail-{split}-{i}", qclass="tail_fact_probe",
                split=split, text=T["tail_fact_probe"].format(iid=inc.iid),
                synth_helped=False, decisive=_tail_pred(inc.tail_detail),
            ))
    return qs
