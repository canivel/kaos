# KAOS v0.4: your agents remember now, and they use 78% less context doing it

> **IMAGE: hero-v04.png**
> Wide 16:9 dark-themed tech illustration. Center composition: A glowing SQLite cylinder with a brain-like neural pattern overlaid, connected by luminous threads to 3-4 translucent agent bubbles orbiting it. Each bubble has a different colored glow (purple, cyan, green, orange). From the brain pattern, arrows flow downward into a funnel/compressor that outputs a smaller, brighter, concentrated dot — representing compressed context. Next to the funnel: a small "78% smaller" label in monospace font. Below: a timeline showing 3 search iterations with a knowledge line connecting them (not resetting to zero). Color palette: deep navy (#0a0a0f), purple (#6c5ce7), cyan (#18ffff), green (#00e676), orange (#f97316). No text except the label, no faces, no robots. Style: abstract, clean, developer-focused infrastructure.
![KAOS v0.4 — compaction + knowledge](hero-v04.png)

*we fixed the proposer timeout problem, made knowledge compound across searches, and built a compactor that cuts agent context by 78% with zero quality loss. here's what happened and why it matters.*

**GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos) | **Website:** [canivel.github.io/kaos](https://canivel.github.io/kaos) | **License:** Apache 2.0 | Free and open source

---

## the problem we had

so v0.2 shipped Meta-Harness and it worked. the proposer took accuracy from 0% to 100% in two iterations on our text_classify benchmark, inventing a domain-keyword classifier from scratch. no LLM calls, just pure Python. pretty cool.

but then it kept dying hahaha

every search past iteration 2 would timeout. the proposer makes 5-10 tool calls per iteration — list the archive, read 3 traces, read 2 source files, grep for patterns, submit a harness. each tool call goes through `claude --print`, which replays the ENTIRE conversation as input. by turn 6 the prompt is enormous and boom, timeout.

we tried raising the timeout from 300s to 600s. then 900s. didnt help. the problem wasnt the timeout — it was the architecture. we were feeding the proposer raw data and making it forage through the archive one tool call at a time. every tool call made the next one slower.

---

## smart context compaction

instead of letting the proposer explore the archive with tool calls, we pre-digest the entire archive and inject it into the prompt. one read instead of ten.

but "pre-digest" doesnt mean "truncate." truncation is lossy in an uncontrolled way — you drop the tail and have no idea if the tail was the most important part. we built a structured compactor with three strategies:

> **IMAGE: compaction-flow.png**
> Horizontal flow diagram on dark background (#0a0a0f). 16:9 ratio. LEFT: A tall stack of document icons labeled "Raw Archive" with sizes "30KB traces, 7KB source, 10KB per-problem" in small monospace text. An arrow flows right through a diamond-shaped "Compactor" node glowing purple (#6c5ce7). The compactor has 3 small labels branching from it: "Lossless" (green, pointing to scores/source icons), "Extract" (cyan, pointing to an error-pattern summary icon), "Filter" (orange, pointing to a filtered/smaller trace icon). RIGHT: A compact document icon labeled "Archive Digest" that's visually ~half the size of the left stack. A badge reads "78% smaller, 0% loss". Below the flow: a bar chart showing 5 levels (0,3,5,7,10) with decreasing bar heights for size and all bars at the same height for quality (100%). Style: clean, minimal, rounded boxes.
![Compaction flow — raw archive to digest](compaction-flow.png)

**lossless** — scores and source code stay exactly as-is. small data, 100% signal. the proposer needs exact numbers and full code.

**structured extraction** — raw traces and per-problem results get converted to error patterns. instead of 8 verbose trace entries you get "3/8 wrong: science→technology (2x), timeout (1x)". this is actually MORE useful than the raw data because it surfaces the patterns explicitly.

**filtered** — correct-problem traces get dropped entirely. they add noise, not signal. only errors and failures kept.

**conversation compaction** — for the CCR agent loop, tool results older than 6 turns get compressed to `[tool result: N chars]`. recent turns kept verbatim.

### the results

we didnt just test on one benchmark. we built archives for 5 different domains — each with its own harnesses, failure modes, and diagnostic questions. the questions cover 4 tiers: direct facts ("whats the best score?"), comparison ("which approach is better?"), causal reasoning ("why did it fail?"), and synthesis ("what should the proposer do next?").

### classification

text classification with keyword matching, zero-shot, and a failed API caller. questions like "why did all seeds score 0%?" and "is the keyword list visible so a proposer could extend it?"

```
Level  0 │  29% saved │ 100% quality
Level  5 │  52% saved │ 100% quality  ← default
Level 10 │  68% saved │ 100% quality
```

this domain compacts the most because keyword classifiers are self-contained — the source code IS the approach, no external dependencies to track.

### code generation

harnesses for fizzbuzz through parser combinators and graph algorithms. the winning approach gathers environment context (language, deps, test framework) before generating. questions like "what caused the async_retry failure?" and "what edge case broke dijkstra?"

```
Level  0 │  31% saved │ 100% quality
Level  5 │  31% saved │ 100% quality  ← default
Level 10 │  56% saved │  70% quality
```

code generation needs more context — the specific error messages ("TestFailed: 0/12 tests passed", "edge case with negative weights") are critical for the proposer. at max level some of those get dropped.

### research / RAG

math problem solving with domain-aware retrieval (geometry, algebra, combinatorics, number theory). BM25 scoring within domains. questions like "was the domain routing correct when retrieval missed?" and "which math domains are represented?"

```
Level  0 │  24% saved │ 100% quality
Level  5 │  28% saved │ 100% quality  ← default
Level 10 │  44% saved │  78% quality
```

RAG has the most complex per-problem metadata (domain labels, retrieval scores, routing decisions). compaction at high levels drops some of the retrieval miss analysis.

### tool calling / agentic

single-step vs plan-then-act for multi-step tool chains. questions like "why did the API chain hallucinate step 3?" and "is the decomposition strategy visible?"

```
Level  0 │  30% saved │ 100% quality
Level  5 │  30% saved │ 100% quality  ← default
Level 10 │  53% saved │ 100% quality
```

tool calling compacts well because the key signal is the approach (plan-then-act vs single-step) and the failure mode (hallucinated execution), not the verbose tool call traces.

### ML training / optimization

hyperparameter optimization with dataset-aware configs. questions like "why did the learning rate diverge?" and "is the weight_decay recommendation visible?"

```
Level  0 │  28% saved │ 100% quality
Level  5 │  28% saved │ 100% quality  ← default
Level 10 │  45% saved │ 100% quality
```

ML compacts well because the insights are in the error messages ("lr too high, diverged after epoch 5") and the config differences, not in the raw training logs.

### aggregate across all domains

```
Level  0 │  28% saved │ 100% quality
Level  5 │  34% saved │ 100% quality  ← default
Level  7 │  41% saved │  98% quality
Level 10 │  53% saved │  88% quality
```

at the default level, every domain retains 100% quality. no exceptions. the 12% quality drop at max level comes from code generation and RAG — domains where specific error messages and routing decisions matter most.

### the real savings: 78% fewer tokens

> **IMAGE: compaction-chart.png**
> Horizontal bar chart on dark background (#0a0a0f). 16:9 ratio. 5 domain rows (Classification, Code Generation, Research/RAG, Tool Calling, ML Training), each with a gradient bar (purple→cyan) showing % tokens saved and a thin green bar below showing quality retention %. Domain labels on the left. Percentages on the right of each bar: Classification 84%, Code Gen 77%, Research 76%, Tool Calling 77%, ML 76%. Bottom: aggregate box with "78% reduction, 100% quality retained" in a highlighted panel. Style: clean, minimal, dark theme.

![Token savings by domain](compaction-chart.png)

heres where it gets real. without compaction, the proposer makes ~3 archive reads per iteration (ls, read scores, read source/traces). with compaction, its 1 digest read. the reduction per domain:

```
Classification:   84% fewer tokens — 100% quality
Code Generation:  77% fewer tokens — 100% quality
Research / RAG:   76% fewer tokens — 100% quality
Tool Calling:     77% fewer tokens — 100% quality
ML Training:      76% fewer tokens — 100% quality

Aggregate:        78% fewer tokens — 100% quality at default
```

this matters a LOT right now because claude is limiting context heavily. every token you waste on verbose traces is a token you cant use for actual reasoning. with compaction, the proposer gets a dense, organized digest instead of raw JSON noise — and it uses 78% fewer tokens to get there.

at scale the absolute numbers add up too. at sonnet pricing ($3/M input), each search saves ~$0.36. running 10 searches a day during a research sprint, thats ~$108/month. but honestly the real value isnt the money — its that searches that used to timeout now complete because the context actually fits.

you can tune it in `kaos.yaml`:

```yaml
search:
  compaction_level: 5  # 0 (no compaction) to 10 (maximum)
```

level 0 if you want the proposer to see everything. level 10 if youre running on a model with a small context window and you accept some quality tradeoff in code/RAG domains.

---

## knowledge that compounds

this was the other big gap. every `mh search` started from scratch. the proposer had zero memory of prior searches. it would discover "TF-IDF + keyword matching beats zero-shot by 100%" and then that finding would die when the search completed. next search? starts over from seed harnesses, re-discovers the same thing.

i was reading [karpathy's LLM wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and it clicked — "the tedious part of maintaining a knowledge base is not the reading or the thinking — its the bookkeeping." LLMs dont get bored maintaining cross-references.

> **IMAGE: knowledge-compound.png**
> Vertical flow diagram on dark background (#0a0a0f). 16:9 ratio. 3 horizontal "search" lanes stacked vertically, connected by a vertical glowing line on the left (the knowledge thread). Lane 1 "Search 1": starts with 3 grey seed icons, arrow, proposer icon, arrow, green star icon labeled "keyword classifier 100%". Arrow goes down to the knowledge line. Lane 2 "Search 2": starts with the green star icon (loaded from knowledge line!), arrow, proposer, arrow, cyan star "TF-IDF variant, 30% faster". Arrow goes down to knowledge line. Lane 3 "Search 3": starts with BOTH green and cyan stars (loaded from knowledge), arrow, proposer, arrow, orange star "edge case specialist". On the left, the vertical knowledge line is labeled "kaos-knowledge agent" with a SQLite icon at the bottom. Style: clean timeline, thin glowing connections, dark background.
![Knowledge compounding across searches](knowledge-compound.png)

### how it works

when a search completes, KAOS files the results to a persistent "kaos-knowledge" agent:

```
/discoveries/text_classify/
    frontier.json           # pareto-optimal harnesses
    latest_search.json      # summary: best scores, iterations
    harnesses/
        keyword_class.py    # the actual winning source code
        few_shot_v2.py      # second-best approach
```

when a new search starts, KAOS loads prior discoveries as seeds instead of the default zero-shot/few-shot/retrieval seeds.

search 1: seeds are generic → proposer invents keyword classifier → 100% accuracy

search 2: seeds loaded from knowledge = keyword classifier (100%) → proposer starts from 100% and explores cost optimization

search 3: seeds = both prior winners → proposer focuses on edge cases

each search builds on the last. the bookkeeping is automatic.

```bash
kaos mh knowledge       # view whats in the knowledge base
kaos search "TF-IDF"    # full-text search across all agents
kaos index <agent-id>   # build navigable /index.md
kaos mh lint <id>       # health-check a search archive
```

---

## CLI-first architecture

btw this was the biggest architectural shift in v0.3. there was this [article about CLIs vs MCP for AI agents](https://medium.com/@unicodeveloper/10-must-have-clis-for-your-ai-agents-in-2026-51ba0d0881df) that showed CLI is 10-32x cheaper on tokens than MCP, with ~100% reliability vs MCP's 72%.

makes sense — MCP injects the entire tool schema into every context window. CLI just runs a command and gets the output.

so now every KAOS command supports `--json`:

```bash
kaos --json ls
kaos --json mh status <search-id>
kaos --json search "keyword"
kaos --json mh knowledge | jq '.benchmarks[].harnesses_stored'
```

auto-enabled when piped. an agent calling `kaos --json ls` gets clean JSON; a human calling `kaos ls` gets a Rich table.

### background worker

the MCP server used to run searches as asyncio tasks in the same event loop. if the MCP connection dropped, the search died.

now `mh_search` spawns a detached worker subprocess:

```bash
kaos mh search -b text_classify -n 10 --background
# → "Worker launched (PID 12345). Log: kaos-worker-1712345678.log"
```

survives parent exit, MCP disconnection, terminal close. logs to a file (not /dev/null — that was a fun bug to find hahaha, worker kept dying from missing numpy and we had no output to debug it).

---

## KAOS triaging itself

> **IMAGE: self-triage.png**
> Square illustration on dark background (#0a0a0f). Center: a circular Ouroboros-like shape made of code/terminal text, representing KAOS evaluating itself. Inside the circle: a small SQLite cylinder with a magnifying glass over it. Around the outside: 14 small issue/ticket icons, 6 of them with green checkmarks, 8 with grey dots. A scoreboard/leaderboard floating next to the circle shows "#15 score=6.0", "#13 score=4.5", "#12 score=4.5" with checkmarks. The overall feeling: self-referential, recursive, meta. Color palette: dark navy background, purple accents, green checkmarks. Style: minimal, abstract, no faces.

![KAOS triaging itself](self-triage.png)
we used KAOS to evaluate its own issues. spawned a `self-triage-v030` agent, ingested all 14 GitHub issues into its VFS, scored each on impact/effort/feasibility, and implemented the top 6 in priority order.

```python
afs = Kaos('kaos.db')
triage_id = afs.spawn('self-triage-v030')

# ingest all issues
for issue in github_issues:
    afs.write(triage_id, f'/issues/{issue["number"]}/issue.json',
              json.dumps(issue).encode())
    afs.set_state(triage_id, f'score.{issue["number"]}', {
        "impact": 9, "effort": 2, "feasibility": 10,
        "priority_score": 4.5,
    })

afs.checkpoint(triage_id, label='triage-complete')
```

then queried with SQL to get the ranking:

```sql
SELECT key, json_extract(value, '$.priority_score') as score
FROM state WHERE key LIKE 'score.%'
ORDER BY score DESC
```

13 issues closed across v0.3.0, v0.3.1, and v0.4.0. the framework triaged itself. for sure the most meta thing ive built.

---

## the proposer that couldnt submit

this one was fun hahaha. we got feedback from another project using KAOS: "proposer completes, responds with a perfectly good harness, submits 0 candidates." turns out `claude --print` is text-in, text-out — no tool-use protocol. the proposer needs to call `mh_submit_harness(source_code=...)` but the CLI subprocess cant do that. it just writes plain text back.

the fix: after the proposer runs, if no tool-call submissions were made, we scan the response for ```python blocks containing `def run()` and extract them as candidates. same pattern that external scripts like `evolve_claude.py` use — and it works with any provider, not just claude_code.

this is the kind of bug you dont catch in unit tests because the mock router supports tool-use just fine. it only shows up when a real user runs with a real text-only provider. the AI that reported it also suggested the fix — gotta love that.

---

## bug fixes worth mentioning

**windows unicode crash** — `sys.stdout.reconfigure(encoding="utf-8")` at CLI startup. no more `UnicodeEncodeError` on non-ASCII output.

**MCP stdout corruption** — `sys.stdout = sys.stderr` in stdio mode. any library logging to stdout no longer corrupts the JSON-RPC protocol.

**parallel spawn contention** — `spawn()` retries on WAL lock with backoff. `PRAGMA wal_autocheckpoint=100` keeps WAL small.

**evaluator bugs** — `_truncate()` was creating invalid JSON by slicing mid-string. error score keys had `+`/`-` prefixes that didnt match success keys. both caused every harness to score 0%. ouch.

**objectives override** — `SearchConfig.objectives` now defaults to `None` (inherit from benchmark) instead of hardcoding `["+accuracy", "-context_cost"]`. this was breaking every custom benchmark.

**seed harnesses never called LLM** — the seeds returned `{"prompt": ...}` with no `"prediction"` key. guaranteed 0% accuracy. now they call `llm()` (injected by the evaluator) and actually predict.

---

## whats next

the one remaining P0: **Claude Code as a full execution backend**. right now `agent_spawn` creates an isolated VFS but cant actually run an agent with real tools (Bash, web search, file read). the `ClaudeCodeProvider` does single-shot `claude --print` — useful for the proposer, but not for autonomous agents.

the vision: `agent_spawn` delegates to Claude Code as a subprocess. the spawned agent gets its own VFS, its own tool set, and its results flow back into KAOS. the entire research loop — propose, evaluate, score, checkpoint, iterate — runs inside KAOS autonomously.

thats v0.5.

---

## upgrading

```bash
git pull origin main
uv sync
kaos --version  # 0.4.0
```

existing configs and databases work unchanged. MCP server needs a restart.

---

## full changelog

**v0.4.1** (April 6, 2026)
- proposer text extraction fallback for text-only providers (#27)
- multi-domain compaction eval: classification, code gen, research, tool calling, ML

**v0.4.0** (April 6, 2026)
- cross-search memory via persistent knowledge agent
- smart context compaction (0-10), archive digest, conversation compaction
- full-text search across VFS contents
- VFS auto-index, lint, persistent skills

**v0.3.1** (April 5, 2026)
- bug fixes: Unicode crash, WAL contention, output truncation, stdout corruption
- new: `kaos read`, `kaos logs`, `mh search --dry-run`

**v0.3.0** (April 4, 2026)
- CLI-first architecture with `--json` output
- background worker subprocess for `mh search`
- `provider: claude_code` (no API key needed)
- pluggable `llm()` callable for harnesses
- fail-fast retries, proposer timeout handling

**GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos) — 157 tests, Apache 2.0, zero AI SDK dependencies.
