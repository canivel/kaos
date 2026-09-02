"""Dependency-free ULID generation.

Format-identical to ulid-py's ``str(ulid.new())`` (26 Crockford base32
chars, 48-bit millisecond timestamp + 80 random bits, lexicographically
time-sortable). Kept in-tree because importing ``ulid`` costs ~200 ms at
CLI start-up, which is the whole latency budget of a Claude Code hook.
"""
from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _b32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_ulid() -> str:
    """Return a fresh ULID string."""
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return _b32(ts_ms, 10) + _b32(rand, 16)
