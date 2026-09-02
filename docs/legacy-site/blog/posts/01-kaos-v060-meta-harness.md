# From 48% to 83%: How KAOS v0.6.0 Automates Multi-Agent AI Research

*Code Quality · April 10, 2026 · 10 min read*

*A live demo of Meta-Harness finding the winning prompt strategy — automatically, in 15 iterations, for $0.14*

---

You've spent three days hand-crafting the perfect prompt for your classifier. You tried chain-of-thought. Then few-shot examples. Then a "senior engineer" persona. You're at 74% accuracy and stuck. You run another variant. Still 74%. Another. 74%.

This is the plateau problem — and it's invisible until you're already trapped in it.

KAOS v0.6.0 solves it. Here's how.

---

## What Is KAOS?

[KAOS](https://github.com/canivel/kaos) is an open-source, local-first multi-agent orchestration framework. Every agent gets an isolated virtual filesystem backed by a single SQLite file. Full audit trail. Checkpoint and restore. Zero cloud dependency.

The headline feature is **Meta-Harness**: an automated search loop that finds the best prompt strategy for any LLM task by treating prompt engineering as an optimization problem. Define your task. Give it some data. Run `kaos mh search`. Come back to a ranked Pareto frontier of harnesses.

v0.6.0 adds **CORAL** — three tiers of co-evolutionary improvements that make the search dramatically smarter, especially when it gets stuck.

---

## The Research Foundation

Before diving into the demo, it's worth noting what's under the hood. KAOS v0.6.0 integrates four peer-reviewed research contributions:

- **[Meta-Harness](https://arxiv.org/abs/2603.28052)** (arXiv:2603.28052, Stanford/MIT/KRAFTON) — the search loop itself: evolutionary proposer reads full execution traces and proposes structurally better harnesses
- **[MemPalace](https://github.com/milla-jovovich/mempalace)** — AAAK compact notation that compresses the proposer's context by 57% with zero quality loss
- **[CORAL](https://arxiv.org/abs/2604.01658)** (arXiv:2604.01658) — stagnation detection, heartbeat reflection, and multi-agent co-evolution achieving 3–10× higher improvement rates
- **[EvoSkills](https://arxiv.org/abs/2604.01687)** (arXiv:2604.01687) — Surrogate Verifier: informationally isolated failure diagnostics

This isn't a thin wrapper around a model API. It's a ground-up implementation of the most effective multi-agent search techniques from 2025–2026, running entirely locally.

---

## The Demo: Code Review Severity Classification

**Task:** Classify a GitHub PR review comment into one of four severity levels:
- `BLOCKER` — must fix before merge (security bug, data corruption, broken logic)
- `IMPORTANT` — should fix soon (performance issue, bad pattern)
- `STYLE` — nice to have (naming, formatting)
- `PRAISE` — positive feedback

**Dataset:** 200 labeled PR review comments. Baseline zero-shot accuracy: **48%**.

![Full Meta-Harness demo — code review 48%→83%](https://canivel.github.io/kaos/docs/demos/kaos_mh_full_demo.gif)

---

## Step 1: Define the Benchmark

```python
# benchmarks/code_review.py
LABELS = ["BLOCKER", "IMPORTANT", "STYLE", "PRAISE"]

EXAMPLES = [
    {"comment": "SQL query is vulnerable to injection — must fix before merge",
     "label": "BLOCKER"},
    {"comment": "This N+1 query will cause issues at scale",
     "label": "IMPORTANT"},
    {"comment": "Variable name `x` is not descriptive",
     "label": "STYLE"},
    {"comment": "Nice use of early returns here, much cleaner!",
     "label": "PRAISE"},
    # ... 196 more examples
]

def evaluate(harness_fn, examples=EXAMPLES):
    predictions = [harness_fn(e["comment"]) for e in examples]
    correct = sum(p == e["label"] for p, e in zip(predictions, examples))
    return {"accuracy": correct / len(examples), "n_correct": correct}
```

That's the full benchmark contract. KAOS needs a callable that takes input and returns a score dict.

---

## Step 2: Initialize and Launch

```bash
kaos init
# ✓  Initialized kaos.db
# ✓  Schema v4 applied
# ✓  Knowledge agent spawned [kaos-knowledge]

kaos mh search -b code_review -n 15 -k 3 --background
# ✓  Benchmark loaded: code_review  (200 examples, 4 labels)
# ✓  Search agent spawned [01JMHSRCH-code-review]
# ✓  Worker process started  PID 14832
```

**kaos.yaml** configures the CORAL parameters:

```yaml
provider: claude_code        # uses your CC subscription, zero API cost
model:    claude-sonnet-4-6
compaction_level: 5          # 57% context savings, 100% quality
stagnation_threshold: 4      # CORAL pivot after 4 non-improving iters
consolidation_every: 6       # CORAL skills heartbeat
```

---

## Step 3: Seed Evaluation

```
[seed 1/3]  zero_shot         acc=0.48  cost=12.4   96/200 ✓
[seed 2/3]  few_shot_2        acc=0.54  cost=18.7  108/200 ✓
[seed 3/3]  cot_basic         acc=0.61  cost=24.1  122/200 ✓

Seed evaluation complete.  Initial frontier: 3 points
Best seed: cot_basic (acc=0.61)  —  Search begins from here
```

The basic chain-of-thought approach already beats zero-shot by 13 points. The proposer now has three execution traces to learn from.

---

## Step 4: The Search Loop

```
[iter 1/15]  role_engineer        acc=0.67  +0.06 ↑  IMPROVED
[iter 2/15]  role_engineer_v2     acc=0.71  +0.04 ↑  IMPROVED
[iter 3/15]  rubric_detailed      acc=0.69  ─  regression vs best
[iter 4/15]  few_shot_balanced    acc=0.74  +0.03 ↑  IMPROVED
[iter 5/15]  few_shot_4x          acc=0.73  ─  marginally worse
[iter 6/15]  chain_contrast       acc=0.74  ─  matches best, no improvement
[iter 7/15]  few_shot_role_merge  acc=0.74  ─  stagnant_iters=4
```

Four iterations at 74%. This is the plateau.

---

## Step 5: CORAL Pivot

When `stagnant_iters` reaches the threshold (4), KAOS injects a `PIVOT REQUIRED` block into the next digest:

```
╔══════════════════════════════════════════════════════════════════╗
║  PIVOT REQUIRED  —  stagnant=4  best=0.74                        ║
║                                                                  ║
║  Exhausted approaches:                                           ║
║    • Role-playing (engineer/reviewer) — ceiling at 0.74          ║
║    • Few-shot examples — 1-4 per class, diminishing returns       ║
║    • CoT with contrast — matched best but did not improve         ║
║                                                                  ║
║  Required: propose an orthogonal direction.  Ideas:              ║
║    • Two-step classification (blocker? → if not, style or praise?)║
║    • Structured attribute extraction before classifying           ║
║    • Confidence calibration + abstain on ambiguous cases          ║
╚══════════════════════════════════════════════════════════════════╝
```

The proposer cannot submit another role-playing variant. It must change the fundamental approach.

---

## Step 6: The Breakthrough

```
[iter 8/15]  two_step_chain        acc=0.78  +0.04 ↑  IMPROVED  (pivot worked)
[iter 9/15]  attr_extract          acc=0.79  +0.01 ↑  IMPROVED
[iter 10/15]  two_step_attr_merged  acc=0.83  +0.04 ↑  IMPROVED  ← New best
```

At iteration 10, the CORAL consolidation heartbeat fires:

```
⟳ CORAL Consolidation heartbeat  (every 6 iters)
  Distilling reusable skills from 10 iterations...
  Skill written: two_step_decomposition
  Skill written: attr_grounding
```

The merged harness — combining two-step decomposition with attribute extraction — hits **83%**. That's a 35-point improvement from the 48% baseline.

---

## The Winning Harness

```python
SYSTEM_PROMPT = '''You are a senior software engineer reviewing a PR.
Classify the review comment using a two-step process:

STEP 1 — Extract attributes:
  impact:       high | medium | low
  scope:        blocks-merge | should-fix | nice-to-have | positive
  correctness:  yes (bug/security/logic error) | no

STEP 2 — Apply classification rules:
  If correctness=yes AND impact=high  →  BLOCKER
  If correctness=yes AND impact<high  →  IMPORTANT
  If scope=nice-to-have               →  STYLE
  If scope=positive                   →  PRAISE
  Default ambiguous to IMPORTANT.'''

def harness(comment: str) -> str:
    response = llm(SYSTEM_PROMPT, comment)
    return extract_label(response, valid=LABELS)
```

No embeddings. No retrieval. No fine-tuning. Just a structurally better prompt — the kind of thing an expert prompt engineer might eventually land on after days of iteration. Meta-Harness found it in 15 automated steps.

---

## The Full Picture

```
Baseline (zero-shot)   48% accuracy
After Meta-Harness     83% accuracy (+35 points)
Iterations used        15
Search time            ~12 minutes
API cost               ~$0.14
Key insight            two-step decomposition breaks BLOCKER/IMPORTANT confusion
Skills saved           2 reusable patterns → next search starts from here
```

The audit trail is fully queryable:

```sql
SELECT iteration, harness_id, scores->>'accuracy' as acc, status
FROM mh_attempts
WHERE benchmark='code_review'
ORDER BY iteration;
```

---

## What's New in v0.6.0: CORAL Three Tiers

### Tier 1 — Stagnation Detection + Pivot Prompts

The search now tracks `stagnant_iterations`. When it crosses `stagnation_threshold`, the proposer receives a `PIVOT REQUIRED` block that lists exhausted approaches and demands structural novelty.

### Tier 2 — Three-Tier Memory (attempts / notes / skills)

- **`/attempts/`** — compact `{id, scores, status}` summaries of every eval
- **`/notes/`** — optional iteration observations
- **`/skills/`** — reusable patterns persisted to the knowledge agent across searches

### Tier 3 — Concurrent Multi-Agent Co-Evolution

```python
# Launch 3 agents exploring the same benchmark from different angles
result = mh_spawn_coevolution(benchmark="code_review", n_agents=3)

# Each agent runs independently, auto-syncing every 2 iterations
mh_hub_sync(agent_0_id)
```

Results from the paper: **3-10× higher improvement rates** vs single-agent search. 36% of successful attempts build directly on another agent's discoveries.

---

## Getting Started

```bash
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync
uv run kaos init
uv run kaos mh search -b text_classify -n 10
```

For the collaborative mode (Claude Code drives the search directly from your IDE via MCP):

```json
{
  "mcpServers": {
    "kaos": {
      "command": "uv",
      "args": ["run", "kaos", "mcp"],
      "cwd": "/path/to/kaos"
    }
  }
}
```

Then from Claude Code: *"Use the kaos MCP tools to run a meta-harness search on my sentiment benchmark and propose 5 iterations."*

No API key. No extra cost. Your CC subscription is the inference engine.

---

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*Research credits: [Meta-Harness](https://arxiv.org/abs/2603.28052) · [MemPalace](https://github.com/milla-jovovich/mempalace) · [CORAL](https://arxiv.org/abs/2604.01658) · [EvoSkills](https://arxiv.org/abs/2604.01687) · [Karpathy's autoresearch](https://github.com/karpathy/autoresearch)*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
