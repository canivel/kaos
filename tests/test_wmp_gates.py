"""WMP probe (demo_wmp_bench) — gate mechanics + lock discipline."""

from __future__ import annotations

import json

import pytest

from demo_wmp_bench.gates import (
    KNOWN_LOCK_SHA256, LOCK_PATH, WMPStats, compute_gates, falsify, load,
)
from kaos.eval.harness.manifest import LockTamperError, load_lock
from kaos.eval.harness.verdict import compute_verdict


def mk(b0, full, l1, fc=2000.0, bc=1500.0):
    return WMPStats(
        accuracy={"B0": {"text_classify": b0, "math_rag": b0},
                  "FULL": {"text_classify": full, "math_rag": full},
                  "L1": {"text_classify": l1, "math_rag": l1}},
        chars={"B0": [bc] * 9, "FULL": [fc] * 9, "L1": [fc] * 9})


class TestGates:
    def test_accept_shape(self):
        s = mk([0.5, 0.55, 0.5], [0.7, 0.75, 0.72], [0.52, 0.55, 0.5])
        assert compute_verdict(compute_gates(s), judge_kappa=None) == "ACCEPT"

    def test_null_lift_rejects_g1(self):
        s = mk([0.5, 0.55, 0.5], [0.52, 0.5, 0.55], [0.5, 0.52, 0.5])
        v = compute_verdict(compute_gates(s), judge_kappa=None)
        assert v.startswith("REJECT") and "G1" in v

    def test_placebo_rejects_g2(self):
        s = mk([0.5, 0.5, 0.5], [0.7, 0.72, 0.7], [0.69, 0.71, 0.7])
        v = compute_verdict(compute_gates(s), judge_kappa=None)
        assert v.startswith("REJECT") and "G2" in v and "G1" not in v

    def test_cost_blowout_rejects_g3(self):
        s = mk([0.5, 0.5, 0.5], [0.7, 0.72, 0.7], [0.5, 0.5, 0.5],
               fc=4000.0, bc=1500.0)
        v = compute_verdict(compute_gates(s), judge_kappa=None)
        assert v.startswith("REJECT") and "G3" in v

    def test_incomplete_cells_void(self):
        s = mk([0.5, 0.5], [0.7, 0.7, 0.7], [0.5, 0.5, 0.5])
        assert compute_verdict(compute_gates(s), judge_kappa=None).startswith("VOID")

    def test_falsification_kills_inert_wiki(self):
        s = mk([0.5, 0.55, 0.5], [0.7, 0.75, 0.72], [0.52, 0.55, 0.5])
        can_kill, detail = falsify(s)
        assert can_kill, detail


class TestLockDiscipline:
    def test_registered_lock_loads(self):
        assert load()["name"] == "wmp-probe-v1"

    def test_edited_lock_refused(self, tmp_path):
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        data["kill_gates"]["G1"]["predicate"] = "always pass"   # the retune
        tampered = tmp_path / "ISA.lock.json"
        tampered.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(LockTamperError):
            load_lock(tampered, KNOWN_LOCK_SHA256)
