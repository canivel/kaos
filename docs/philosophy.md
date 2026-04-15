# KAOS Design Philosophy

## Not Invented Here. Curated From the Best.

KAOS is built on a simple conviction: **the best solutions to the hard problems in agentic AI already exist — they just need to work together.**

The research community has spent years solving isolation, coordination, memory, context compression, failure diagnosis, and automated optimization. Papers have been published. Code has been open-sourced. The work is done. The missing piece is a framework that takes each of these solutions seriously, implements them faithfully, and makes them compose cleanly.

That is what KAOS is.

---

## The Integration Criteria

We don't add a capability because it's interesting. We add it because it solves a specific, demonstrated problem that production agentic systems actually face, and because an existing solution does that better than we could invent from scratch.

Before integrating anything, we ask:

1. **Is this a real problem?** Does it occur in production, not just in toy examples?
2. **Has it been solved?** Is there a paper, an open-source project, or empirical evidence that a specific approach works?
3. **Does it compose?** Does it make the rest of the framework better, not just add a new feature?
4. **Can we credit it properly?** Is the source clear? Can we implement it faithfully without misrepresenting the original work?

If all four answers are yes, we build it. If not, we wait.

---

## Current Integrations

| Capability | Source | What It Solves |
|---|---|---|
| Cross-agent FTS5 memory | [claude-mem](https://github.com/thedotmack/claude-mem) by Alex Newman | Agents repeating past mistakes across sessions |
| Cross-agent skill library | [Zhou et al. 2026, arXiv:2604.08224](https://arxiv.org/abs/2604.08224) | Agents reinventing reliable solutions every run |
| Shared log / coordination | [LogAct arXiv:2604.07988](https://arxiv.org/abs/2604.07988), Balakrishnan et al. 2026 | Agents acting without consensus on risky operations |
| AAAK context compaction | [MemPalace](https://github.com/milla-jovovich/mempalace) | Context bloat eating accuracy and budget |
| Stagnation + co-evolution | [CORAL arXiv:2604.01658](https://arxiv.org/abs/2604.01658) | Agent improvement plateaus and wasted iterations |
| Failure diagnosis | [EvoSkills arXiv:2604.01687](https://arxiv.org/abs/2604.01687) | Opaque failures giving proposers nothing to fix |
| Automated optimization | [Meta-Harness arXiv:2603.28052](https://arxiv.org/abs/2603.28052) | Manual prompt engineering that doesn't compound |

The core VFS engine, checkpoint/restore, and audit trail are original KAOS work — they're the substrate that makes all the above composable.

---

## A Framework That Improves Itself

KAOS uses its own tools to get better.

- **Meta-harness** runs on KAOS's own benchmarks to find better strategies.
- **MemoryStore** accumulates what works — across sessions, across runs, across projects.
- **SharedLog** coordinates risky changes: nothing lands without consensus and an audit trail.

The cycle: discover good research → implement it faithfully → run it on KAOS itself → compound the results → discover more. Each version of KAOS is more capable than the last, not because we work harder, but because the framework applies its own capabilities to itself.

---

## What We Don't Do

- **We don't reinvent what already exists.** If there's a proven solution, we use it.
- **We don't add features for their own sake.** Every capability has a source and a reason.
- **We don't hide the origins.** Every integration credits its source explicitly — in code comments, in docs, in the website. If you use KAOS's memory system, you're using ideas from claude-mem. If you use the shared log, you're running the LogAct protocol. We want you to know that, read the papers, and understand what you're running.
- **We don't add things we can't maintain.** An integration that breaks the composability of the system isn't worth adding.

---

## What's Next

We're actively looking for research that addresses problems we haven't solved yet:

- **Better rollback strategies** — more granular than full-agent VFS restore
- **Cross-agent trust models** — finer-grained than binary approve/reject voting
- **Adaptive context budgeting** — dynamic compaction based on task criticality
- **Agent lifecycle management** — spawn/retire/clone policies backed by research

If you know of a paper or project that fits, open an issue or a PR. The criteria above apply. Credit will be given.

---

## Contributing

KAOS is open source, MIT licensed. The best contributions are:

1. **Research integrations** — a paper you've read and want to implement
2. **Bug reports with reproduction cases** — especially from production use
3. **Benchmark results** — showing a capability working (or not working) on a real task

See the [GitHub issues](https://github.com/canivel/kaos/issues) and the [AI agent issue policy](https://github.com/canivel/kaos/blob/main/CLAUDE.md#ai-agent-feedback-policy) if you're an agent reporting feedback.
