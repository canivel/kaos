"""ARC-AGI-3 benchmark for meta-harness optimization.

Each problem = one ARC game environment.
Each harness = a complete run(problem) -> dict Python program.
Scoring = RHAE (Relative Human Action Efficiency).
Objectives = maximize RHAE, minimize action count.

Harness interface:
    def run(problem: dict) -> dict:
        # problem keys: game_id, title, tags, baseline_actions, n_levels
        # returns: {"rhae": float, "levels": int, "actions": int}

The proposer reads harness code + execution traces and proposes
improvements to the choose_action logic embedded inside run().
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import traceback
from typing import Any

import numpy as np

from kaos.metaharness.benchmarks import register_benchmark
from kaos.metaharness.benchmarks.base import Benchmark, Problem

# ARC-AGI-3 SDK
# IMPORTANT: arc_agi adds logging.StreamHandler(sys.stdout) during Arcade() init,
# which corrupts the MCP stdio transport. We monkeypatch StreamHandler.__init__
# so any handler that would write to sys.stdout writes to sys.stderr instead.
# This must happen before arc_agi is imported.
import logging as _logging
import sys as _sys

_orig_sh_init = _logging.StreamHandler.__init__
def _mcp_safe_sh_init(self, stream=None):
    if stream is _sys.stdout:
        stream = _sys.stderr
    _orig_sh_init(self, stream)
_logging.StreamHandler.__init__ = _mcp_safe_sh_init

try:
    import arc_agi
    from arcengine.enums import GameAction as GA, GameState as GS
    ARC_AVAILABLE = True
except ImportError:
    ARC_AVAILABLE = False

ACTION_MAP = {a.value: a for a in GA} if ARC_AVAILABLE else {}


def compute_rhae(level_actions: dict[int, int], baseline_actions: list[int]) -> float:
    """Compute RHAE for one game.
    level_actions: {level_idx: agent_action_count}
    baseline_actions: [human_actions_per_level]
    """
    if not level_actions:
        return 0.0
    n = len(baseline_actions)
    total_w = n * (n + 1) / 2
    score = 0.0
    for l in range(n):
        w = l + 1
        if l in level_actions:
            h = baseline_actions[l]
            a = level_actions[l]
            s = min(1.0, h / max(a, 1)) ** 2
            score += w * s
    return score / total_w


def run_agent_on_game(agent_code: str, env_info, arcade, time_budget=120, max_actions=5000) -> dict:
    """Execute an agent strategy (Python code) on one ARC game.

    The agent_code must define a function:
        def choose_action(grid, available_actions, state) -> (action_value, data_dict_or_None)

    Where:
        grid: numpy array (64, 64) int8
        available_actions: list of int (action values)
        state: dict with keys: prev_grid, prev_action, visited_hashes, frame_change_actions,
               tried_actions, level, total_actions, actions_this_level
    """
    # Compile agent code
    agent_ns = {}
    exec(agent_code, {"__builtins__": __builtins__, "np": np, "random": random,
                       "hashlib": hashlib, "defaultdict": __import__("collections").defaultdict,
                       "deque": __import__("collections").deque}, agent_ns)

    if "choose_action" not in agent_ns:
        return {"error": "No choose_action function defined", "rhae": 0.0, "levels": 0, "actions": 0}

    choose_fn = agent_ns["choose_action"]

    env = arcade.make(env_info.game_id)
    frame = env.reset()
    avail_vals = frame.available_actions

    # State passed to agent
    state = {
        "prev_grid": None,
        "prev_action": None,
        "prev_hash": None,
        "visited_hashes": set(),
        "frame_change_actions": {},  # hash -> set of action vals
        "tried_actions": {},  # hash -> set of action vals
        "level": 0,
        "total_actions": 0,
        "actions_this_level": 0,
        "globally_productive": {},  # action_val -> count
    }

    total_actions = 0
    levels_completed = 0
    level_actions = {}
    current_level_start = 0
    t0 = time.time()

    while time.time() - t0 < time_budget and total_actions < max_actions:
        if frame.state in (GS.NOT_PLAYED, GS.GAME_OVER):
            frame = env.step(GA.RESET)
            state["prev_grid"] = None
            state["prev_action"] = None
            state["prev_hash"] = None
            continue

        if frame.state == GS.WIN:
            break

        # Level change
        if frame.levels_completed > levels_completed:
            acts = total_actions - current_level_start
            level_actions[levels_completed] = acts
            levels_completed = frame.levels_completed
            current_level_start = total_actions
            state["level"] = levels_completed
            state["actions_this_level"] = 0
            state["visited_hashes"] = set()
            state["tried_actions"] = {}

        # Get grid
        grid = np.array(frame._frame[0], dtype=np.int8)
        if grid.ndim == 3: grid = grid[-1]

        # Frame hash
        frame_hash = hashlib.md5(grid.tobytes()).hexdigest()
        state["visited_hashes"].add(frame_hash)

        # Update state with frame change info
        if state["prev_hash"] is not None and state["prev_action"] is not None:
            if frame_hash != state["prev_hash"]:
                if state["prev_hash"] not in state["frame_change_actions"]:
                    state["frame_change_actions"][state["prev_hash"]] = set()
                state["frame_change_actions"][state["prev_hash"]].add(state["prev_action"])
                state["globally_productive"][state["prev_action"]] = \
                    state["globally_productive"].get(state["prev_action"], 0) + 1

        state["total_actions"] = total_actions
        state["actions_this_level"] = total_actions - current_level_start

        # Call agent
        try:
            action_val, data = choose_fn(grid, avail_vals, state)
        except Exception as e:
            # Fallback to random
            action_val = random.choice(avail_vals)
            data = None

        if action_val == 6 and data is None:
            nonzero = np.argwhere(grid != 0)
            if len(nonzero) > 0:
                idx = random.randint(0, len(nonzero) - 1)
                data = {"x": int(nonzero[idx][1]), "y": int(nonzero[idx][0])}
            else:
                data = {"x": random.randint(0, 63), "y": random.randint(0, 63)}

        # Track
        if frame_hash not in state["tried_actions"]:
            state["tried_actions"][frame_hash] = set()
        state["tried_actions"][frame_hash].add(action_val)
        state["prev_grid"] = grid
        state["prev_action"] = action_val
        state["prev_hash"] = frame_hash

        action = ACTION_MAP[action_val]
        frame = env.step(action, data=data)
        total_actions += 1

    elapsed = time.time() - t0
    rhae = compute_rhae(level_actions, env_info.baseline_actions)

    return {
        "rhae": rhae,
        "levels": levels_completed,
        "actions": total_actions,
        "level_actions": {str(k): v for k, v in level_actions.items()},
        "elapsed": elapsed,
    }


class ArcAGI3Benchmark(Benchmark):
    """ARC-AGI-3 benchmark: evolve agent strategies for game-playing efficiency."""

    def __init__(self, time_per_game=25, max_actions=800, n_search_games=6, n_test_games=15):
        if not ARC_AVAILABLE:
            raise ImportError("arc-agi package not installed. Run: uv add arc-agi")

        self.arcade = arc_agi.Arcade()
        self.all_envs = sorted(self.arcade.get_environments(),
                               key=lambda e: sum(e.baseline_actions))
        self.time_per_game = time_per_game
        self.max_actions = max_actions
        self.n_search = n_search_games
        self.n_test = n_test_games

    @property
    def name(self) -> str:
        return "arc-agi-3"

    @property
    def objectives(self) -> list[str]:
        return ["+rhae", "+levels", "-actions"]

    def get_search_set(self) -> list[Problem]:
        """Use easiest games for search (faster iteration)."""
        problems = []
        for env in self.all_envs[:self.n_search]:
            problems.append(Problem(
                problem_id=env.game_id,
                input={
                    "game_id": env.game_id,
                    "title": env.title,
                    "tags": env.tags,
                    "baseline_actions": env.baseline_actions,
                    "n_levels": len(env.baseline_actions),
                    "time_budget": self.time_per_game,
                    "max_actions": self.max_actions,
                },
                expected={"target_rhae": 1.0},
                metadata={"human_total": sum(env.baseline_actions)},
            ))
        return problems

    def get_test_set(self) -> list[Problem]:
        """Use remaining games for final evaluation."""
        problems = []
        for env in self.all_envs[self.n_search:self.n_search + self.n_test]:
            problems.append(Problem(
                problem_id=env.game_id,
                input={
                    "game_id": env.game_id,
                    "title": env.title,
                    "tags": env.tags,
                    "baseline_actions": env.baseline_actions,
                    "n_levels": len(env.baseline_actions),
                },
                expected={"target_rhae": 1.0},
                metadata={"human_total": sum(env.baseline_actions)},
            ))
        return problems

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        """Score a harness run on one game."""
        return {
            "rhae": output.get("rhae", 0.0),
            "levels": float(output.get("levels", 0)),
            "actions": float(output.get("actions", self.max_actions)),
        }

    def aggregate_scores(self, per_problem: list[dict[str, float]]) -> dict[str, float]:
        """RHAE-primary aggregation. Actions normalized to [0,1] (lower=better).

        The Pareto optimizer uses these aggregate scores.
        We weight RHAE heavily since it's the competition metric.
        Levels help the proposer understand partial progress.
        Actions are normalized so they're comparable in scale.
        """
        if not per_problem:
            return {"rhae": 0.0, "levels": 0.0, "actions": float(self.max_actions)}
        n = len(per_problem)
        mean_rhae = sum(s["rhae"] for s in per_problem) / n
        mean_levels = sum(s["levels"] for s in per_problem) / n
        # Normalize actions: 0=best (0 actions), 1=worst (max_actions)
        mean_actions = sum(s["actions"] for s in per_problem) / n
        return {
            "rhae": mean_rhae,
            "levels": mean_levels,
            "actions": mean_actions,
        }

    def get_seed_harnesses(self) -> list[str]:
        """Seed strategies (run(problem) format) to start the search."""
        return [
            SEED_RANDOM,
            SEED_SYSTEMATIC,
            SEED_PRODUCTIVE_FIRST,
            SEED_CLICK_OBJECTS,
        ]

    def evaluate_harness(self, harness_code: str, problems: list[Problem]) -> list[dict]:
        """Run a harness on problems and return per-problem scores.

        Harness must define run(problem: dict) -> dict.
        """
        ns: dict = {}
        try:
            exec(compile(harness_code, "<harness>", "exec"), ns)
        except Exception as e:
            return [{"rhae": 0.0, "levels": 0, "actions": self.max_actions,
                     "error": f"compile error: {e}"}] * len(problems)

        if "run" not in ns:
            return [{"rhae": 0.0, "levels": 0, "actions": self.max_actions,
                     "error": "no run() function"}] * len(problems)

        run_fn = ns["run"]
        results = []
        for problem in problems:
            try:
                result = run_fn(problem.input)
                if not isinstance(result, dict):
                    result = {"rhae": 0.0, "levels": 0, "actions": self.max_actions}
                results.append(result)
            except Exception as e:
                results.append({"rhae": 0.0, "levels": 0, "actions": self.max_actions,
                               "error": str(e), "traceback": traceback.format_exc()[-500:]})

        return results


# ─── Shared game-loop header embedded in every harness ───────────────
# NOTE: The comment block inside _GAME_LOOP is INTENTIONALLY inside the harness
# source so the LLM proposer sees it when reading the archive. It explains
# what to modify and why.

_GAME_LOOP = '''
# ═══ ARC-AGI-3 Game-Playing Harness ════════════════════════════════════════
# BENCHMARK: Interactive reasoning games. No text. No language. Pure vision.
# METRIC: RHAE = sum_l( w_l * min(1, human_actions_l / agent_actions_l)^2 )
#   w_l = l+1 (later levels weighted more). Range: 0..1. Higher = better.
#   Score 1.0 = match human efficiency exactly. 0.0 = never complete any level.
#
# YOUR JOB: Improve choose_action(grid, available_actions, state).
#   - grid: 64×64 int8 array (pixel colors 0-15, 0=background)
#   - available_actions: list of int (subset of 1-6 available this frame)
#   - state: dict (see keys below) — you can add NEW keys to persist data
#   Returns: (action_val: int, data: dict|None)
#     action_val 6 = click; data must be {"x": int, "y": int}
#     all other action_vals: data=None
#
# STATE KEYS PROVIDED:
#   tried_actions[frame_hash]       → set of action_vals already tried here
#   frame_change_actions[fh]        → set of action_vals that changed frame from fh
#   globally_productive[action_val] → count of frames this action has changed
#   visited_hashes                  → set of frame hashes seen this level
#   level                           → current level index (0-based)
#   total_actions / actions_this_level → action counters
#
# WINNING STRATEGIES (from leaderboard analysis):
#   1. BFS via game source (needs importlib — not available in harness mode)
#   2. Productive-first: prefer actions that changed frames before
#   3. Object-click: detect colored objects, click centroids systematically
#   4. Keyboard sweep: try non-click actions first (often fewer actions needed)
#   5. Cycle detection + undo: detect stuck states, use undo to backtrack
#   6. Level-to-level transfer: reuse actions from prev level on current
#
# DO NOT TOUCH the game loop or run() — only modify choose_action().
# ════════════════════════════════════════════════════════════════════════════
import arc_agi, hashlib, random, time, numpy as np
from collections import defaultdict
from arcengine.enums import GameAction as GA, GameState as GS

ACTION_MAP = {a.value: a for a in GA}

def _compute_rhae(level_actions, baseline):
    if not level_actions: return 0.0
    n = len(baseline); tw = n*(n+1)/2; s = 0.0
    for l in range(n):
        if l in level_actions:
            s += (l+1) * min(1.0, baseline[l]/max(level_actions[l],1))**2
    return s/tw

def _click_data(grid):
    nz = np.argwhere(grid != 0)
    if len(nz):
        i = random.randint(0, len(nz)-1)
        return {"x": int(nz[i][1]), "y": int(nz[i][0])}
    return {"x": random.randint(0,63), "y": random.randint(0,63)}

def run(problem):
    game_id = problem["game_id"]
    baseline = problem["baseline_actions"]
    time_budget = problem.get("time_budget", 25)   # seconds per game (25s for search, override with problem["time_budget"])
    max_actions = problem.get("max_actions", 800)

    # Reuse Arcade across calls via function attribute
    if not hasattr(run, "_arcade"):
        run._arcade = arc_agi.Arcade()
        run._envs = {e.game_id: e for e in run._arcade.get_environments()}
    if game_id not in run._envs:
        return {"rhae": 0.0, "levels": 0, "actions": 0}

    env = run._arcade.make(game_id)
    frame = env.reset()
    avail_vals = frame.available_actions

    state = {
        "prev_hash": None, "prev_action": None, "prev_grid": None,
        "visited_hashes": set(),
        "frame_change_actions": {},   # hash -> set of action_vals that changed frame
        "tried_actions": {},          # hash -> set of tried action_vals
        "globally_productive": {},    # action_val -> count of times it changed a frame
        "level": 0, "total_actions": 0, "actions_this_level": 0,
    }

    total_actions = 0; levels_done = 0; level_actions = {}; lvl_start = 0
    t0 = time.time()

    while time.time()-t0 < time_budget and total_actions < max_actions:
        if frame.state in (GS.NOT_PLAYED, GS.GAME_OVER):
            frame = env.step(GA.RESET)
            state.update(prev_hash=None, prev_action=None, prev_grid=None)
            continue
        if frame.state == GS.WIN:
            break
        if frame.levels_completed > levels_done:
            level_actions[levels_done] = total_actions - lvl_start
            levels_done = frame.levels_completed; lvl_start = total_actions
            state.update(level=levels_done, actions_this_level=0,
                         visited_hashes=set(), tried_actions={})

        grid = np.array(frame._frame[0], dtype=np.int8)
        if grid.ndim == 3: grid = grid[-1]
        fh = hashlib.md5(grid.tobytes()).hexdigest()
        state["visited_hashes"].add(fh)

        if state["prev_hash"] and state["prev_action"] is not None and fh != state["prev_hash"]:
            state["frame_change_actions"].setdefault(state["prev_hash"], set()).add(state["prev_action"])
            state["globally_productive"][state["prev_action"]] = state["globally_productive"].get(state["prev_action"],0)+1

        state["total_actions"] = total_actions
        state["actions_this_level"] = total_actions - lvl_start

        try:
            action_val, data = choose_action(grid, avail_vals, state)
        except Exception:
            action_val = random.choice(avail_vals); data = None

        if action_val == 6 and data is None:
            data = _click_data(grid)

        state["tried_actions"].setdefault(fh, set()).add(action_val)
        state["prev_hash"] = fh; state["prev_action"] = action_val; state["prev_grid"] = grid

        frame = env.step(ACTION_MAP[action_val], data=data)
        total_actions += 1

    rhae = _compute_rhae(level_actions, baseline)
    return {
        "rhae": rhae,
        "levels": levels_done,
        "actions": total_actions,
        # Extra context for the proposer to understand failures:
        "game_title": problem.get("title", "?"),
        "n_levels": problem.get("n_levels", 0),
        "baseline_total": sum(baseline),
        "efficiency": rhae / max(levels_done, 1) if levels_done else 0.0,
        "per_level_actions": {str(k): v for k, v in level_actions.items()},
    }
'''

# ─── Seed Harnesses (run(problem) format) ────────────────────────────
# Each harness = _GAME_LOOP + a choose_action() implementation.
# The proposer modifies choose_action() to improve RHAE.

SEED_RANDOM = _GAME_LOOP + '''
def choose_action(grid, available_actions, state):
    """Pure random — baseline lower bound."""
    action = random.choice(available_actions)
    return action, None
'''

SEED_SYSTEMATIC = _GAME_LOOP + '''
def choose_action(grid, available_actions, state):
    """Systematic: exhaust untried actions before repeating."""
    fh = hashlib.md5(grid.tobytes()).hexdigest()
    tried = state["tried_actions"].get(fh, set())
    untried = [a for a in available_actions if a not in tried]
    action = untried[0] if untried else random.choice(available_actions)
    return action, None
'''

SEED_PRODUCTIVE_FIRST = _GAME_LOOP + '''
def choose_action(grid, available_actions, state):
    """Prefer globally productive actions; fall back to untried then random."""
    fh = hashlib.md5(grid.tobytes()).hexdigest()
    tried = state["tried_actions"].get(fh, set())
    untried = [a for a in available_actions if a not in tried]

    if untried:
        scored = sorted(untried, key=lambda a: -state["globally_productive"].get(a, 0))
        action = scored[0]
    else:
        prod = state["frame_change_actions"].get(fh, set())
        candidates = [a for a in available_actions if a in prod] or available_actions
        action = random.choice(candidates)

    data = None
    if action == 6:
        colors = np.unique(grid[grid != 0])
        if len(colors):
            color = random.choice(colors)
            px = np.argwhere(grid == int(color))
            cy, cx = px.mean(axis=0).astype(int)
            data = {"x": int(cx), "y": int(cy)}
    return action, data
'''

SEED_CLICK_OBJECTS = _GAME_LOOP + '''
def choose_action(grid, available_actions, state):
    """Try all non-click actions first; then systematically click object centroids."""
    fh = hashlib.md5(grid.tobytes()).hexdigest()
    tried = state["tried_actions"].get(fh, set())

    non_click = [a for a in available_actions if a != 6 and a not in tried]
    if non_click:
        return non_click[0], None

    if 6 in available_actions:
        targets = []
        for color in np.unique(grid[grid != 0]):
            px = np.argwhere(grid == int(color))
            if len(px) < 2: continue
            cy, cx = px.mean(axis=0).astype(int)
            targets += [(int(cy),int(cx)),
                        (int(px[:,0].min()),int(px[:,1].min())),
                        (int(px[:,0].max()),int(px[:,1].max()))]
        key = f"cidx_{fh}"
        idx = state.get(key, 0)
        if targets and idx < len(targets):
            state[key] = idx + 1
            y, x = targets[idx]
            return 6, {"x": min(63,max(0,x)), "y": min(63,max(0,y))}
        nz = np.argwhere(grid != 0)
        if len(nz):
            i = random.randint(0,len(nz)-1)
            return 6, {"x": int(nz[i][1]), "y": int(nz[i][0])}
        return 6, {"x": random.randint(0,63), "y": random.randint(0,63)}

    return random.choice(available_actions), None
'''

# ─── Register benchmark ───────────────────────────────────────────────
register_benchmark("arc-agi-3", ArcAGI3Benchmark)
