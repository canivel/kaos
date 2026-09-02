"""Fetch the LongMemEval (cleaned) files named in preregistration.json and verify sha256.

    uv run python benchmarks/longmemeval/download.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
BASE = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    lock = json.loads((HERE / "preregistration.json").read_text())
    ds = lock["dataset"]
    DATA.mkdir(exist_ok=True)
    ok = True
    for name, expected in ((ds["primary_file"], ds["primary_sha256"]),
                           (ds["control_file"], ds["control_sha256"])):
        dest = DATA / name
        if not dest.exists():
            print(f"downloading {name} …")
            urllib.request.urlretrieve(BASE + name, dest)
        got = sha256(dest)
        status = "ok" if got == expected else "SHA256 MISMATCH"
        ok = ok and got == expected
        print(f"{name}: {dest.stat().st_size} bytes  sha256={got}  {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
