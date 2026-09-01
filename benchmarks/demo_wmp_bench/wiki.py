"""WMP bench-local implementation — wiki maintainer + proposer injection.

Nothing here enters kaos/ unless the probe ACCEPTs. The proposer subclass is
swapped in via the module attribute ``kaos.metaharness.search.ProposerAgent``
by run.py, per arm:

  B0    — stock ProposerAgent behavior (subclass only counts prompt chars)
  FULL  — one maintainer LLM call per iteration performs root-cause analysis
          over the same archive digest the proposer reads, maintaining a
          <=2,000-char failure-pattern wiki appended to the proposer prompt
  L1    — identical, but the wiki is word-scrambled before injection
          (same tokens, destroyed instruction — the padding placebo)

Char accounting (G3): per iteration, the final proposer prompt length plus
(for FULL/L1) the maintainer prompt + response lengths.
"""

from __future__ import annotations

import logging

from kaos.bench.replay import scramble_payload
from kaos.metaharness.proposer import ProposerAgent

logger = logging.getLogger(__name__)

WIKI_CAP_CHARS = 2000
DIGEST_CAP_CHARS = 6000

MAINTAINER_SYSTEM = (
    "You are a Wiki Maintainer for an automated harness search. You perform "
    "root-cause analysis over candidate harnesses and their scores."
)

MAINTAINER_PROMPT = """\
Below is (1) the current failure-pattern wiki and (2) a digest of all harness
candidates evaluated so far in this search, with scores and per-problem
outcomes.

Update the wiki: root-cause WHY the losing harnesses lose and WHAT the winning
ones do that works. Write durable, mechanism-level patterns (not scores), each
as one bullet: `- PATTERN: ... BECAUSE: ... THEREFORE: ...`. Merge or drop
stale bullets. Maximum {cap} characters. Output ONLY the updated wiki text.

## Current wiki
{wiki}

## Archive digest
{digest}
"""


class WMPContext:
    """Per-search mutable state shared with the proposer subclass."""

    def __init__(self, arm: str):
        assert arm in ("B0", "FULL", "L1")
        self.arm = arm
        self.wiki_text = ""
        self.iter_chars: list[int] = []      # per-iteration context chars (G3)
        self._pending_maintainer_chars = 0

    def to_dict(self) -> dict:
        return {"arm": self.arm, "iter_chars": self.iter_chars,
                "final_wiki": self.wiki_text}


# run.py sets this before each search; searches run strictly sequentially.
CTX: WMPContext | None = None


class WMPProposer(ProposerAgent):
    """Stock proposer + (per arm) wiki maintenance and injection."""

    async def propose(self, **kw):  # type: ignore[override]
        global CTX
        assert CTX is not None
        CTX._pending_maintainer_chars = 0
        if CTX.arm in ("FULL", "L1"):
            try:
                await self._maintain_wiki(kw.get("compaction_level", 5),
                                          kw.get("iteration", 0))
            except Exception as e:  # noqa: BLE001 — maintenance failure is data
                logger.warning("wiki maintainer failed (wiki unchanged): %s", e)
        return await super().propose(**kw)

    async def _maintain_wiki(self, compaction_level: int, iteration: int) -> None:
        assert CTX is not None
        digest = self._build_archive_digest(compaction_level)[:DIGEST_CAP_CHARS]
        prompt = MAINTAINER_PROMPT.format(
            cap=WIKI_CAP_CHARS,
            wiki=CTX.wiki_text or "(empty — first iteration)",
            digest=digest or "(no candidates evaluated yet)")
        agent_id = self.afs.spawn(f"wmp-maintainer-iter-{iteration}")
        try:
            resp = await self.router.route(
                agent_id=agent_id,
                messages=[{"role": "system", "content": MAINTAINER_SYSTEM},
                          {"role": "user", "content": prompt}],
                tools=[], config={})
            CTX.wiki_text = (resp.content or "")[:WIKI_CAP_CHARS]
            CTX._pending_maintainer_chars = len(prompt) + len(resp.content or "")
            self.afs.complete(agent_id)
        except Exception:
            self.afs.fail(agent_id, error="maintainer route failed")
            raise

    def _assemble_prompt(self, **kw) -> str:  # type: ignore[override]
        global CTX
        assert CTX is not None
        prompt = super()._assemble_prompt(**kw)
        if CTX.arm in ("FULL", "L1") and CTX.wiki_text:
            wiki = (CTX.wiki_text if CTX.arm == "FULL"
                    else scramble_payload(CTX.wiki_text))
            prompt += (
                "\n\n## Failure-pattern wiki\n"
                "Maintained root-cause patterns from this search's history. "
                "Advisory context for your proposals:\n" + wiki)
        CTX.iter_chars.append(len(prompt) + CTX._pending_maintainer_chars)
        CTX._pending_maintainer_chars = 0
        return prompt
