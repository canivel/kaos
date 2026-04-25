"""Generate a clones-over-time chart from GitHub Traffic API data.

Reads JSON from gh api repos/canivel/kaos/traffic/clones (passed on stdin
or via --input), writes a PNG to f:/Projects/kaos-ghpages/charts/.

The chart shows daily total clones + unique cloners across the 14-day
window. Spikes correlate with release events.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OUT_DIR = Path("f:/Projects/kaos-ghpages/charts")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BG = "#0a0a0f"
BG2 = "#12121a"
FG = "#e4e4ef"
FG2 = "#9494a8"
PINK = "#fd79a8"
PURPLE = "#a29bfe"
GREEN = "#00e676"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": BG2,
    "savefig.facecolor": BG,
    "axes.edgecolor": "#2a2a3a",
    "axes.labelcolor": FG,
    "xtick.color": FG2,
    "ytick.color": FG2,
    "text.color": FG,
    "axes.grid": True,
    "grid.color": "#22222e",
    "grid.linewidth": 0.7,
    "font.family": "sans-serif",
    "font.size": 10.5,
})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path,
                   help="JSON file from `gh api repos/.../traffic/clones`. "
                        "If omitted, reads stdin.")
    p.add_argument("--out", type=Path,
                   default=OUT_DIR / "github-clones-14d.png")
    args = p.parse_args()

    raw = (args.input.read_text() if args.input
           else sys.stdin.read())
    data = json.loads(raw)

    days = data["clones"]
    if not days:
        print("No clone data — exiting", file=sys.stderr)
        return 1

    dates = [datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
             for d in days]
    counts = [d["count"] for d in days]
    uniques = [d["uniques"] for d in days]

    total_clones = data["count"]
    total_uniques = data["uniques"]

    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=160)

    bar_w = 0.7
    x = mdates.date2num(dates)

    ax.bar(x - 0.18, counts, width=0.36, color=PINK,
           edgecolor=PINK, linewidth=1.2, label=f"Total clones  ({total_clones:,})",
           alpha=0.92)
    ax.bar(x + 0.18, uniques, width=0.36, color=PURPLE,
           edgecolor=PURPLE, linewidth=1.2,
           label=f"Unique cloners  ({total_uniques:,})", alpha=0.92)

    # Annotate the peak day
    peak_i = counts.index(max(counts))
    ax.annotate(f"{counts[peak_i]} clones",
                xy=(x[peak_i] - 0.18, counts[peak_i]),
                xytext=(0, 8), textcoords="offset points",
                ha="center", fontsize=9.5, color=FG, weight="bold")

    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center")

    ax.set_ylabel("Daily count")
    title = (f"github.com/canivel/kaos  --  clones over the last 14 days\n"
             f"{total_clones:,} clones, {total_uniques:,} unique cloners")
    ax.set_title(title, color=FG, fontsize=12.5, pad=12, weight="bold")
    ax.legend(loc="upper right", facecolor=BG2, edgecolor="#2a2a3a",
              labelcolor=FG, framealpha=0.95)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    snap_ts = datetime.utcnow().strftime("%Y-%m-%d")
    ax.text(0.99, -0.18,
            f"GitHub Traffic API snapshot - {snap_ts}",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8, color=FG2, style="italic")

    plt.tight_layout()
    plt.savefig(args.out, bbox_inches="tight")
    plt.close()
    print(f"Wrote {args.out}  ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
