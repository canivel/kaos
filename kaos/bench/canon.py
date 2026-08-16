"""Content addressing for eval records — the one canonicalizer, used everywhere.

    record_cid = "tb1:" + hex(sha256(JCS(body)))

JCS is the JSON Canonicalization Scheme (RFC 8785): sorted object keys, no
insignificant whitespace, ECMAScript number formatting, UTF-8. A record is a
Merkle node — the body transitively commits (via ``lock_sha256`` and
``results_sha256``) to the lock bytes and results bytes — so two benches holding
the same ``record_cid`` provably hold the same eval, gates, and numbers.

Every surface (CLI, SDK, MCP, admission, the hosted server) MUST use this module.
A second canonicalizer that disagrees on one byte is the classic federation
footgun: identity would fork silently when a record moves between benches.

The ``tb1:`` prefix versions the hashing scheme independently of the record
schema (which is versioned by ``schema_id``). Note: the lock is NEVER canonicalized
here — it is hashed over its raw committed bytes elsewhere (PLAN.md R3); this module
canonicalizes the record *body* only.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

CID_PREFIX = "tb1:"


def _fmt_number(x: int | float) -> str:
    """ECMAScript ``Number::toString`` for the values that appear in a record body
    (probabilities, thresholds, small signed decimals, counts).

    Integral values render without a fractional part (JCS: ``1.0`` -> ``"1"``),
    non-integral values use Python's shortest round-trip repr (matches ES across
    the finite range records use). NaN/Inf are not representable in JSON and are
    rejected rather than silently coerced.
    """
    if isinstance(x, bool):  # bool is an int subclass — must be handled by caller
        raise TypeError("bool is not a number")
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        raise ValueError(f"non-finite number is not JSON-representable: {x!r}")
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))  # integral float -> integer form, and normalizes -0.0
    return repr(x)


def _ser(obj: Any) -> str:
    """Serialize one value to its canonical JCS string form."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        # RFC 8259 minimal escaping, non-ASCII preserved — exactly JCS's string rule.
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, (int, float)):
        return _fmt_number(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_ser(v) for v in obj) + "]"
    if isinstance(obj, dict):
        for k in obj:
            if not isinstance(k, str):
                raise TypeError(f"object keys must be strings, got {type(k).__name__}")
        # JCS orders keys by UTF-16 code units; encoding to UTF-16-BE gives that
        # order exactly (and equals codepoint order for the ASCII keys records use).
        items = sorted(obj.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(_ser(k) + ":" + _ser(v) for k, v in items) + "}"
    raise TypeError(f"value of type {type(obj).__name__} is not JSON-serializable")


def canonical_bytes(body: Any) -> bytes:
    """The exact canonical bytes of a record body — what gets hashed and stored."""
    return _ser(body).encode("utf-8")


def record_cid(body: Any) -> str:
    """``"tb1:" + hex(sha256(JCS(body)))`` — stable under key reordering / reserialization."""
    return CID_PREFIX + hashlib.sha256(canonical_bytes(body)).hexdigest()


def verify_cid(body: Any, cid: str) -> bool:
    """True iff ``body`` canonicalizes to ``cid``. Verification at rest / on receive."""
    return record_cid(body) == cid
