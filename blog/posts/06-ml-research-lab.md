# 4 Hypotheses. 4 Agents. 1 Night. Let the Machine Do the Research.

*ML Research · April 15, 2026 · 9 min read*

*How KAOS turns a single train.py into a parallel ML experiment lab — isolated, auditable, and queryable — inspired by Karpathy's autoresearch.*

---

You have one GPU cluster and four competing ideas. You can only run one tonight. Or can you?

The classic ML researcher bottleneck: experiments are serial by default. One hypothesis at a time. Run it, wait, read the loss curve, form the next hypothesis, repeat. A four-hypothesis night takes four nights.

KAOS breaks the serialization. Four agents, four isolated copies of `train.py`, four hypotheses running in parallel overnight. You wake up to a SQL table of results and a clear winner.

---

![KAOS ML research lab demo — 4 agents running parallel experiments overnight, SQL results table, winner identified](https://canivel.github.io/kaos/docs/demos/kaos_uc_mllab.gif)

*4 agents spawn at 22:00. scale-explorer finishes first at 00:14. arch-explorer finishes last at 05:47. SQL comparison at 06:00 shows clear winner.*

---

## Inspired by Karpathy's Autoresearch

[Karpathy's autoresearch](https://github.com/karpathy/autoresearch) is a compelling demonstration: one agent, one GPU, given a model training script. The agent modifies `train.py`, runs it, reads the loss curve, and proposes an improvement. It keeps the changes that help, discards the ones that don't, and iterates through the night.

The key insight: ML research is systematic enough to be automated. An agent can read a loss curve and generate a reasonable next hypothesis. The bottleneck isn't intelligence — it's the serial loop.

The KAOS version extends this to N agents and N hypotheses running simultaneously. Each agent gets its own isolated VFS copy of the training code. They cannot see each other's modifications. Results are queryable when they finish. The insights compound across searches via the KAOS knowledge agent.

---

## The Problem: Character-Level Language Model, val_loss = 2.34

Task: improve a character-level language model baseline. The model trains on Shakespeare. Current best: `val_loss = 2.34`. Four hypotheses to test tonight:

- **arch-explorer** — LoRA adapters vs full finetune (hypothesis: parameter efficiency helps small models generalize)
- **optim-explorer** — AdamW vs Lion optimizer (hypothesis: Lion's sign-based updates work better for small LMs)
- **scale-explorer** — batch size 32 vs 128 (hypothesis: larger batches stabilize char-level training)
- **reg-explorer** — dropout 0.1 vs 0.3 (hypothesis: more regularization needed for character-level overfit)

Sequential: 4 nights minimum. Parallel with KAOS: one night.

---

## Spawning 4 Isolated Agents

```bash
kaos parallel \
  "spawn arch-explorer  --from ./charlm --task lora_vs_full" \
  "spawn optim-explorer --from ./charlm --task adamw_vs_lion" \
  "spawn scale-explorer --from ./charlm --task batch_32_vs_128" \
  "spawn reg-explorer   --from ./charlm --task dropout_01_vs_03"

# [arch-explorer]   spawned  vfs_id=arch-2a1b  status=running
# [optim-explorer]  spawned  vfs_id=opt-5c3d   status=running
# [scale-explorer]  spawned  vfs_id=scl-8e4f   status=running
# [reg-explorer]    spawned  vfs_id=reg-1g7h   status=running
#
# 4 agents training in parallel — 22:00
```

Each agent's `train.py` is in its own VFS. No file conflicts. No race conditions. Agent 1 cannot accidentally overwrite Agent 2's best checkpoint. Fully reproducible — each experiment can be replayed from its exact VFS state.

---

## Running Overnight — Interleaved Training Loops

```
[00:14]  scale-explorer   COMPLETE  final_val_loss=2.21  (-5.6%)
         Finding: batch_size=128 stabilizes training. Converges faster.

[01:47]  reg-explorer     COMPLETE  final_val_loss=2.28  (-2.6%)
         Finding: dropout=0.3 marginally helps. Small effect.

[03:31]  optim-explorer   COMPLETE  final_val_loss=2.19  (-6.4%)
         Finding: Lion optimizer wins on this task. Better char-level.

[05:47]  arch-explorer    COMPLETE  final_val_loss=1.89  (-19.2%)
         Finding: LoRA + cosine LR schedule. Clear winner.
```

`scale-explorer` finishes first — batch size is a simpler change. `arch-explorer` finishes last — LoRA requires more iterations to stabilize, and the agent runs two full training cycles to compare.

---

## The SQL Comparison

```sql
SELECT
  agent_name,
  final_val_loss,
  ROUND((2.34 - final_val_loss) / 2.34 * 100, 1) AS improvement_pct,
  train_time_min,
  notes
FROM ml_results
WHERE run_id = 'overnight-2026-04-15'
ORDER BY final_val_loss ASC
```

| Agent | val_loss | Improvement | Time | Finding |
|---|---|---|---|---|
| arch-explorer | **1.89** | **-19.2%** | 347 min | LoRA + cosine LR schedule |
| optim-explorer | 2.19 | -6.4% | 191 min | Lion optimizer outperforms AdamW |
| scale-explorer | 2.21 | -5.6% | 74 min | batch=128 stabilizes convergence |
| reg-explorer | 2.28 | -2.6% | 182 min | dropout=0.3 marginal improvement |

`arch-explorer` wins by a wide margin. val_loss 1.89 — a 19.2% improvement over baseline. The LoRA + cosine LR combination is the clear path forward. Lion optimizer is worth combining with the LoRA result.

---

## Read the Winner

```
kaos read arch-explorer /results/best_config.md

## Winning Configuration — val_loss = 1.89

### Architecture Changes
- LoRA rank: 8 (r=8, alpha=16)
- Applied to: q_proj, v_proj in all attention layers
- Full finetune baseline: val_loss=2.34 (no improvement)
- LoRA finetune: val_loss=1.89 (19.2% improvement)

### Training Changes
- LR schedule: cosine with warmup (1% warmup steps)
- Peak LR: 3e-4 (was 1e-3 — reduced due to LoRA sensitivity)
- Gradient clip: 1.0 (unchanged)

### Hypothesis confirmed
Parameter-efficient finetuning (LoRA) dramatically outperforms
full finetune on this small character-level model. The reduced
parameter count prevents overfitting on the Shakespeare corpus.
```

---

## Checkpoint and Compound

```bash
kaos checkpoint arch-explorer --label winning-lora-config

# Seed the next search from this agent's discoveries
kaos mh search \
  -b char_lm \
  --seed-from arch-explorer \
  --model claude-sonnet-4-6 \
  -n 10

# [mh-search] Loading knowledge from arch-explorer...
# [mh-search] Loaded skills: lora_param_efficiency, cosine_lr_warmup
# [mh-search] Seeding with best config: val_loss=1.89
# [mh-search] Search starts from the known frontier, not from scratch
```

The next search doesn't start from baseline 2.34. It starts from 1.89, with the LoRA insight already encoded as a reusable skill. The insights compound. Each overnight run seeds the next.

**The compounding effect:** After 3 overnight runs, the knowledge agent has a library of reusable skills for this architecture. Run 4 starts with a seed pool that would have taken weeks of manual iteration to assemble.

---

## The Cost

| Approach | Wall Time | Engineer Time | Hypotheses Tested |
|---|---|---|---|
| Sequential (human-driven) | 4 nights | 4 × setup + analysis | 4 |
| KAOS parallel overnight | 1 night | 30 min setup + 15 min review | 4 |

Same 4 hypotheses. One night instead of four. No wasted hypotheses — even the weaker results are real data that inform the next search. The machine ran the experiments. You read the results.

---

The machine ran 4 experiments overnight. You wake up to a SQL table of results and a clear winner. The winning configuration is documented, checkpointed, and ready to apply. The insights are encoded as reusable skills that seed the next search.

That's how research should work.

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). KAOS extends the single-agent loop to N parallel agents with isolated VFS, SQL-queryable results, and persistent knowledge across searches.*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
