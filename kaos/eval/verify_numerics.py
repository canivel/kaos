"""verify-numerics — trace numeric claims in generated text to recorded measurements.

Verification infrastructure (not a performance mechanism): given a text artifact
and a corpus of recorded measurements (the experiments journal + results.json
files), classify every measurement-shaped number as verified / unverifiable /
allowlisted. Pure regex + exact-value lookup — no embeddings, no LLM, offline,
deterministic. Acceptance gates are pre-registered in
``demo_verify_numerics_bench/ACCEPTANCE.md``.

Design bias: PRECISION over recall on the verified side. A fabricated number must
never be reported ``verified`` (G-FALSIFY). Matching is therefore exact-value with
a tight relative tolerance, and bare small integers with no measurement context
are treated as ambiguous (skipped), not claimed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# ── allowlist: patterns that are provably not measurement claims ──────
# Applied by MASKING them out of the text before any number extraction, so their
# internal digits can never be mistaken for a claim.
_ALLOWLIST = [
    r"v?\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)*",   # semver / dotted versions
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?",  # ISO date/datetime
    r"\b(?:19|20)\d{2}\b",                     # bare years 1900-2099
    r"[\w./\\-]+\.(?:py|md|json|yaml|yml|sql|txt|toml|html|tex|js|ts):\d+",  # file:line
    r"https?://\S+",                            # URLs
    r"\b[0-9a-f]{7,40}\b",                      # hex / commit shas
    r"[#§]\s?\d+",                              # ordinals / ranks / issue / section nums
    r"\bv\d+\b",                                # bare version tags like v9, v0
    r"\bschema\s+v\d+\b",                        # schema v9
]
_ALLOWLIST_RE = re.compile("|".join(f"(?:{p})" for p in _ALLOWLIST), re.IGNORECASE)

# ── measurement-shaped claim tokens (order matters: most specific first) ──
# Each returns (value, kind). Percentages/pp scale to the same units the corpus
# stores them in (raw and /100 are both tried at match time).
# Units ordered longest-first so 'ops/s' and 'ms' win over 's'. The trailing
# (?![A-Za-z]) guard stops '10 seeds' matching as '10 s' (seconds).
_UNIT = r"(?:ops/s|ms|µs|us|ns|MB|KB|GB|pp|×|x|s|k|K|M)"
_CLAIM_PATTERNS = [
    ("fraction", re.compile(r"(?<![\d./])(\d{1,7})\s*/\s*(\d{1,7})(?![\d./])")),
    ("percent",  re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(?:%|pp)(?![A-Za-z])")),
    ("unit",     re.compile(rf"([+-]?\d+(?:\.\d+)?)\s*{_UNIT}(?![A-Za-z])")),
    ("decimal",  re.compile(r"(?<![\d.])([+-]?\d+\.\d+)(?![\d.])")),
    ("bignum",   re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{4,})(?![\d.,])")),
]

_TOL = 1e-6  # relative tolerance for exact-value match

# Typographic characters that appear in real reports must be folded to ASCII
# before extraction, or a fabricated "−0.42" (U+2212 minus) slips past unflagged.
_UNICODE_FOLD = {
    "−": "-",   # minus sign  −
    "–": "-",   # en dash (numeric ranges/negatives in prose)
    " ": " ",   # non-breaking space
    " ": " ",   # narrow no-break space (common before units)
}


def _normalize(text: str) -> str:
    for k, v in _UNICODE_FOLD.items():
        text = text.replace(k, v)
    return text


@dataclass
class NumericClaim:
    raw: str
    value: float
    kind: str            # fraction|percent|unit|decimal|bignum
    context: str
    status: str          # verified|unverifiable
    matched_value: float | None = None

    def to_dict(self) -> dict:
        return vars(self)


@dataclass
class VerifyReport:
    verified: list[NumericClaim] = field(default_factory=list)
    unverifiable: list[NumericClaim] = field(default_factory=list)
    corpus_size: int = 0

    @property
    def ok(self) -> bool:
        return not self.unverifiable

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "n_verified": len(self.verified),
            "n_unverifiable": len(self.unverifiable),
            "corpus_size": self.corpus_size,
            "verified": [c.to_dict() for c in self.verified],
            "unverifiable": [c.to_dict() for c in self.unverifiable],
        }


# ── number extraction (shared by corpus + claim scanning) ─────────────

_ANY_NUMBER = re.compile(r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?")


def _to_float(tok: str) -> float | None:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _corpus_values(text: str) -> set[float]:
    """Every numeric value appearing anywhere in a ground-truth string."""
    text = _normalize(text)
    out: set[float] = set()
    for m in _ANY_NUMBER.finditer(text):
        v = _to_float(m.group(0))
        if v is not None:
            out.add(v)
    return out


def build_corpus(
    db_path: str | Path | None = None,
    results_paths: list[str | Path] | None = None,
) -> set[float]:
    """Flatten every recorded number from the experiments journal and any given
    results.json files into a set of float values. Token-faithful: we serialize
    each ground-truth source and extract its numbers verbatim."""
    corpus: set[float] = set()

    if db_path and str(db_path) != ":memory:" and Path(db_path).exists():
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            try:
                rows = conn.execute("SELECT * FROM experiments").fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                corpus |= _corpus_values(" ".join("" if v is None else str(v) for v in row))
        finally:
            conn.close()

    for p in results_paths or []:
        try:
            corpus |= _corpus_values(Path(p).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue

    return corpus


# ── matching ──────────────────────────────────────────────────────────

def _matches(value: float, corpus: set[float]) -> float | None:
    """Return the corpus value that matches, or None. Exact within relative
    tolerance; empty-corpus never matches."""
    for c in corpus:
        scale = max(abs(c), abs(value), 1.0)
        if abs(value - c) <= _TOL * scale:
            return c
    return None


def _verify_value(value: float, kind: str, corpus: set[float],
                  extra: tuple[float, float] | None = None) -> float | None:
    """Try the claim's value against the corpus under the interpretations valid
    for its kind (raw, percent<->fraction, both fraction terms)."""
    m = _matches(value, corpus)
    if m is not None:
        return m
    if kind == "percent":
        # "85.4%" may be stored as 0.854 or 85.4
        for cand in (value / 100.0, value * 100.0):
            m = _matches(cand, corpus)
            if m is not None:
                return m
    if kind == "fraction" and extra is not None:
        num, den = extra
        # token-faithful: verified iff BOTH terms are recorded numbers
        if _matches(num, corpus) is not None and _matches(den, corpus) is not None:
            return value
    return None


def _context(text: str, start: int, end: int, width: int = 32) -> str:
    a = max(0, start - width)
    b = min(len(text), end + width)
    return text[a:b].replace("\n", " ").strip()


def scan_claims(text: str) -> list[tuple[str, float, str, str, tuple | None]]:
    """Extract measurement-shaped claims after masking allowlisted spans.

    Returns list of (raw, value, kind, context, extra) where extra carries
    fraction terms. Overlapping matches are resolved by claiming each character
    span at most once, most-specific pattern first.
    """
    text = _normalize(text)
    masked = _ALLOWLIST_RE.sub(lambda m: " " * len(m.group(0)), text)
    claimed: list[tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(s < ce and cs < e for cs, ce in claimed)

    out = []
    for kind, pat in _CLAIM_PATTERNS:
        for m in pat.finditer(masked):
            s, e = m.start(), m.end()
            if overlaps(s, e):
                continue
            extra = None
            if kind == "fraction":
                num = _to_float(m.group(1))
                den = _to_float(m.group(2))
                if num is None or den is None or den == 0:
                    continue
                value = num / den
                extra = (num, den)
            else:
                value = _to_float(m.group(1))
                if value is None:
                    continue
            claimed.append((s, e))
            out.append((m.group(0).strip(), value, kind, _context(text, s, e), extra))
    return out


def verify_text(
    text: str,
    *,
    db_path: str | Path | None = None,
    results_paths: list[str | Path] | None = None,
    corpus: set[float] | None = None,
) -> VerifyReport:
    """Classify every measurement-shaped number in ``text``."""
    if corpus is None:
        corpus = build_corpus(db_path, results_paths)
    report = VerifyReport(corpus_size=len(corpus))
    for raw, value, kind, ctx, extra in scan_claims(text):
        matched = _verify_value(value, kind, corpus, extra)
        claim = NumericClaim(
            raw=raw, value=value, kind=kind, context=ctx,
            status="verified" if matched is not None else "unverifiable",
            matched_value=matched,
        )
        (report.verified if matched is not None else report.unverifiable).append(claim)
    return report
