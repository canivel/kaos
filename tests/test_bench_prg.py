"""PRG bench: lock integrity + runner smoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRG = ROOT / "benchmarks" / "prg"
sys.path.insert(0, str(PRG))

import run_prg  # noqa: E402

from kaos.eval.harness import LockTamperError, load_lock, sha256_file  # noqa: E402


def test_lock_hash_is_registered():
    assert sha256_file(PRG / "preregistration.json") in run_prg.KNOWN_LOCK_SHA256


def test_tampered_lock_is_refused(tmp_path):
    lock = json.loads((PRG / "preregistration.json").read_text())
    lock["gates"]["VOID"] = "n_pairs < 1"  # move the goalposts
    p = tmp_path / "preregistration.json"
    p.write_text(json.dumps(lock))
    with pytest.raises(LockTamperError):
        load_lock(p, run_prg.KNOWN_LOCK_SHA256)


def test_pairs_file_has_fifty_unique_pairs():
    pairs = json.loads((PRG / "pairs.json").read_text())["pairs"]
    assert len(pairs) == 50
    assert len({p["id"] for p in pairs}) == 50
    assert all(p["stored_phrase"] and p["paraphrase_query"] for p in pairs)


def test_runner_smoke_on_five_pairs():
    pairs = json.loads((PRG / "pairs.json").read_text())["pairs"][:5]
    conditions = run_prg.run(pairs)
    control = conditions["verbatim/and/bm25"]
    assert control["n"] == 5
    assert control["miss_rate"] == 0.0, control["missed_ids"]
    assert "paraphrase/and/bm25" in conditions
    assert run_prg.sanitize("Double-Charge on the retry!", "and") == "double charge retry"
    assert run_prg.sanitize("cache miss cache", "or") == "cache OR miss"
