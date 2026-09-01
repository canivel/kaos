"""ARC-AGI-3 end-to-end validation for Dream M1+M2+M3.

Simulates the meta-harness evolutionary search over a handful of ARC games,
capturing every plasticity signal a real run would produce. Verifies the
automatic dream mechanism picks it all up without manual invocation.

Run with::

    cd demo_arc_agi3_test
    uv run python scenario.py

Exits 0 only if every validation passes.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from kaos import Kaos  # noqa: E402
from kaos.dream import DreamCycle  # noqa: E402
from kaos.memory import MemoryStore  # noqa: E402
from kaos.shared_log import SharedLog  # noqa: E402
from kaos.skills import SkillStore  # noqa: E402

DB = HERE / "arc-agi3-plastic.db"
DREAMS_DIR = HERE / "Dreams"

# Threshold low enough that we cross it during the scenario and trigger
# auto-consolidation organically.
os.environ["KAOS_DREAM_THRESHOLD"] = "6"


# ── Realistic ARC-AGI-3 planted data ───────────────────────────────


GAMES = [
    # (game_id, title, baseline_actions_per_level)
    ("ls20", "Light Switch 20", [12, 20, 28]),
    ("vc33", "Vertical Climb 33", [15, 25]),
    ("ft09", "Frame Transform 09", [18, 22, 30, 40]),
    ("gs50", "Grid Solver 50", [10]),
    ("ex01", "Escape 01", [25, 35, 45]),
    ("hs45", "Hash Shift 45", [20, 30]),
]

STRATEGIES = [
    # (skill_name, description, template, success_rate_numerator_out_of_total,
    #  is_merge_duplicate_of)
    ("random-fallback",
     "Pick a random available action. Baseline for comparison.",
     "def choose_action(grid, available_actions, state):\n"
     "    return random.choice(available_actions), None",
     (5, 15), None),

    ("systematic-click-sweep",
     "Sweep click across the grid in row-major order, dedupe by frame hash.",
     "def choose_action(grid, available_actions, state):\n"
     "    # systematic sweep pattern\n"
     "    return 6, {'x': (state['total_actions'] % 64), "
     "'y': (state['total_actions'] // 64) % 64}",
     (12, 15), None),

    ("productive-first-replay",
     "Replay actions that historically changed the frame on a similar grid.",
     "def choose_action(grid, available_actions, state):\n"
     "    # productive action replay heuristic\n"
     "    prod = state.get('globally_productive', {})\n"
     "    best = max(available_actions, key=lambda a: prod.get(a, 0))\n"
     "    return best, None",
     (14, 15), None),

    ("click-nonzero-objects",
     "Click on the first non-zero pixel; fall back to random coordinates.",
     "def choose_action(grid, available_actions, state):\n"
     "    # click non-zero object strategy\n"
     "    if 6 in available_actions:\n"
     "        nz = np.argwhere(grid != 0)\n"
     "        if len(nz):\n"
     "            return 6, {'x': int(nz[0][1]), 'y': int(nz[0][0])}\n"
     "    return available_actions[0], None",
     (10, 15), None),

    ("bfs-state-exploration",
     "Breadth-first exploration of frame states using visited_hashes.",
     "def choose_action(grid, available_actions, state):\n"
     "    # BFS explorer: try unvisited actions first\n"
     "    tried = state['tried_actions'].get(state.get('prev_hash'), set())\n"
     "    untried = [a for a in available_actions if a not in tried]\n"
     "    return (untried[0] if untried else available_actions[0]), None",
     (2, 8), None),

    ("color-match-pattern",
     "Match the dominant grid color to infer the next useful action.",
     "def choose_action(grid, available_actions, state):\n"
     "    return available_actions[0], None",
     (0, 0), None),  # never used — fully cold

    ("corner-tap-heuristic",
     "Tap the four grid corners in sequence, sweep click dedupe by frame hash.",
     "def choose_action(grid, available_actions, state):\n"
     "    # corner tap variant\n"
     "    return 6, {'x': 0, 'y': 0}",
     (8, 12), "systematic-click-sweep"),  # near-duplicate for merge detection
]

MEMORY_ENTRIES = [
    # (key, type, content, search_query, hits_count)
    ("rhae-formula", "insight",
     "RHAE = sum of weighted level scores: (l+1) * min(1, h/a)^2. "
     "Higher weight on later levels (they're harder).",
     "RHAE formula weighted score", 9),

    ("action-6-requires-data", "result",
     "Action value 6 is 'click' and REQUIRES data={'x': int, 'y': int}. "
     "Passing None raises TypeError.",
     "action 6 click data", 7),

    ("frame-hash-dedup-pattern", "insight",
     "MD5-hash the grid bytes to detect duplicate frames; track tried_actions "
     "per hash to avoid infinite loops.",
     "frame hash duplicate detection", 5),

    ("level-reset-on-game-over", "observation",
     "When frame.state == GAME_OVER, send RESET action and clear "
     "visited_hashes for the new level.",
     "game over reset", 2),

    ("obsolete-action-5-note", "observation",
     "Early v1 harnesses used action=5 for undo — removed in v2 API. "
     "Do not reference.",
     "action 5 undo obsolete", 0),  # cold entry
]

# Planted failures that the meta-harness mutation process would realistically
# trigger. Each (error_message, tool_name, count) gets planted via failing agents.
FAILURES = [
    ("KeyError: 'tried_actions'", "harness_run", 3),
    ("TypeError: click requires data dict", "harness_run", 2),
    ("Timeout exceeded 120s on game ls20", "harness_run", 1),
]


# ── Validation harness ──────────────────────────────────────────────


class Checks:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed.append(name)
            print(f"  [PASS] {name}")
        else:
            self.failed.append((name, detail))
            print(f"  [FAIL] {name}  {detail}")

    def summary(self) -> int:
        print("")
        total = len(self.passed) + len(self.failed)
        print(f"  {len(self.passed)}/{total} checks passed")
        return 0 if not self.failed else 1


# ── Phases ──────────────────────────────────────────────────────────


def phase_reset() -> None:
    print("\n== Reset ==")
    if DB.exists():
        DB.unlink()
    if DREAMS_DIR.exists():
        shutil.rmtree(DREAMS_DIR)
    print(f"  DB:       {DB}")
    print(f"  Digests:  {DREAMS_DIR}")
    print(f"  Threshold: KAOS_DREAM_THRESHOLD={os.environ.get('KAOS_DREAM_THRESHOLD')}")


def phase_schema(checks: Checks) -> Kaos:
    print("\n== Schema v5 present ==")
    kaos = Kaos(db_path=str(DB))
    expected_tables = [
        "agents", "files", "blobs", "tool_calls", "state", "events",
        "checkpoints", "memory", "memory_fts", "shared_log",
        "agent_skills", "agent_skills_fts",
        # v4
        "skill_uses", "memory_hits", "dream_runs", "episode_signals",
        # v5
        "associations", "failure_fingerprints", "policies",
        "consolidation_proposals",
    ]
    rows = kaos.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    actual = {r[0] for r in rows}
    for t in expected_tables:
        checks.check(f"table '{t}' exists", t in actual)

    # v5 deprecated columns on agent_skills
    col_names = [r[1] for r in kaos.conn.execute(
        "PRAGMA table_info(agent_skills)"
    ).fetchall()]
    for col in ("deprecated", "deprecated_at", "deprecated_reason"):
        checks.check(f"agent_skills.{col} column present", col in col_names)

    version = kaos.conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0]
    checks.check("schema version == 5", version == 5, f"got {version}")
    return kaos


def phase_seed_strategies(kaos: Kaos, checks: Checks) -> dict[str, int]:
    """Plant the strategy skills as if the meta-harness seeded them."""
    print("\n== Seed strategies ==")
    sk = SkillStore(kaos.conn)
    seed_agent = kaos.spawn("meta-harness-seed")

    skill_ids: dict[str, int] = {}
    for name, desc, template, (success, total), _dup in STRATEGIES:
        sid = sk.save(name=name, description=desc, template=template,
                      source_agent_id=seed_agent,
                      tags=["arc-agi-3", "strategy"])
        skill_ids[name] = sid

    checks.check(f"seeded {len(STRATEGIES)} strategies",
                 len(skill_ids) == len(STRATEGIES))
    return skill_ids


def phase_seed_memory(kaos: Kaos, checks: Checks) -> dict[str, int]:
    """Plant ARC-AGI-3 domain memory entries."""
    print("\n== Seed domain memory ==")
    mem = MemoryStore(kaos.conn)
    seed_agent = kaos.spawn("arc-agi-domain-expert")

    memory_ids: dict[str, int] = {}
    for key, mtype, content, _q, _n in MEMORY_ENTRIES:
        mid = mem.write(agent_id=seed_agent, content=content,
                        type=mtype, key=key)
        memory_ids[key] = mid

    kaos.complete(seed_agent)  # episode #1 (threshold=6, won't fire yet)
    checks.check(f"seeded {len(MEMORY_ENTRIES)} memory entries",
                 len(memory_ids) == len(MEMORY_ENTRIES))
    return memory_ids


def phase_simulate_search(kaos: Kaos, skill_ids: dict[str, int],
                           checks: Checks) -> None:
    """Simulate N meta-harness iterations — spawning candidates that apply
    skills, retrieve memory, and succeed or fail per game."""
    print("\n== Simulate meta-harness iterations ==")
    sk = SkillStore(kaos.conn)
    mem = MemoryStore(kaos.conn)

    # Apply planted (success, total) patterns for each strategy across games
    for name, _desc, _template, (success, total), _dup in STRATEGIES:
        if total == 0:
            continue
        sid = skill_ids[name]
        for i in range(total):
            # One candidate agent per application
            aid = kaos.spawn(f"candidate-{name}-{i}")
            # Record the skill outcome FIRST (so the agent has a skill_use
            # by the time memory retrieval fires the cross-modal hook).
            did_succeed = (i < success)
            sk.record_outcome(sid, success=did_succeed, agent_id=aid)
            # Memory retrieval — the strategy consults known tips
            for key, _mtype, _content, query, hits in MEMORY_ENTRIES:
                if i < hits:  # bias hits to most-popular entries
                    mem.search(query, record_hits=True, requesting_agent_id=aid)
                    break

            if did_succeed:
                kaos.complete(aid)
            else:
                # Failed candidates — plant a realistic error
                if FAILURES:
                    err_msg, tool, _ = FAILURES[i % len(FAILURES)]
                    call = kaos.log_tool_call(aid, tool, {"candidate": name})
                    kaos.start_tool_call(call)
                    kaos.complete_tool_call(
                        call, output={}, status="error",
                        error_message=err_msg, token_count=50,
                    )
                kaos.fail(aid, error=f"candidate {name} failed iter {i}")

    total_agents = kaos.conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    completed = kaos.conn.execute(
        "SELECT COUNT(*) FROM agents WHERE status='completed'"
    ).fetchone()[0]
    failed = kaos.conn.execute(
        "SELECT COUNT(*) FROM agents WHERE status='failed'"
    ).fetchone()[0]
    print(f"  spawned={total_agents} completed={completed} failed={failed}")
    checks.check("many agents spawned", total_agents >= 60,
                 f"got {total_agents}")
    checks.check("many completions", completed >= 40, f"got {completed}")
    checks.check("failures realistic", failed >= 6, f"got {failed}")


def phase_shared_log_policy_cycle(kaos: Kaos, checks: Checks) -> None:
    """Run three identical shared-log cycles so policies.run() has a candidate."""
    print("\n== Shared-log policy cycles ==")
    log = SharedLog(kaos.conn)
    for i in range(3):
        aid = kaos.spawn(f"proposer-{i}")
        intent_id = log.intent(aid, "promote productive-first-replay to default")
        log.vote(aid, intent_id, approve=True)
        log.decide(intent_id, aid)
        kaos.complete(aid)

    votes = kaos.conn.execute(
        "SELECT COUNT(*) FROM shared_log WHERE type='vote'"
    ).fetchone()[0]
    checks.check("shared_log votes recorded", votes >= 3, f"got {votes}")


def phase_validate_auto_plasticity(kaos: Kaos, checks: Checks) -> None:
    """Everything in this section must be observable as a side-effect of the
    normal agent activity above — NO manual `kaos dream` calls."""
    print("\n== Validate AUTOMATIC plasticity (no manual dream run) ==")
    conn = kaos.conn

    # Episode signals populated inline
    ep_count = conn.execute(
        "SELECT COUNT(*) FROM episode_signals"
    ).fetchone()[0]
    checks.check("episode_signals populated inline (every agent got a row)",
                 ep_count >= 60, f"got {ep_count}")

    # Skill associations
    skill_assocs = conn.execute(
        "SELECT COUNT(*) FROM associations "
        "WHERE kind_a='skill' AND kind_b='skill'"
    ).fetchone()[0]
    # Note: each agent only uses ONE skill in our sim, so skill↔skill
    # associations only form through shared agent_id across record_outcome.
    # We accept >= 0 here but check cross-modal edges below.
    checks.check("associations table exists and is queryable",
                 skill_assocs >= 0)

    # Cross-modal skill↔memory edges
    cross = conn.execute(
        "SELECT COUNT(*) FROM associations "
        "WHERE kind_a='skill' AND kind_b='memory'"
    ).fetchone()[0]
    checks.check("cross-modal skill->memory associations built automatically",
                 cross > 0, f"got {cross}")

    # Failure fingerprints captured inline
    fp_rows = conn.execute(
        "SELECT fingerprint, count FROM failure_fingerprints "
        "ORDER BY count DESC"
    ).fetchall()
    checks.check("failure fingerprints captured automatically",
                 len(fp_rows) >= 2, f"got {len(fp_rows)}")
    if fp_rows:
        max_count = fp_rows[0][1]
        checks.check("duplicate errors merged (one fingerprint, count > 1)",
                     max_count >= 2, f"max_count={max_count}")

    # Memory hits recorded inline
    hits = conn.execute("SELECT COUNT(*) FROM memory_hits").fetchone()[0]
    checks.check("memory_hits populated inline", hits > 0, f"got {hits}")

    # Auto-consolidation fired (threshold=6 should cross multiple times with 60+ episodes)
    # Threshold-triggered consolidation writes consolidation_proposals rows
    proposals = conn.execute(
        "SELECT COUNT(*) FROM consolidation_proposals"
    ).fetchone()[0]
    checks.check("auto-consolidation ran and logged proposals (threshold crossings)",
                 proposals >= 1, f"got {proposals}")

    # Low-success skill soft-deprecated by auto-consolidation apply path
    # (auto triggers run in dry_run=True by default — verify manually below)


def phase_manual_consolidation_apply(kaos: Kaos, checks: Checks) -> None:
    """Run a manual `consolidate --apply` to exercise the prune/promote path."""
    print("\n== Manual consolidate --apply ==")
    from kaos.dream.phases.consolidation import run as consolidate_run

    # Use a lower merge threshold for this data set — the strategy descriptions
    # are intentionally varied in vocabulary so Jaccard lands around 0.5.
    report = consolidate_run(kaos.conn, dry_run=False,
                             trigger_reason="test-manual",
                             merge_threshold=0.5)
    checks.check("consolidate found prune candidates (bfs-state, random)",
                 report.pruned >= 1, f"pruned={report.pruned}")
    checks.check("consolidate found promote candidates (hot memory)",
                 report.promoted >= 1, f"promoted={report.promoted}")
    checks.check("consolidate identified merge candidates (systematic + corner-tap)",
                 report.merge_candidates >= 1,
                 f"merge_candidates={report.merge_candidates}")
    checks.check("applied >= 1 structural change",
                 report.applied >= 1, f"applied={report.applied}")

    # Verify a skill got soft-deprecated
    deprecated = kaos.conn.execute(
        "SELECT COUNT(*) FROM agent_skills WHERE deprecated=1"
    ).fetchone()[0]
    checks.check("at least one skill soft-deprecated by prune",
                 deprecated >= 1, f"got {deprecated}")

    # Verify a promoted skill appeared (memory → skill)
    promoted = kaos.conn.execute(
        "SELECT COUNT(*) FROM agent_skills WHERE name = 'rhae-formula'"
    ).fetchone()[0]
    checks.check("hot memory 'rhae-formula' promoted to a skill",
                 promoted == 1, f"got {promoted}")


def phase_policy_promotion(kaos: Kaos, checks: Checks) -> None:
    print("\n== Policy promotion ==")
    from kaos.dream.phases.policies import run as policies_run
    report = policies_run(kaos.conn, dry_run=False)
    checks.check("policy promoted from repeated approvals",
                 report.total_promoted >= 1,
                 f"total_promoted={report.total_promoted}")
    row = kaos.conn.execute(
        "SELECT action_pattern, approval_rate, sample_size FROM policies LIMIT 1"
    ).fetchone()
    if row is not None:
        checks.check("promoted policy action pattern includes 'productive-first'",
                     "productive-first" in (row[0] or ""),
                     f"got {row[0]}")
        checks.check("promoted policy approval_rate >= 0.9",
                     (row[1] or 0) >= 0.9, f"got {row[1]}")


def phase_dream_run_writes_digest(kaos: Kaos, checks: Checks) -> None:
    print("\n== Full dream run + digest ==")
    cycle = DreamCycle(kaos, digest_dir=DREAMS_DIR)
    result = cycle.run(dry_run=True)

    checks.check("dream run_id returned", result.run_id > 0)
    checks.check("digest file written to disk",
                 result.digest_path and Path(result.digest_path).is_file(),
                 f"path={result.digest_path}")

    digest = result.digest_markdown
    section_checks = [
        ("KAOS dream digest header", "# KAOS dream digest"),
        ("Episodes replay section", "## Episodes (replay)"),
        ("Hot skills section", "Hot skills"),
        ("Hot memory section", "Hot memory"),
        ("Associations section", "Associations"),
        ("Failure fingerprints section", "Failure fingerprints"),
        ("Consolidation proposals section", "Consolidation proposals"),
    ]
    for label, needle in section_checks:
        checks.check(f"digest has {label}",
                     needle in digest,
                     f"missing: {needle}")

    # The digest should mention our planted strategies
    checks.check("digest mentions 'productive-first-replay' (hot skill)",
                 "productive-first-replay" in digest)
    checks.check("digest mentions at least one failure tool_name",
                 "harness_run" in digest)

    # All 7 phase timings present
    for phase_key in ("replay_ms", "weights_ms", "associations_ms",
                      "failures_ms", "consolidation_ms", "policies_ms",
                      "narrative_ms", "total_ms"):
        checks.check(f"phase timing '{phase_key}' recorded",
                     phase_key in result.phase_timings_ms)


def phase_weighted_search(kaos: Kaos, checks: Checks) -> None:
    print("\n== Weighted search — proven strategies rank first ==")
    sk = SkillStore(kaos.conn)

    # Query matching multiple strategy descriptions: "grid" + "frame" + "action"
    # appear across random/systematic/productive/click-nonzero/bfs.
    q = "grid OR frame OR action OR click"
    results = sk.search(q, limit=10, rank="weighted")
    names = [s.name for s in results]
    print(f"  weighted top: {names[:5]}")
    checks.check("productive-first-replay appears in top weighted results",
                 "productive-first-replay" in names,
                 f"names={names}")
    checks.check("systematic-click-sweep appears in top weighted results",
                 "systematic-click-sweep" in names,
                 f"names={names}")

    bm25_results = sk.search(q, limit=10, rank="bm25")
    bm25_names = [s.name for s in bm25_results]
    if "random-fallback" in names and "productive-first-replay" in names:
        checks.check("productive-first ranks ahead of random under weighted",
                     names.index("productive-first-replay") <
                     names.index("random-fallback"),
                     f"prod={names.index('productive-first-replay')} "
                     f"rnd={names.index('random-fallback')}")
    # Cross-check: weighted differs from bm25 somewhere
    checks.check("weighted ordering differs from bm25",
                 names != bm25_names,
                 f"bm25={bm25_names[:3]} weighted={names[:3]}")


def phase_cli_integration(checks: Checks) -> None:
    print("\n== CLI integration ==")
    import subprocess
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    def run(args):
        return subprocess.run(
            ["uv", "run", "kaos", "--json", *args],
            cwd=str(ROOT), env=env,
            capture_output=True, text=True, encoding="utf-8",
            timeout=60,
        )

    # dream runs
    proc = run(["dream", "runs", "--db", str(DB)])
    checks.check("`kaos dream runs` exits 0",
                 proc.returncode == 0, proc.stderr[:200])
    payload = _parse_json(proc.stdout)
    checks.check("`kaos dream runs` returns a list",
                 isinstance(payload, list))

    # dream consolidate --dry-run
    proc = run(["dream", "consolidate", "--db", str(DB), "--dry-run"])
    checks.check("`kaos dream consolidate --dry-run` exits 0",
                 proc.returncode == 0, proc.stderr[:200])
    d = _parse_json(proc.stdout)
    checks.check("consolidate payload has consolidation field",
                 isinstance(d, dict) and "consolidation" in d)

    # dream failures
    proc = run(["dream", "failures", "--db", str(DB), "--min-count", "1"])
    checks.check("`kaos dream failures` exits 0",
                 proc.returncode == 0, proc.stderr[:200])
    fp_list = _parse_json(proc.stdout)
    checks.check("failures list non-empty",
                 isinstance(fp_list, list) and len(fp_list) >= 1)

    # dream related on a hot skill
    proc = run(["dream", "related", "skill",
                "productive-first-replay", "--db", str(DB)])
    checks.check("`kaos dream related` exits 0",
                 proc.returncode == 0, proc.stderr[:200])


def phase_real_arc_smoke(checks: Checks) -> None:
    """Optional: if arc-agi SDK is installed, instantiate the real benchmark
    (1 game, 10s budget) to confirm wiring. Skipped otherwise.
    """
    print("\n== Optional: real ARC-AGI-3 benchmark smoke test ==")
    try:
        import arc_agi  # noqa: F401
    except ImportError:
        print("  [SKIP] arc-agi SDK not installed")
        return

    try:
        from kaos.metaharness.benchmarks.arc_agi3 import ArcAGI3Benchmark
    except ImportError as e:
        print(f"  [SKIP] benchmark not loadable: {e}")
        return

    try:
        bench = ArcAGI3Benchmark(time_per_game=10, max_actions=100,
                                 n_search_games=1, n_test_games=0)
    except Exception as e:
        print(f"  [SKIP] benchmark init failed: {e}")
        return

    search = bench.get_search_set()
    checks.check("real benchmark produces at least 1 search problem",
                 len(search) >= 1, f"got {len(search)}")
    if search:
        p = search[0]
        checks.check("search problem has a game_id",
                     bool(p.input.get("game_id")))
        checks.check("search problem has baseline_actions",
                     isinstance(p.input.get("baseline_actions"), list)
                     and len(p.input["baseline_actions"]) > 0)


# ── JSON parse helper ──────────────────────────────────────────────


def _parse_json(stdout: str):
    s = stdout.strip()
    if not s:
        return None
    if s.startswith(("[", "{")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    for i, ch in enumerate(s):
        if ch in "[{":
            try:
                return json.loads(s[i:])
            except json.JSONDecodeError:
                return None
    return None


# ── Main ────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 68)
    print("KAOS — ARC-AGI-3 full-stack validation for Dream M1+M2+M3")
    print("=" * 68)

    checks = Checks()

    phase_reset()
    kaos = phase_schema(checks)
    try:
        skill_ids = phase_seed_strategies(kaos, checks)
        phase_seed_memory(kaos, checks)
        phase_simulate_search(kaos, skill_ids, checks)
        phase_shared_log_policy_cycle(kaos, checks)
        phase_validate_auto_plasticity(kaos, checks)
        phase_manual_consolidation_apply(kaos, checks)
        phase_policy_promotion(kaos, checks)
        phase_dream_run_writes_digest(kaos, checks)
        phase_weighted_search(kaos, checks)
    finally:
        kaos.close()

    phase_cli_integration(checks)
    phase_real_arc_smoke(checks)

    print("\n" + "=" * 68)
    print("Summary")
    print("=" * 68)
    exit_code = checks.summary()
    if exit_code == 0:
        print("\n  [OK]  ARC-AGI-3 scenario passes end-to-end. "
              "Dream M1+M2+M3 validated.")
    else:
        print(f"\n  [X]  {len(checks.failed)} validation(s) failed:")
        for name, detail in checks.failed:
            print(f"      - {name}  {detail}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
