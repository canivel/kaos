"""Deterministic incident world with LATENT failure rules.

Honest-test invariant: each domain has a generalization (the "latent
rule") that is NEVER stated in any single incident memory. Each incident
memory carries only a SUBSET of the rule's concept tokens plus surface
noise. The full token set co-occurs in one text only if something
abstracts across the cluster. The judge later checks token-set
containment in a *retrieved* item — so a feature passes a hard query iff
a retrieved item genuinely entails the rule, which a correct cluster-blind
synthesis must produce and raw episodes provably cannot.

Nothing here is shown to the synthesizer. The synthesizer sees only the
generated incident memory TEXT.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# Domains, each with a frozen latent rule expressed as a REQUIRED concept
# token set. No single incident memory will contain the whole set.
DOMAINS = {
    "payments": {
        "rule_tokens": ["ledgerdb", "p99latency", "deployfreeze", "inactive"],
        "rule_phrase": ("cascading payment failures are preceded by ledgerdb "
                        "p99latency breach while deployfreeze is inactive"),
        "services": ["pay-gateway", "pay-ledger", "pay-router", "pay-webhook"],
        "symptoms": ["timeout", "5xxspike", "queuebacklog", "retrystorm"],
    },
    "auth": {
        "rule_tokens": ["tokencache", "evictionburst", "replicalag", "quorumloss"],
        "rule_phrase": ("auth cascades follow a tokencache evictionburst "
                        "coinciding with replicalag causing quorumloss"),
        "services": ["auth-edge", "auth-token", "auth-store", "auth-mfa"],
        "symptoms": ["401flood", "loginfail", "sessiondrop", "latencyspike"],
    },
    "data": {
        "rule_tokens": ["shardrebalance", "hotpartition", "compaction", "stall"],
        "rule_phrase": ("data outages start when shardrebalance hits a "
                        "hotpartition during compaction causing stall"),
        "services": ["data-shard", "data-index", "data-stream", "data-cache"],
        "symptoms": ["readtimeout", "writereject", "lagspike", "oom"],
    },
    "infra": {
        "rule_tokens": ["nodepool", "drain", "pdbviolation", "schedstarve"],
        "rule_phrase": ("infra incidents arise when a nodepool drain triggers "
                        "a pdbviolation leading to schedstarve"),
        "services": ["infra-lb", "infra-dns", "infra-mesh", "infra-quota"],
        "symptoms": ["502", "dnsfail", "meshdrop", "quotahit"],
    },
}

# 'data' domain has a TEMPORAL CONTRADICTION: after day T its rule changes
# (a config migration). A correct synthesis must encode the RESOLVED state.
DATA_POST_RULE_TOKENS = ["shardrebalance", "backpressure", "throttle", "drainmode"]
DATA_POST_PHRASE = ("after the migration, data outages start when "
                    "shardrebalance lacks backpressure throttle in drainmode")
DATA_MIGRATION_DAY = 55


@dataclass
class Incident:
    iid: int
    day: int
    domain: str
    service: str
    is_distractor: bool
    # The memory texts an agent will write for this incident. Each carries
    # only a SUBSET of rule tokens (never the full set).
    symptom: str
    obs_text: str
    err_text: str
    result_text: str
    tail_detail: str            # rare unique detail (tail-fact probe target)
    rule_tokens_present: list[str] = field(default_factory=list)


def _rule_tokens_for(domain: str, day: int) -> tuple[list[str], str]:
    if domain == "data" and day >= DATA_MIGRATION_DAY:
        return DATA_POST_RULE_TOKENS, DATA_POST_PHRASE
    return DOMAINS[domain]["rule_tokens"], DOMAINS[domain]["rule_phrase"]


def generate_world(seed: int, days: int = 90,
                    incidents_per_day: int = 6) -> list[Incident]:
    """Deterministic incident stream. Each incident memory leaks only a
    PARTIAL subset of the latent rule tokens + surface noise. The full
    token set is never co-located in a single memory."""
    rng = random.Random(seed)
    out: list[Incident] = []
    iid = 0
    for day in range(1, days + 1):
        for _ in range(incidents_per_day):
            iid += 1
            domain = rng.choice(list(DOMAINS))
            d = DOMAINS[domain]
            service = rng.choice(d["services"])
            is_distractor = rng.random() < 0.20
            rule_tokens, _phrase = _rule_tokens_for(domain, day)

            if is_distractor:
                # Trap: surface vocab of `domain` but latent precondition
                # is a DIFFERENT domain's tokens — punishes naive
                # summarize-everything / over-generalisation.
                other = rng.choice([x for x in DOMAINS if x != domain])
                leak_pool = DOMAINS[other]["rule_tokens"]
            else:
                leak_pool = rule_tokens

            # Leak at most 2 of the (>=4) rule tokens into this incident's
            # memories — never enough alone to entail the rule.
            k = rng.randint(1, 2)
            leaked = rng.sample(leak_pool, k=min(k, len(leak_pool)))
            sym = rng.choice(d["symptoms"])
            noise = rng.choice(["amber", "delta", "kilo", "sierra", "tango",
                                "victor", "zulu", "echo", "foxtrot"])
            tail = f"port{rng.randint(20000, 65000)}-{noise}"

            obs = (f"incident {iid} day {day} {service} {sym} observed; "
                   f"context {leaked[0]} noise {noise}")
            err = (f"incident {iid} {service} error {sym} "
                   f"signal {' '.join(leaked)}")
            res = (f"incident {iid} remediated by restarting {service}; "
                   f"local fix applied; residual {leaked[-1]}")
            out.append(Incident(
                iid=iid, day=day, domain=domain, service=service,
                is_distractor=is_distractor, symptom=sym,
                obs_text=obs, err_text=err, result_text=res,
                tail_detail=tail,
                rule_tokens_present=leaked,
            ))
    return out


def canonical_rule(domain: str, *, resolved: bool = True) -> tuple[list[str], str]:
    """The frozen canonical rule a correct synthesis must entail. For
    'data' the RESOLVED (post-migration) rule is canonical."""
    if domain == "data" and resolved:
        return DATA_POST_RULE_TOKENS, DATA_POST_PHRASE
    return DOMAINS[domain]["rule_tokens"], DOMAINS[domain]["rule_phrase"]
