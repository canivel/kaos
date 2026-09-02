"""Pre-registered latency probe for the Claude Code hooks (M1 / G4.1b).

    uv run python benchmarks/cc_hook_latency/run_cc_hook_latency.py [--trials 50] [--output PATH]

Refuses to run if preregistration.json was edited after locking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
LOCK = HERE / "preregistration.json"
KNOWN_LOCK_SHA256 = {
    # v1: REJECTed on G3 — seed never matched the hint (instrument defect); result kept
    "2eff0e07a8e2f09f8ede1fd66d2f4b66dce626eedc1ace2f82512bde1c286383": "v1",
    "42f4a278a1ca5018c013cf231ab5eb117cd7d3d7a76a6f544a0e98343a3b2418": "v2",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed(db_path: str, agents: int = 10_000, per_agent: int = 5) -> None:
    from kaos._ids import new_ulid
    from kaos.core import Kaos
    rng = random.Random(7)
    db = Kaos(db_path)
    conn = db.conn
    ids = [new_ulid() for _ in range(agents)]
    conn.executemany(
        "INSERT INTO agents (agent_id, name, status) VALUES (?, ?, 'completed')",
        [(a, f"agent-{i}") for i, a in enumerate(ids)],
    )
    words = ["payment", "retry", "webhook", "timeout", "idempotency", "cache", "auth",
             "migration", "queue", "deploy", "index", "billing", "session", "token", "rate"]
    rows = []
    for a in ids:
        for _ in range(per_agent):
            body = " ".join(rng.choice(words) for _ in range(12)) + " fix applied"
            if rng.random() < 0.01:
                body = "payments service: " + body
            rows.append((a, "insight", body))
    conn.executemany("INSERT INTO memory (agent_id, type, content) VALUES (?, ?, ?)", rows)
    conn.commit()
    db.close()


def trial(cmd: str, payload: dict, db: str, env: dict) -> tuple[float, int, str]:
    t0 = time.perf_counter()
    p = subprocess.run(["kaos-hook", cmd, "--db", db], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=30)
    return (time.perf_counter() - t0) * 1000, p.returncode, p.stdout


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--output", default=str(HERE / "results" / "latest.json"))
    args = ap.parse_args()

    lock_sha = _sha(LOCK)
    if lock_sha not in KNOWN_LOCK_SHA256:
        print(f"REFUSING: preregistration.json sha256 {lock_sha} is not a known lock", file=sys.stderr)
        return 2
    if not shutil.which("kaos-hook"):
        verdict = "VOID: kaos-hook not on PATH"
        _write(args.output, {"verdict": verdict, "lock_sha256": lock_sha})
        print(verdict)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="cc-hook-lat-"))
    db = str(tmp / "kaos.db")
    home = tmp / "home"
    home.mkdir()
    env = dict(os.environ, KAOS_HOME=str(home), KAOS_HOOK_PROMPT_INJECT="1", KAOS_HOOK_NO_CONSOLIDATE="1")
    try:
        t0 = time.perf_counter()
        seed(db)
        seed_s = time.perf_counter() - t0
        cwd = "/home/dev/payments-service"
        ps = {"session_id": "probe-session", "cwd": cwd, "hook_event_name": "SessionStart",
              "session_start_reason": "startup", "transcript_path": "/tmp/t.jsonl"}
        pp = {"session_id": "probe-session", "cwd": cwd, "hook_event_name": "UserPromptSubmit",
              "user_message": "the payment webhook double charges on retry after a timeout — fix with an idempotency key"}
        for _ in range(5):
            trial("session-start", ps, db, env)
            trial("prompt", pp, db, env)
        s_lat, p_lat, codes, injected = [], [], [], 0
        for _ in range(args.trials):
            ms, rc, out = trial("session-start", ps, db, env)
            s_lat.append(ms); codes.append(rc); injected += int("<kaos-memory" in out)
            ms, rc, out = trial("prompt", pp, db, env)
            p_lat.append(ms); codes.append(rc)
        g1 = p95(s_lat) <= 400
        g2 = p95(p_lat) <= 200
        g3 = all(c == 0 for c in codes) and injected == args.trials
        if g1 and g2 and g3:
            verdict = "ACCEPT"
        elif not g1 or not g3:
            verdict = "REJECT: G1 session-start budget" if not g1 else "REJECT: G3 hook failed or no injection"
        else:
            verdict = "REJECT:prompt — UserPromptSubmit stays off by default"
        res = {
            "benchmark": f"cc-hook-latency-{KNOWN_LOCK_SHA256[lock_sha]}", "verdict": verdict, "lock_sha256": lock_sha,
            "trials": args.trials, "seed_s": round(seed_s, 2),
            "session_start_ms": {"p50": round(sorted(s_lat)[len(s_lat)//2], 1), "p95": round(p95(s_lat), 1), "min": round(min(s_lat), 1)},
            "prompt_ms": {"p50": round(sorted(p_lat)[len(p_lat)//2], 1), "p95": round(p95(p_lat), 1), "min": round(min(p_lat), 1)},
            "gates": {"G1_session_start": g1, "G2_prompt": g2, "G3_never_blocks": g3},
            "injected_blocks": injected,
            "machine": {"platform": platform.platform(), "python": platform.python_version(),
                        "db_dir": str(tmp), "note": "WSL2 /tmp on this dev box; CI runner numbers will differ"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write(args.output, res)
        print(json.dumps(res, indent=2))
        return 0 if verdict == "ACCEPT" else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
