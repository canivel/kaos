# Tutorial 07 — CORAL Co-Evolution: Multiple Agents Improving Together
**Duration:** 5 minutes  
**Level:** Advanced  
**Goal:** Run multiple meta-harness search agents in parallel that share skills, pivot when stuck, and consolidate discoveries — the CORAL system built into KAOS v0.6.

---

## SCENE 1 — Hook [0:00–0:25]

**[VISUAL: Two search agents running in parallel. Agent A discovers chain-of-thought helps. Agent B learns it automatically via shared skills, skips the discovery phase, and jumps ahead on accuracy.]**

> "One search agent exploring alone is good. Three agents exploring different strategies simultaneously, sharing every useful pattern they discover, is dramatically better. That's CORAL — Collaborative Optimization via Reinforcement and Autonomous Learning. It's built into KAOS v0.6 and it changes how fast you find good harnesses."

---

## SCENE 2 — The Three CORAL Tiers [0:25–1:10]

**[VISUAL: Three-tier diagram — Reflect (every iter), Pivot (stagnation), Consolidate (heartbeat)]**

> "CORAL adds three types of intelligence on top of the base meta-harness loop.

Tier 1 — Reflect: after every evaluation, the proposer is asked to record what it learned in a notes directory before proposing the next harness. Explicit reflection prevents repeating the same failed approaches.

Tier 2 — Consolidate: every 5 iterations, a heartbeat prompt fires asking the proposer to extract reusable patterns — called skills — from what it's discovered so far. Skills persist and transfer to future searches.

Tier 3 — Pivot: when the frontier hasn't improved for 3 consecutive iterations, a pivot prompt fires demanding a structurally different approach. It won't fire again until another 3 stagnant iterations pass — a cooldown that prevents prompt spam."

---

## SCENE 3 — Launching Co-Evolution [1:10–2:10]

**[VISUAL: `mh_spawn_coevolution` MCP call from Claude, or Python equivalent]**

> "Launch a co-evolution run from Claude using the MCP tool:"

**[VISUAL: Claude conversation]**

> User: "Spawn a 3-agent co-evolution search on text_classify for 10 iterations."

```
Tool: mcp__kaos__mh_spawn_coevolution
{
  "benchmark": "text_classify",
  "n_agents": 3,
  "iterations": 10,
  "hub_sync_interval": 2
}
```

**[VISUAL: Claude's response]**
```
Co-evolution started.
Hub agent:  01JQHUB...
Agents:
  A → 01JQAG1...  (strategy: chain-of-thought)
  B → 01JQAG2...  (strategy: few-shot examples) 
  C → 01JQAG3...  (strategy: structured output)

Hub syncs every 2 iterations.
Monitor: kaos dashboard
```

> "Each agent starts with a different seed strategy. Every 2 iterations, they sync via the hub — pushing their best discoveries and pulling skills other agents found."

---

## SCENE 4 — How the Hub Works [2:10–3:00]

**[VISUAL: Hub architecture — three agents pushing/pulling to a shared hub agent]**

> "The hub agent is a shared KAOS agent that holds three directories:"

```
/best_per_agent/<agent-id>.json    ← each agent's current best harness + scores
/shared_skills/                    ← all skills contributed by any agent
/shared_attempts/                  ← compact summaries of all evaluations
```

> "When an agent syncs, it pushes its best harness and any new skills to the hub. Then it pulls skills other agents discovered that it doesn't have yet. A deduplication check prevents agents from re-evaluating harnesses another agent already tried.

The hub sync happens automatically when `mh_next_iteration` is called — every `hub_sync_interval` iterations with no extra code from you."

**[VISUAL: Animation — Agent A pushes a skill icon to hub; Agent B and C pull it; their accuracy bars tick up]**

---

## SCENE 5 — Skills: What They Look Like [3:00–3:40]

**[VISUAL: Example skill file in `/skills/`]**

> "A skill is a named, reusable pattern with a description and optional code template. The proposer writes skills using the `mh_write_skill` tool."

```json
{
  "name": "chain_of_thought_classification",
  "description": "Add step-by-step reasoning before the final label. Improves accuracy on ambiguous cases by ~12 points.",
  "code_template": "prompt = f'Think step by step:\\n{problem[\"text\"]}\\nTherefore the label is:'"
}
```

> "Skills inject automatically into the next iteration's proposer prompt as a structured list of proven techniques. The proposer doesn't rediscover them — it builds on top of them."

---

## SCENE 6 — Stagnation Pivot: The Cooldown [3:40–4:20]

**[VISUAL: Stagnation counter animation — iters 1,2,3 no improvement → pivot fires → iter 4,5,6 no improvement → pivot fires again]**

> "When 3 consecutive iterations pass with no improvement, a pivot prompt demands a structurally different approach — not just a tweak. The exact prompt:"

```
⚠ PIVOT REQUIRED (stagnant for 3 iterations)

The Pareto frontier has NOT improved for the last 3 iterations.
You MUST try something structurally different:
1. Identify the fundamental assumption of the current best approach
2. Negate that assumption — build an approach that avoids it entirely
3. Consider: chain-of-thought, few-shot, ensemble voting, decomposition...
4. Do NOT submit a variant of the current best
```

> "The pivot fires once at stagnation=3, then resets its cooldown. It only fires again after another 3 stagnant iterations — not on iterations 4, 5, 6. This is the CORAL plateau cooldown: meaningful intervention without constant noise."

---

## SCENE 7 — Summary [4:20–5:00]

**[VISUAL: Co-evolution convergence graph — three agent curves, each discovering something, converging faster together than any one alone]**

> "CORAL gives meta-harness search three superpowers: per-iteration reflection to avoid repeated failures, skills that compound and transfer between agents and across runs, and cooldown-protected pivot prompts that force structural exploration when incremental changes stop working.

Co-evolution runs multiple agents simultaneously with a hub that synchronizes discoveries — so one agent's breakthrough becomes all agents' starting point.

That's KAOS v0.6. The final tutorial covers building a custom benchmark so you can run meta-harness search on your own tasks."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Visionary. This is the most novel feature — let the excitement come through.
- **Scene 1 animation:** Two progress curves — one solo (slower), one co-evolution (faster) — animating in parallel, converging earlier.
- **Hub diagram (Scene 4):** Animate skill icons as small glowing dots traveling from agent to hub to other agents. Color-code by agent.
- **Pivot prompt (Scene 6):** Show the actual prompt text appearing on screen, formatted like a warning box with a yellow border. Let it sit for 2-3 seconds so viewers can read it.
