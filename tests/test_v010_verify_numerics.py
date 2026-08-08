"""v0.10 — `kaos eval verify-numerics` acceptance suite.

Encodes the pre-registered gates in demo_verify_numerics_bench/ACCEPTANCE.md.
Thresholds here are frozen; softening them post-hoc is the retune-and-rerun the
discipline bans. A numeric verifier that blesses a fabrication is worse than
none, so G-FALSIFY (no fabricated number ever 'verified') is load-bearing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaos.eval.verify_numerics import (
    build_corpus,
    scan_claims,
    verify_text,
)


# ── extraction / normalization ───────────────────────────────────────

class TestExtraction:
    def _kinds(self, text):
        return {(raw, kind) for raw, _v, kind, _c, _e in scan_claims(text)}

    def test_percent_and_pp(self):
        vals = {raw: v for raw, v, k, _c, _e in scan_claims("gained 85.4% and +10.0pp then +13.3 pp")}
        assert vals["85.4%"] == 85.4
        assert vals["+10.0pp"] == 10.0
        assert vals["+13.3 pp"] == 13.3

    def test_signed_decimal(self):
        vals = {raw: v for raw, v, k, _c, _e in scan_claims("separation -0.062 vs +0.653")}
        assert vals["-0.062"] == pytest.approx(-0.062)
        assert vals["+0.653"] == pytest.approx(0.653)

    def test_units(self):
        got = {raw: (v, k) for raw, v, k, _c, _e in scan_claims("9.2ms p95, 15µs, 1,118 ops/s, 122.8× faster")}
        assert got["9.2ms"] == (9.2, "unit")
        assert got["15µs"] == (15.0, "unit")
        assert got["122.8×"] == (122.8, "unit")

    def test_fraction(self):
        claims = [c for c in scan_claims("flagged 97/109 agents")]
        raw, v, kind, _c, extra = claims[0]
        assert raw == "97/109" and kind == "fraction" and extra == (97.0, 109.0)

    def test_thousands_and_bignum(self):
        vals = {raw: v for raw, v, k, _c, _e in scan_claims("1,639 tool calls across 1405 runs")}
        assert vals["1,639"] == 1639.0
        assert vals["1405"] == 1405.0

    def test_unit_does_not_eat_plural_nouns(self):
        # "10 seeds" must NOT parse as 10 seconds; "3 states" not 3 seconds
        raws = {raw for raw, _v, _k, _c, _e in scan_claims("ran 10 seeds over 3 states")}
        assert "10 s" not in raws and "3 s" not in raws
        # neither 10 nor 3 is measurement-shaped, so nothing is claimed
        assert not scan_claims("ran 10 seeds over 3 states")


class TestAllowlist:
    @pytest.mark.parametrize("text", [
        "released v0.9.2 today",
        "on 2026-08-08 at noon",
        "back in 2026 we shipped",
        "see search.py:449 for the bug",
        "https://doi.org/10.5281/zenodo.21688617",
        "commit add0c25 landed",
        "reached #39 on the board",
        "schema v9 has 26 tables",   # 'v9' allowlisted; 26 is 2-digit -> not claimed
    ])
    def test_allowlisted_yields_no_claims(self, text):
        assert scan_claims(text) == [], f"allowlist leak in: {text!r}"

    def test_doi_digits_not_claimed(self):
        # the long zenodo id must be masked, not surface as a bignum claim
        raws = {raw for raw, *_ in scan_claims("doi:10.5281/zenodo.21688617")}
        assert "21688617" not in raws


# ── matching: verified / unverifiable ────────────────────────────────

class TestMatching:
    def test_exact_decimal_verified(self):
        r = verify_text("separation was -0.062", corpus={-0.062, 0.653})
        assert r.ok and r.verified[0].raw == "-0.062"

    def test_percent_scales_to_fraction(self):
        # text says 85.4%, corpus stored it as 0.854
        r = verify_text("anchored 85.4% of tasks", corpus={0.854})
        assert r.ok and r.verified[0].matched_value == pytest.approx(0.854)

    def test_fraction_verified_iff_both_terms_present(self):
        assert verify_text("97/109 agents", corpus={97.0, 109.0}).ok
        assert not verify_text("97/109 agents", corpus={97.0}).ok  # 109 missing

    def test_unit_value_matches_bare_corpus_number(self):
        r = verify_text("9.2ms p95 latency", corpus={9.2})
        assert r.ok

    def test_fabricated_is_unverifiable(self):
        r = verify_text("separation was -0.4271", corpus={-0.062, 0.653, 0.9})
        assert not r.ok and r.unverifiable[0].raw == "-0.4271"


# ── G-FALSIFY (load-bearing) ─────────────────────────────────────────

class TestFalsify:
    def test_injected_fabrication_flagged(self):
        real = "FULL 1.000, B1 0.188, separation -0.062, DET +0.653"
        corpus = {1.000, 0.188, -0.062, 0.653}
        assert verify_text(real, corpus=corpus).ok  # the real report traces clean
        tampered = real + "\nand a fabricated 0.7419 gain"
        r = verify_text(tampered, corpus=corpus)
        assert not r.ok
        assert any(c.raw == "0.7419" for c in r.unverifiable)

    def test_no_fabricated_number_ever_verified(self):
        # a value absent from a nonempty corpus must never be reported verified
        corpus = {0.1, 0.2, 0.3, 12.5, 1639.0}
        r = verify_text("the model hit 0.8888 accuracy and 44.44pp lift", corpus=corpus)
        assert all(c.status == "unverifiable" for c in r.unverifiable)
        assert not any(c.value in (0.8888, 44.44) for c in r.verified)

    def test_empty_corpus_verifies_nothing(self):
        r = verify_text("0.5 and 9.2ms and 90.0%", corpus=set())
        assert not r.ok and len(r.unverifiable) == 3

    def test_typographic_minus_is_caught(self):
        # a fabrication written with U+2212 (−) must not slip past unflagged
        r = verify_text("separation was −0.4271 here", corpus={0.062})
        assert not r.ok and r.unverifiable[0].value == pytest.approx(-0.4271)
        # and a real unicode-minus value still verifies
        assert verify_text("sep −0.062", corpus={-0.062}).ok


# ── G-RECALL: hand-labeled fixture ───────────────────────────────────

_FIXTURE = """
The probe scored 1.000 on the constructed slice against a 0.188 baseline.
Median reuse landed at 10.000, and pairing precision was 0.900.
A rogue claim of 0.6666 slipped in, plus a bogus 77.7pp and a fake 3.1416 constant.
Released v0.9.2 on 2026-08-08 (see search.py:449); reached #39 of ~1,700.
"""
_FIXTURE_CORPUS = {1.000, 0.188, 10.000, 0.900}
_PLANTED_UNVERIFIABLE = {"0.6666", "77.7pp", "3.1416"}


class TestRecall:
    def test_all_planted_unverifiable_flagged(self):
        r = verify_text(_FIXTURE, corpus=_FIXTURE_CORPUS)
        flagged = {c.raw for c in r.unverifiable}
        assert _PLANTED_UNVERIFIABLE <= flagged, f"missed: {_PLANTED_UNVERIFIABLE - flagged}"

    def test_allowlisted_not_flagged(self):
        r = verify_text(_FIXTURE, corpus=_FIXTURE_CORPUS)
        raws = {c.raw for c in r.unverifiable} | {c.raw for c in r.verified}
        for benign in ("0.9.2", "2026-08-08", "449", "39", "1,700"):
            assert benign not in raws


# ── G-PRECISION: numbers that DO trace ───────────────────────────────

class TestPrecision:
    def test_false_unverifiable_and_false_verified_rates(self):
        # 10 numbers that all genuinely trace to the corpus
        traced = [1.000, 0.188, 10.000, 0.900, 0.653, 9.2, 15.0, 1639.0, 0.854, 122.8]
        corpus = set(traced) | {0.854}
        text = ("results: 1.000, 0.188, 10.000, 0.900, +0.653, 9.2ms, 15µs, "
                "1,639 calls, 85.4%, 122.8×")
        r = verify_text(text, corpus=corpus)
        n = len(r.verified) + len(r.unverifiable)
        false_unverifiable = len(r.unverifiable) / n
        assert false_unverifiable < 0.20, f"{false_unverifiable:.2%} false-unverifiable"
        # false-verified: none of these are fabrications, so hard to test directly;
        # instead assert a fabrication mixed in is NOT verified (<5% => 0 tolerated)
        r2 = verify_text(text + " and fake 0.31337", corpus=corpus)
        assert all(c.raw != "0.31337" for c in r2.verified)


# ── G-OFFLINE: deterministic, no network ─────────────────────────────

class TestOffline:
    def test_deterministic_partitions(self):
        text = "0.062, 65.3pp, 9.2ms, fabricated 0.999999"
        corpus = {0.062, 65.3, 9.2}
        a = verify_text(text, corpus=corpus).to_dict()
        b = verify_text(text, corpus=corpus).to_dict()
        assert a == b

    def test_corpus_from_db_and_results(self, tmp_path):
        # experiments journal
        from kaos.experiments import ExperimentStore
        db = tmp_path / "kaos.db"
        with ExperimentStore(str(db)) as store:
            store.log_run(name="p", family="probe", arms={"acc": {"best": 0.777}})
        # results.json
        rp = tmp_path / "results.json"
        rp.write_text(json.dumps({"separation": -0.062, "flag_rate": 0.9}))
        corpus = build_corpus(str(db), [str(rp)])
        assert 0.777 in corpus and -0.062 in corpus and 0.9 in corpus
        # a claim tracing to each source verifies
        assert verify_text("acc 0.777 and sep -0.062", db_path=str(db),
                           results_paths=[str(rp)]).ok


# ── CLI smoke ────────────────────────────────────────────────────────

class TestCLI:
    def test_exit_nonzero_on_unverifiable(self, tmp_path):
        from click.testing import CliRunner
        from kaos.cli.main import cli
        art = tmp_path / "blog.md"
        art.write_text("we measured 0.4271 improvement")  # nothing in empty db
        db = tmp_path / "kaos.db"
        from kaos.experiments import ExperimentStore
        ExperimentStore(str(db)).close()  # create empty journal
        res = CliRunner().invoke(cli, ["eval", "verify-numerics", str(art), "--db", str(db)])
        assert res.exit_code == 1

    def test_exit_zero_when_clean(self, tmp_path):
        from click.testing import CliRunner
        from kaos.cli.main import cli
        art = tmp_path / "post.md"
        art.write_text("released v0.9.2 on 2026-08-08, see search.py:449")  # all allowlisted
        db = tmp_path / "kaos.db"
        from kaos.experiments import ExperimentStore
        ExperimentStore(str(db)).close()
        res = CliRunner().invoke(cli, ["--json", "eval", "verify-numerics", str(art), "--db", str(db)])
        assert res.exit_code == 0
        assert json.loads(res.output)["ok"] is True
