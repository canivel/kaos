# Panel Ledger — review record for kaos_neuroplasticity.tex

Three-level, 9-reviewer panel (KAOS workflow wf_1d299d04-699, 2026-07-18).
All reviewers returned MAJOR on draft 1: 8 blockers, 31 majors, ~30 minors.
Full verdicts: workflow journal (session artifacts); digest below.

| Level | Reviewer | Verdict | Key findings -> disposition |
|---|---|---|---|
| L1 | ground:P1-P8 | MAJOR | alpha-sweep footnote cause wrong -> FIXED (code-path truth); default 25 vs 100 -> FIXED; net-flip wording -> FIXED; overhead stats language -> FIXED; alpha dip -> FIXED; pragma pair -> FIXED; P15 FTS count -> FIXED; artifact sign bug -> FIXED in bench |
| L1 | ground:P9-P16 | MAJOR | BLOCKER Feb/June date hallucination -> FIXED; P9/P10 commit swap -> FIXED; P12 untracked file -> committed now; P14 commits extended -> FIXED; abstract scoping -> FIXED |
| L1 | ground:citations | MAJOR | Anonymous bib entries + title mismatches -> PARTIAL: CTIM-Rover added; author verification against arXiv REQUIRED pre-submission (SUBMISSION.md checklist) |
| L2 | rigor:stats | MAJOR | BLOCKER footnote; "statistically indistinguishable" -> FIXED (point estimate framing) |
| L2 | rigor:repro | MAJOR | Eq.1 didn't match code -> FIXED (max(bm25,eps)*(c+alphaW)*decay, query-time reranking); threshold -> FIXED; abstract batch-vs-query -> FIXED |
| L2 | rigor:claims | MAJOR | author block -> FIXED (sole author + AI-use disclosure section); temporal scoping of discipline claim -> FIXED; PANEL_LEDGER must exist -> this file |
| L3 | adv:systems | MAJOR | BLOCKER ranker never probed -> DISCLOSED as asymmetry + queued probe; vise overclaim -> WEAKENED to tested-variants + conjecture; novelty vs generative-agents scoring -> addressed via implementation-faithful Eq.1 + Wilson distinction |
| L3 | adv:empirical | MAJOR | ledger/panel files must be committed -> DONE; retroactive-check wording kept (margins verified); small-n replication -> stated as first queued work |
| L3 | adv:related | MAJOR | BLOCKER Anonymous entries -> checklist; author-block policy -> FIXED; bandit-literature (UCB) citation -> DEFERRED (noted for camera-ready; Wilson-vs-UCB discussion queued) |

Deferred (tracked, not blocking draft-2): UCB/bandit related-work paragraph; larger-n bench rerun; alpha-sweep rerun through production path; e-process stopping.
Human author is the final gate on all dispositions.
