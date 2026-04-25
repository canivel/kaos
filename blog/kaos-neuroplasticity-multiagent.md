# Neuroplasticity in a Multi-Agent System — The Bigger Picture

*What "the library learns from itself" really means when you have N agents writing into one SQLite file, no wake/sleep cycle, and a pile of skills and memories that were supposed to help but kept going stale.*

---

A multi-agent framework accumulates history fast. Every outcome, every retrieved memory, every failed tool call, every approval — all of it lands in the database within milliseconds of happening. The open question for the last two years was never *how do we store more of it.* It was **what should the framework do with it.**

This post is about the bigger picture: not the v0.8.1 release notes, not the v0.8.2 patch story, but what neuroplasticity actually means when you take the concept seriously inside a multi-agent system.

![KAOS architecture — seven layers](https://canivel.github.io/kaos/architecture.svg)
*KAOS — seven layers. Layer 4, **Neuroplasticity**, is what this post is about.*

---

## 1. Why a multi-agent system needs plasticity at all

If you run **one** agent, feedback loops are easy. The agent sees its own outcomes, reads its own memory, runs its own retries. Any adaptive behaviour you want — *"stop retrying this failing tool"*, *"prefer the skill that worked last time"*, *"don't re-derive this fact"* — is a local decision inside that one agent's loop.

If you run **fifty** agents against the same project, none of that is local anymore.

- Agent A hits a failure and finds a fix.
- Agent B hits the identical failure ten seconds later, pays the same LLM cost to rediscover the same fix, and stores a near-duplicate skill into the same table.
- Agent C runs a retrieval and the two near-duplicate skills both surface, each with its own half-learned reliability history.
- A month later an operator opens the library and sees six skills that solve the same problem, all with partial-credit success rates, none of them clearly preferred.

This is the shape of the problem a multi-agent framework has to solve and a single-agent one doesn't. **The data that needs to learn is the union across the population, not any individual agent's own trail.** There is no privileged process that wakes up with the big picture. The big picture has to be something the database itself can derive, on its own, as a side effect of agents doing their normal work.

That's the gap neuroplasticity closes. Not metaphorically — structurally. The library itself becomes the thing that learns.

---

## 2. The biological analogy, treated honestly

Two ideas from neuroscience keep showing up in the design. Both are useful as architectural metaphors. **Neither is a biological claim.**

**Hebb's rule (1949):** "neurons that fire together wire together." When two cells participate in the same pattern of activation repeatedly, the synapse between them strengthens. This is an inline, synaptic-timescale phenomenon — it happens as a side effect of firing, not during a scheduled training epoch.

**Sleep consolidation (Tononi & Cirelli 2014, and others):** the brain has a nightly cycle where redundant synapses are pruned and episodic memories get re-encoded as more compact, more general structures. Different timescale, different machinery, different purpose. Structural rather than synaptic.

> **To be absolutely clear:** what KAOS ships is an architectural analogy borrowed from these concepts, not a neurobiological claim. Real neurons are not Wilson-lower-bound estimators. The algorithms we use (Wilson bound, exponential recency decay, Jaccard similarity, sliding-window co-occurrence counters) are standard primitives from information retrieval and statistical learning, and they stand on their own merit. The biology gave us the *shape* of the solution, not the *math* of it.

The useful takeaway from the analogy is the **two-timescale split.** Anything on the inline path must be cheap enough to fire on every event without blowing up the agent's hot path. Anything structural can be expensive and batched. Conflating the two — trying to rebuild a full co-occurrence graph on every tool call — was the first architectural mistake we made, and the benchmark told us about it immediately.

![Two-timescale split](https://canivel.github.io/kaos/blog/charts-multiagent/04-two-timescale.png)
*Six orders of magnitude separate the synaptic hot path from the batched sleep phase. Mixing the two breaks the system; respecting the split makes it cheap.*

---

## 3. Translating it into a multi-agent framework

Here's how the biological shape maps into the KAOS world. Read the two columns as a glossary.

| In the brain | In KAOS |
|---|---|
| **Firing together → wiring together.** Co-activation strengthens the synapse. | **Used-together → edge weight.** Skills and memories retrieved in the same agent session get an `associations` edge, reinforced on each recurrence. |
| **Unused synapses atrophy.** What isn't fired stops being maintained. | **Low success-rate skills decay.** The Wilson lower bound penalises small-sample failures; consolidation soft-deprecates skills whose measured success drops below a floor. |
| **Sleep consolidates.** Episodic traces become abstract, general memory. | **Consolidation runs at agent completion.** Not nightly — there is no night. Once a threshold of completed sessions accrues, the phase rebuilds the edge graph and fires promotion / prune / merge proposals. |
| **Dopamine marks reward.** Positive outcomes bias future selection. | **Outcome success biases retrieval.** Weighted ranking composes BM25 with Wilson-lower-bound success and exponential recency decay. |

Two translation choices deserve calling out, because they're what "multi-agent" changes from the single-agent case.

**There is no sleep cycle.** A real brain alternates wake and sleep. A multi-agent framework has neither a global clock nor a quiet period. Consolidation runs *at agent completion*, opportunistically — and we cap cost by firing the full structural pass only every `KAOS_DREAM_THRESHOLD` completions rather than every single one. "Sleep" in this setting means *"a phase that runs fast enough that batching it into the tail of a completed session is cheap."*

**Writes have to be safe under N concurrent agents.** A single-agent learner can afford a heavy upsert on every outcome. N concurrent agents cannot — the fsync cost compounds and the lock contention blows up. All inline hooks in KAOS write in the *caller's* existing transaction (zero extra fsync) and defer heavy graph work to the batched pass. This was not an abstract constraint: the v0.8.1 pre-release benchmark showed **+210 ms p50 overhead** on a per-event upsert design. We threw that design away and measured **+15 µs p50** on the batched one. Same concept, four orders of magnitude cheaper.

---

## 4. The four loops the library actually closed

"Plasticity" isn't one feature; it's a small set of feedback loops that share the same conceptual shape. Each one starts from data KAOS was already collecting, and each one turns that data into something the framework now *does* automatically.

![The four loops KAOS closes](https://canivel.github.io/kaos/blog/charts-multiagent/05-four-loops.png)

**1. Inline synaptic plasticity.** Every time an agent records a skill outcome, retrieves a memory, or completes / fails, a hook fires in the caller's transaction. No extra fsync. The hook is deliberately minimal: it updates a counter, not a graph. Measured: **+15 µs p50** on `record_outcome`.

**2. Batched structural consolidation.** At agent completion and at every `KAOS_DREAM_THRESHOLD` sessions, a single `executemany` rebuilds the Hebbian co-occurrence graph (skill↔skill, memory↔memory, skill↔memory), then a full consolidation pass proposes promotions (memory → skill), prunes low-success skills, and flags near-duplicate pairs for operator-reviewed merge.

**3. Policy auto-approval.** When the shared log detects a repeated pattern — *"this action gets approved every time"* — it promotes the pattern into a `policies` row. On the next matching intent, `SharedLog.intent_auto()` consults the policy and short-circuits the full intent → vote → decide cycle with an auto-approve. The consensus loop is still the source of truth; the policy table just memoises its recurring answers.

**4. Failure diagnosis with cached LLM fallback.** Every failed tool call gets fingerprinted and classified by a registry of heuristic diagnosers (connection refused, rate limit, auth, timeout, resource exhaustion, DNS, missing required argument, Python exception types). Failures no heuristic matches fall through to an opt-in LLM diagnoser whose results are cached by fingerprint — so the framework pays the model cost at most once per unique failure, then answers in microseconds forever after.

All four loops share one design discipline: **the hot path stays fast, and the smart work is batched or cached.** That's the only way you get plasticity under multi-agent concurrency without re-introducing the latency problem KAOS set out to avoid.

---

## 5. What this buys you when you actually run N agents

The individual numbers live in the [whitepaper](https://canivel.github.io/kaos/papers/kaos-neuroplasticity-whitepaper.html) and the committed benchmark folders. What matters here is what those numbers mean in aggregate when you point N agents at a shared library.

![Retrieval accuracy: BM25 vs plasticity-weighted](https://canivel.github.io/kaos/blog/charts-multiagent/01-retrieval-accuracy.png)
*Two benchmarks, two different ground-truth designs. Plasticity wins on both. Numbers are measured, reproducible, committed.*

**Retrieval gets better, slowly, automatically.** The first time an agent searches for a skill, BM25 is the only signal available. After a few dozen sessions have fed outcome data back into the system, the weighted ranker starts outperforming BM25 by double-digit percentage points on realistic workloads. The agents don't have to know this is happening; the rank is simply better when they ask for results.

![Alpha sensitivity sweep](https://canivel.github.io/kaos/blog/charts-multiagent/02-alpha-sensitivity.png)
*Sensitivity sweep over the plasticity weight. The shipped default α=3.0 sits on a broad plateau covering α=2 through α=12. Not a knife-edge choice.*

**Redundant skills don't silently accumulate.** When two agents independently save skills that do the same thing, consolidation notices the Jaccard overlap and generates a merge proposal. An operator (or an authorised agent) reviews it; acceptance migrates all telemetry, collapses associations, and soft-deprecates the retired skill with a rationale. The library stays lean instead of quietly doubling every few weeks.

**Known failures stop being re-diagnosed.** A failure fingerprint is populated the first time any agent hits the error. Every subsequent agent in the population — across sessions, across projects — gets the known diagnosis and suggested action in microseconds. The LLM-backed fallback covers the novel tail; the cache means novelty costs once.

**Consensus becomes policy.** An action the team keeps approving turns into a rule that agents can consult at intent time. Human judgement still makes the call the first N times; after that, the framework has learned the verdict and applies it consistently. The supervisors spend their attention on novel decisions, not re-approvals.

None of these buy you performance on a single task in isolation. They buy you **coherent behaviour at population scale** — the thing a single-agent framework doesn't need and a multi-agent one can't ship without.

---

## 6. What the analogy does *not* buy you

The honest limits are worth reading slowly.

![Consolidation cost vs library size](https://canivel.github.io/kaos/blog/charts-multiagent/03-consolidation-scale.png)
*Sub-linear up to 1k skills. Above that, the pairwise Jaccard merge scan dominates and growth turns near-quadratic. A budget problem, not a latency problem — but a real one to name.*

**Gains are workload-conditional.** Plasticity only helps where feedback is informative and retrieval is ambiguous. If agents never record outcomes, the Wilson bound has nothing to stand on. If the right answer is trivially the BM25 winner on every query, there's no room for plasticity to lift anything. The framework degrades gracefully to BM25 in those cases; it doesn't magically create signal that wasn't there.

**The metaphor is a metaphor.** Biology didn't give us a correctness proof; it gave us a useful two-timescale split and a handful of names. "Wilson lower bound" is not a real synapse. Sleep consolidation in the brain re-encodes representations; KAOS's consolidation phase rewrites a handful of SQL rows. Don't over-read the analogy when debugging — at 3am, the bug is in the SQL, not the biology.

**Merges stay human-in-the-loop by design.** The library can flag two near-duplicate skills, but it won't auto-collapse them. Two skills that look like duplicates by Jaccard are occasionally genuinely distinct in ways only a human (or an authorised reviewer agent) can see. The accept/reject workflow exists precisely so those cases stay recoverable.

**Population size matters.** With two agents sharing a database you'll see some plasticity effects but they'll be noisy. The system really starts paying for itself once you have enough concurrent activity that the same error, the same skill, the same approval pattern recurs across many independent sessions. *Many* here is tens of sessions per day, not thousands per second.

**The consolidation phase has quadratic cost above 1,000 skills.** The pairwise Jaccard merge scan is O(n²) by construction; we measured 493 ms at 1k skills and 38 s at 10k. It runs opportunistically, not on the agent hot path, so this is a budget problem, not a latency problem — but it's a real budget problem worth naming. At very-large scale, shard the merge detection by tag or disable it.

---

> Neuroplasticity in a multi-agent framework isn't *"the agents got smarter."* It's *"the **library** got an opinion about its own contents."* Ranking learns. Redundancy gets flagged. Failures cache. Consensus turns into policy. All of it happens continuously, at the population level, as a side effect of agents doing their normal work — which is the only way to make it work at all when there is no orchestrator and no wake/sleep cycle to hang structural work off of.

The journey is still early. Whatever shape this takes in v0.9 will come from more agents, more workloads, more people actually running into the cases where the library's opinion matters — and the next round of honest limits we haven't noticed yet.

---

**Further reading:**
- The [v0.8.1 growth story](https://canivel.github.io/kaos/blog/kaos-neuroplasticity.html) covers how this actually got built and why the first architecture got thrown away.
- The [whitepaper](https://canivel.github.io/kaos/papers/kaos-neuroplasticity-whitepaper.html) goes into the formulas and benchmarks.
- The [code](https://github.com/canivel/kaos) and every benchmark in this post live in the repo.

*Every number quoted in this post is measured, reproducible, and committed alongside its script.*
