"""Instrument calibration for the Attraktor binding probe (NON-BINDING).

Runs the REAL pipeline — ClaudeCodeRunner + BenchHooks + pull/ledger/arms +
probe gates — in three throwaway sandbox workspaces with KNOWN ground truth:

  effect   : injection causally helps (success needs the un-scrambled secret)
             -> the probe MUST ACCEPT
  null     : injection does nothing (success independent of arms)
             -> the probe MUST NOT ACCEPT (G1 kill expected)
  placebo  : ANY injected tokens 'help', scrambled included (padding artifact)
             -> G4 MUST kill even though G1 passes

This calibrates the instrument, not the loop: episodes here are scripted, so
per the lock they can NEVER feed the binding verdict. Everything runs in
sandbox dirs — the flagship bench.db is untouched. Deliberately NOT logged to
the experiments journal: harvest_experiments would mint it into the real brain.

Run:  uv run python demo_attraktor_loop_bench/calibration.py [sandbox_dir]
Exit: 0 iff all three scenarios land on their expected verdict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from demo_attraktor_loop_bench.probe_adapter import run_probe  # noqa: E402
from kaos import Kaos  # noqa: E402
from kaos.bench.config import BenchConfig  # noqa: E402
from kaos.bench.fingerprint import Grain, Level, anchor_tokens  # noqa: E402
from kaos.bench.hooks import BenchHooks  # noqa: E402
from kaos.bench.schema import bench_id, fts_index_record, open_bench  # noqa: E402
from kaos.ccr.runner import ClaudeCodeRunner  # noqa: E402

logging.disable(logging.WARNING)

SECRET = "use the flag --zeta-42 before retrying"
KEYS = "retry_backoff pipelines/scrape.py"
N_EPISODES = 300
P_HELPED, P_BASE, P_NULL = 0.90, 0.40, 0.60


def seed_brain(bench_path: Path) -> None:
    bench = open_bench(bench_path)
    cid = "tb1:" + "c" * 64
    env = {"consumes": [], "measured": {"M2": int(Level.PRESENT)},
           "m2_grain": int(Grain.EPISODE),
           "retrieval_keys": sorted(anchor_tokens(KEYS)), "wilson_lb": 0.8}
    bench.execute(
        "INSERT INTO eval_records (record_cid, schema_id, kind, self_test_passed,"
        " verdict, variant, faithful, trust_level, repro_class, envelope_json,"
        " body_json, origin_bench_id) VALUES (?, 'attraktor/eval_record/v1',"
        " 'skill', 1, 'ACCEPT', 'as-is', 1, 2, 'llm_nondeterministic', ?, ?, ?)",
        (cid, json.dumps(env),
         json.dumps({"name": "zeta retry skill", "template": SECRET}),
         bench_id(bench)))
    fts_index_record(bench, cid, name="zeta retry skill", keys_text=KEYS)
    bench.commit()
    bench.close()


class ScriptedRouter:
    """Deterministic 'model': the episode outcome is a pure function of the
    scenario's ground truth + what actually reached the system prompt."""
    clients = {"scripted": object()}

    def __init__(self, scenario: str, seed: int) -> None:
        self.scenario = scenario
        self.rng = random.Random(seed)

    async def route(self, **kw):
        system = next((m["content"] for m in kw.get("messages", ())
                       if m.get("role") == "system"), "")
        if self.scenario == "effect":
            p = P_HELPED if SECRET in system else P_BASE
        elif self.scenario == "placebo":
            p = P_HELPED if "Validated workspace learnings" in system else P_BASE
        else:  # null
            p = P_NULL
        if self.rng.random() < p:
            return SimpleNamespace(content="done", tool_calls=[],
                                   stop_reason="end_turn", usage={})
        raise RuntimeError("episode failed (scripted outcome)")


async def run_scenario(name: str, root: Path) -> dict:
    ws = root / name
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    seed_brain(ws / "bench.db")

    cfg = BenchConfig(enabled=True, local_bench_path="bench.db")  # arms_mode=probe
    hooks = BenchHooks(cfg, db_dir=ws)
    afs = Kaos(db_path=str(ws / "kaos.db"))
    runner = ClaudeCodeRunner(afs, ScriptedRouter(name, seed=20260816),
                              bench_hooks=hooks)
    for i in range(N_EPISODES):
        agent_id = afs.spawn(f"cal-{name}-{i}")
        try:
            await runner.run_agent(
                agent_id, f"fix retry_backoff failure {i} in pipelines/scrape.py")
        except RuntimeError:
            pass  # scripted failure — already recorded by the runner path
    afs.close()

    bench = open_bench(ws / "bench.db")
    rep = run_probe(bench, out_dir=ws)  # calibration results stay in the sandbox
    bench.close()
    return rep


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "loop_calibration"
    expectations = {"effect": "ACCEPT", "null": "REJECT", "placebo": "REJECT"}
    all_ok = True
    for name, want in expectations.items():
        rep = asyncio.run(run_scenario(name, root))
        verdict = rep["verdict"]
        ok = verdict.split(":")[0] == want
        if name == "placebo":
            ok = ok and "G4" in verdict
        if name == "null":
            ok = ok and "G1" in verdict
        all_ok &= ok
        print(f"[{'OK' if ok else 'FAIL'}] {name}: expected {want}, got {verdict}")
        print(f"      episodes={rep['episodes']} wins={rep['wins']} "
              f"pulls={rep['pulls']} matched={rep['matched_pulls']} "
              f"self_test={'passed' if rep['self_test_passed'] else 'FAILED'}")
        for g in rep["gates"]:
            print(f"      {'+' if g['passed'] else '-'} {g['gate']}: {g['detail']}")
    print("\nCALIBRATION " + ("PASSED — instrument is admissible" if all_ok
                              else "FAILED — instrument NOT admissible"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
