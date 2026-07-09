"""v0.9.2 Tier-0 — eval-harness integrity P0s (RED-FIRST).

The framework's product is its verdicts; the instrument that renders them
had holes the v0.10 panel verified in source (candidate eval-harness-integrity):
  - compute_verdict returns ACCEPT for a probe with zero kill-gates
  - the blind-judge kappa is `jq.correct == jq.correct` (always 1.0 — the
    kappa VOID gate is dead code)
  - Probe.verify() crashes on the results.json shapes run() actually produces
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaos.eval.harness import (
    ArmResults, GateOutcome, Probe, QueryResult, compute_verdict, sha256_file,
)
from kaos.eval.harness.judge import JudgedQuery, judge_arm


def _g(gate, passed, kill):
    return GateOutcome(gate=gate, name=gate, passed=passed, kill=kill, detail="")


# ── empty kill-gate list must VOID, not ACCEPT ───────────────────────


class TestEmptyGatesVoid:
    def test_zero_kill_gates_is_void_not_accept(self):
        # A probe that registers no kill-gates must NOT auto-pass.
        v = compute_verdict([], judge_kappa=1.0)
        assert v.startswith("VOID"), f"expected VOID, got {v!r}"

    def test_only_sanity_gates_no_kill_is_void(self):
        v = compute_verdict([_g("G0", True, False)], judge_kappa=1.0)
        assert v.startswith("VOID"), f"expected VOID, got {v!r}"

    def test_at_least_one_kill_gate_all_pass_is_accept(self):
        v = compute_verdict([_g("G1", True, True)], judge_kappa=1.0)
        assert v == "ACCEPT"

    def test_failed_kill_still_rejects(self):
        v = compute_verdict([_g("G1", False, True)], judge_kappa=1.0)
        assert v.startswith("REJECT")


# ── kappa must reflect real judge disagreement ───────────────────────


class TestKappaIsReal:
    def _stream(self, indep):
        # 20 items; independent-label list `indep` overrides agreement.
        return [
            JudgedQuery(
                qid=f"q{i}", qclass="c", split="in_dist",
                correct=True, extras={"independent": indep[i]},
            )
            for i in range(len(indep))
        ]

    def test_full_agreement_yields_high_kappa(self):
        judged = self._stream([True] * 20)
        _, kappa = judge_arm("arm", judged)
        assert kappa is None or kappa >= 0.85

    def test_disagreeing_judge_lowers_kappa(self):
        # Mechanical label is True for all; independent labeler disagrees on
        # half. A real kappa MUST drop below the 0.85 VOID threshold — the
        # pre-fix tautology (x == x) made this impossible.
        judged = self._stream([True] * 10 + [False] * 10)
        _, kappa = judge_arm("arm", judged)
        assert kappa is not None, "mechanical-only kappa must be exempt (None), not a silent 1.0"
        assert kappa < 0.85, f"disagreement should lower kappa, got {kappa}"

    def test_disagreement_voids_the_verdict(self):
        judged = self._stream([True] * 4 + [False] * 16)
        _, kappa = judge_arm("arm", judged)
        v = compute_verdict([_g("G1", True, True)], judge_kappa=kappa)
        assert v.startswith("VOID")

    def test_mechanical_only_probe_is_kappa_exempt(self):
        # No independent labels -> kappa is explicitly exempt (None), NOT a
        # tautological 1.0, and compute_verdict does not VOID on it.
        judged = [
            JudgedQuery(qid=f"q{i}", qclass="c", split="in_dist", correct=True)
            for i in range(10)
        ]
        _, kappa = judge_arm("arm", judged)
        assert kappa is None
        v = compute_verdict([_g("G1", True, True)], judge_kappa=kappa)
        assert v == "ACCEPT"


# ── Probe.verify() must not crash on real results.json shapes ────────


class _MiniProbe(Probe):
    """Minimal probe whose gate reads per_query so verify() must reconstruct it."""
    lock_path = ""          # set per-instance in the test
    known_sha256: dict = {}

    def arms(self):
        return ["B0", "FULL"]

    def gates(self, arms):
        full = arms["FULL"].acc({"c"})
        b0 = arms["B0"].acc({"c"})
        return [GateOutcome("G1", "beats", (full - b0) >= 0.1, True,
                            f"FULL={full} B0={b0}")]

    def run(self, *, out_dir, **kw):
        arms = {
            "B0": ArmResults("B0", [QueryResult(f"b{i}", "c", i < 2) for i in range(10)]),
            "FULL": ArmResults("FULL", [QueryResult(f"f{i}", "c", i < 8) for i in range(10)]),
        }
        outcomes = self.gates(arms)
        verdict = compute_verdict(outcomes, judge_kappa=None)
        result = {
            "verdict": verdict, "judge_kappa": None,
            "arms": {
                n: {
                    "acc": a.acc({"c"}),
                    "per_query": [
                        {"qid": q.qid, "qclass": q.qclass, "correct": q.correct,
                         "split": q.split, "extras": q.extras}
                        for q in a.per_query
                    ],
                } for n, a in arms.items()
            },
            "gates": [{"gate": g.gate, "passed": g.passed, "kill": g.kill,
                       "detail": g.detail} for g in outcomes],
        }
        Path(out_dir, "results.json").write_text(json.dumps(result, indent=2))
        return result


def _mini(tmp_path: Path) -> _MiniProbe:
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"name": "mini"}))
    h = sha256_file(lock)
    _MiniProbe.lock_path = str(lock)
    _MiniProbe.known_sha256 = {h: "v1"}
    return _MiniProbe()


class TestVerifyDoesNotCrash:
    def test_verify_reconstructs_from_persisted_per_query(self, tmp_path: Path):
        p = _mini(tmp_path)
        run_result = p.run(out_dir=tmp_path)
        verdict = p.verify(tmp_path / "results.json")
        assert verdict == run_result["verdict"]  # ACCEPT, recomputed at HEAD

    def test_verify_short_circuits_on_void_results(self, tmp_path: Path):
        # A VOID results.json (empty arms — the shape the action-realization
        # probe writes when the workload is insufficient) must NOT KeyError.
        p = _mini(tmp_path)
        void = {"verdict": "VOID#1: insufficient organic sample",
                "judge_kappa": 1.0, "arms": {}, "gates": []}
        (tmp_path / "results.json").write_text(json.dumps(void))
        verdict = p.verify(tmp_path / "results.json")
        assert verdict.startswith("VOID")
