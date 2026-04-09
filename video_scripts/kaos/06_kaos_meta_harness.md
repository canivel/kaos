# Tutorial 06 — Meta-Harness Search: Autonomous Harness Optimization
**Duration:** 5 minutes  
**Level:** Advanced  
**Goal:** Run a meta-harness search that autonomously improves LLM wrapping code across iterations, reads the Pareto frontier, and builds a knowledge base for future runs.

---

## SCENE 1 — Hook [0:00–0:25]

**[VISUAL: Graph — iteration 0 at 62% accuracy. Each iteration bumps the curve. By iteration 10: 89%. No human intervention.]**

> "What if your LLM pipeline could improve itself? You give KAOS a benchmark and a seed harness. It runs an agent that reads the results, writes improved code, evaluates it, and repeats — autonomously, across as many iterations as you specify. This is Meta-Harness search. Here's how it works."

---

## SCENE 2 — What Is a Harness [0:25–1:05]

**[VISUAL: Simple harness source code with `def run(problem)` highlighted]**

> "A harness is a Python program that wraps an LLM to solve a specific task. It defines one function: `run(problem)` — takes a problem dict, calls an LLM, returns a result dict."

```python
# seed harness — the starting point
def run(problem: dict) -> dict:
    prompt = f"Classify this text as positive or negative:\n\n{problem['text']}"
    
    response = llm(prompt, max_tokens=10)  # llm() is injected by KAOS
    
    prediction = "positive" if "positive" in response.lower() else "negative"
    
    return {
        "prediction":     prediction,
        "context_tokens": len(prompt.split()),
    }
```

> "The `llm()` function is injected automatically — it routes through your configured KAOS provider. The harness just focuses on the prompt strategy."

---

## SCENE 3 — Starting a Search [1:05–2:00]

**[VISUAL: CLI command and Python API side by side]**

> "Launch a search from the CLI — specify the benchmark, number of iterations, and optionally a background flag so it runs detached."

```bash
# Text classification, 10 iterations, run in background
kaos mh search \
  --benchmark text_classify \
  --iterations 10 \
  --background
```

**[VISUAL: Terminal shows "Search started: agent ID 01JQMHS..."]**

> "Or from Python, with full config control:"

```python
from kaos import Kaos
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.search import MetaHarnessSearch
from kaos.router import GEPARouter

db     = Kaos("project.db")
router = GEPARouter.from_config("kaos.yaml")

config = SearchConfig(
    benchmark              = "text_classify",
    max_iterations         = 10,
    candidates_per_iteration = 2,    # propose 2 harnesses per iteration
    compaction_level       = 5,      # 57% context savings on archive digest
    stagnation_threshold   = 3,      # pivot prompt after 3 non-improving iters
    consolidation_interval = 5,      # skills heartbeat every 5 iters
)

search = MetaHarnessSearch(db, router, benchmark, config)
result = asyncio.run(search.run())
print(result.summary())
```

---

## SCENE 4 — What Happens Each Iteration [2:00–3:00]

**[VISUAL: Flowchart of one iteration — archive read → proposer → validate → evaluate → frontier update]**

> "Each iteration has four steps. First, the proposer agent reads the search archive — all prior harness source code, their evaluation scores, and their execution traces. Then it proposes new harness candidates, each targeting a specific failure mode it identified in the traces. KAOS validates the harness interface — AST check plus smoke test. Then evaluates it against the benchmark. Finally updates the Pareto frontier."

**[VISUAL: Show the archive structure]**
```
/harnesses/<id>/
    source.py        ← the code
    scores.json      ← accuracy, cost metrics  
    trace.jsonl      ← what the LLM actually did per problem
    per_problem.jsonl ← pass/fail + output per problem
/pareto/
    frontier.json    ← current best set of harnesses
/attempts/           ← compact summaries for fast proposer scanning
/skills/             ← reusable patterns the proposer discovered
/notes/              ← proposer's working notes per iteration
```

> "The proposer reads the traces — not just the scores. Traces show exactly which problems each harness got wrong and why. That's what enables targeted improvement."

---

## SCENE 5 — Monitoring Progress [3:00–3:40]

**[VISUAL: `kaos mh status` and dashboard Meta-Harness panel]**

> "Poll search progress from the CLI:"

```bash
kaos mh status <search-agent-id>
```

**[VISUAL: Status output]**
```
Search: 01JQMHS...
Benchmark:  text_classify
Iteration:  7 / 10
Harnesses:  14 evaluated
Frontier:   3 Pareto-optimal points
  Best accuracy:  0.89  (harness 01JQXYZ...)
  Best cost:      0.12  (harness 01JQABC...)
  Stagnant:       0 iterations
```

> "Or watch it live in the dashboard — there's a dedicated Meta-Harness panel with current iteration, frontier size, and best scores auto-refreshing every 5 seconds."

```bash
kaos dashboard
```

---

## SCENE 6 — The Knowledge Base [3:40–4:30]

**[VISUAL: `kaos mh knowledge` output]**

> "When a search completes, KAOS files the winning harnesses and discovered skills into a persistent knowledge agent. Future searches on the same benchmark start from those discoveries instead of from scratch."

```bash
kaos mh knowledge
```

**[VISUAL: Knowledge base listing — benchmarks, harness count, best scores]**

```python
# Resume an interrupted search
kaos mh resume <search-agent-id>

# Or, start a new search — it auto-loads prior discoveries as seeds
kaos mh search --benchmark text_classify --iterations 10
# → Loaded 3 prior discoveries for text_classify from knowledge base
# → Loaded 5 skills from knowledge agent for text_classify
```

> "The knowledge base compounds across searches. Each run seeds the next. Skills — reusable prompt patterns the proposer discovered — transfer automatically."

---

## SCENE 7 — Summary [4:30–5:00]

**[VISUAL: Meta-harness loop diagram — iteration → proposer → evaluate → frontier → knowledge]**

> "Meta-harness search is autonomous harness optimization. You provide a benchmark and a seed — KAOS does the rest. The proposer reads traces, not just scores, to target specific failures. The Pareto frontier tracks accuracy versus cost simultaneously. Discoveries persist to a knowledge base. Skills compound across runs.

Next tutorial: CORAL co-evolution — running multiple meta-harness searches in parallel that share skills and compete to find better harnesses faster."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Ambitious, forward-looking. This is the most powerful KAOS feature — project that.
- **Scene 1 graph:** The accuracy curve should animate iteration by iteration with a satisfying upward trend. Each bump should have a small label like "chain-of-thought added" or "few-shot examples."
- **Flowchart (Scene 4):** Each step should highlight in sequence as narrated — don't show the full diagram all at once.
- **Archive structure (Scene 4):** Use a file tree animation — directories expand to show files, `trace.jsonl` pulses to emphasize it's the most important.
