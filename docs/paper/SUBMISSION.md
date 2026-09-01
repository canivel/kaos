# Submission guide

Categories: cs.AI (primary); cross-list cs.MA, cs.SE.
Keywords: agent harness, plasticity, usage statistics, falsifiable evaluation, pre-registration, SQLite, local-first.

Pre-submission checklist (MUST):
1. Replace remaining `Anonymous` authors in references.bib (metaharness2026, coral2026, evoskills2026, sweskills2026, multirun2026, eprocess2025, lifeharness2026, yu2026memo, ctimrover2025) with real author lists from their arXiv pages; verify zhou2026externalization title/authors.
2. Compile: latexmk -pdf kaos_neuroplasticity.tex (needs natbib; no arxiv.sty dependency).
3. Rerun alpha sweep through SkillStore.search production path (or keep footnote as-is with the disclosed caveat).
4. Optional strengtheners before v2: larger-n retrieval bench under cluster-bootstrap protocol; UCB/bandits related-work paragraph.
Companion materials: repo at github.com/canivel/kaos (code+benches+locks), paper/PROVENANCE.md, paper/PANEL_LEDGER.md.

## Zenodo (published 2026-07-24)
- Version DOI: 10.5281/zenodo.21533588 (this build)
- Concept DOI (cite-all-versions): 10.5281/zenodo.21533587
- Record: https://zenodo.org/records/21533588 (Preprint, CC-BY-4.0)
- arXiv follow-up: after acceptance, add the arXiv ID to the Zenodo record as related identifier "Is identical to".
