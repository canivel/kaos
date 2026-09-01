"""
Render terminalizer YAML recording files to animated GIFs.
Uses pyte (VT100 terminal emulator) + Pillow (image generation).
No Electron, no browser — pure Python.

Usage:
    python render_gif.py                   # render all kaos_*.yml in current dir
    python render_gif.py kaos_01.yml       # render a single file
"""

import os
import re
import sys
import yaml
import pyte
from PIL import Image, ImageDraw, ImageFont

# ── Config ────────────────────────────────────────────────────────────────────

COLS         = 110
ROWS         = 32
FONT_SIZE    = 14
LINE_HEIGHT  = 20
CHAR_WIDTH   = 8   # approximate for monospace at size 14
PAD_X        = 18
PAD_Y        = 46  # space for titlebar
TITLE_H      = 30
LOOP         = 0   # 0 = loop forever
MAX_DELAY_MS = 1800

# GitHub dark theme palette
BG_COLOR     = (13,  17,  23)   # #0d1117
FG_COLOR     = (201, 209, 217)  # #c9d1d9
TITLE_BG     = (22,  27,  34)   # #161b22
TITLE_FG     = (139, 148, 158)  # #8b949e
BTN_RED      = (255, 95,  86)
BTN_YLW      = (255, 189, 46)
BTN_GRN      = (39,  201, 63)

ANSI_COLORS = {
    # normal
    30: (22,  27,  34),   # black  → dark bg
    31: (255, 123, 114),  # red
    32: (63,  185, 80),   # green
    33: (227, 179, 65),   # yellow
    34: (88,  166, 255),  # blue
    35: (188, 140, 255),  # magenta
    36: (57,  197, 207),  # cyan
    37: (181, 186, 196),  # white
    90: (110, 118, 129),  # bright black (dark grey)
    91: (255, 161, 152),  # bright red
    92: (86,  211, 100),  # bright green
    93: (227, 179, 65),   # bright yellow
    94: (121, 192, 255),  # bright blue
    95: (210, 168, 255),  # bright magenta
    96: (86,  212, 221),  # bright cyan
    97: (240, 246, 252),  # bright white
}

# ── Font loading ──────────────────────────────────────────────────────────────

def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/consola.ttf",   # Consolas
        "C:/Windows/Fonts/cour.ttf",       # Courier New
        "C:/Windows/Fonts/lucon.ttf",      # Lucida Console
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


FONT      = load_font(FONT_SIZE)
FONT_BOLD = load_font(FONT_SIZE)  # use same font — bold separate path if available

# Measure actual char dimensions from the loaded font
try:
    bbox = FONT.getbbox("M")
    CHAR_WIDTH  = bbox[2] - bbox[0]
    LINE_HEIGHT = int((bbox[3] - bbox[1]) * 1.55)
except Exception:
    pass  # keep defaults

IMG_W = PAD_X * 2 + COLS * CHAR_WIDTH
IMG_H = PAD_Y + ROWS * LINE_HEIGHT + 12

# ── Terminal emulation ────────────────────────────────────────────────────────

def make_screen() -> tuple[pyte.Screen, pyte.ByteStream]:
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    return screen, stream

def feed(stream: pyte.ByteStream, content: str) -> None:
    stream.feed(content.encode("utf-8", errors="replace"))

# ── ANSI color helper (for pyte's char attributes) ───────────────────────────

def resolve_color(color_attr, default: tuple) -> tuple:
    """Convert a pyte color attribute to an RGB tuple."""
    if color_attr is None or color_attr == "default":
        return default
    if isinstance(color_attr, str):
        # Named color from pyte: 'green', 'red', etc.
        name_map = {
            "black": ANSI_COLORS[30], "red": ANSI_COLORS[31],
            "green": ANSI_COLORS[32], "brown": ANSI_COLORS[33],
            "blue":  ANSI_COLORS[34], "magenta": ANSI_COLORS[35],
            "cyan":  ANSI_COLORS[36], "white": ANSI_COLORS[37],
        }
        return name_map.get(color_attr, default)
    if isinstance(color_attr, int):
        return ANSI_COLORS.get(color_attr, default)
    return default

# ── Frame rendering ───────────────────────────────────────────────────────────

def render_frame(screen: pyte.Screen, title: str) -> Image.Image:
    img  = Image.new("RGB", (IMG_W, IMG_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([0, 0, IMG_W, TITLE_H], fill=TITLE_BG)
    draw.text((PAD_X, 8), title, font=FONT, fill=TITLE_FG)
    # Traffic lights
    for i, col in enumerate([BTN_RED, BTN_YLW, BTN_GRN]):
        cx = IMG_W - 22 - i * 18
        draw.ellipse([cx-5, TITLE_H//2-5, cx+5, TITLE_H//2+5], fill=col)

    # Terminal content
    for row_idx in range(ROWS):
        y = PAD_Y + row_idx * LINE_HEIGHT
        line = screen.buffer[row_idx]
        x = PAD_X
        for col_idx in range(COLS):
            char = line[col_idx]
            ch   = char.data if char.data else " "
            fg   = resolve_color(char.fg, FG_COLOR)
            bg   = resolve_color(char.bg, BG_COLOR)
            bold = getattr(char, "bold", False)

            if bg != BG_COLOR:
                draw.rectangle(
                    [x, y, x + CHAR_WIDTH, y + LINE_HEIGHT],
                    fill=bg,
                )
            font = FONT_BOLD if bold else FONT
            if ch.strip():
                draw.text((x, y + 2), ch, font=font, fill=fg)
            x += CHAR_WIDTH

    return img

# ── GIF assembly ──────────────────────────────────────────────────────────────

def frames_to_gif(frames: list[tuple[Image.Image, int]], out_path: str) -> None:
    """Save list of (image, delay_ms) as animated GIF."""
    images   = [f[0].convert("P", palette=Image.ADAPTIVE, colors=256) for f in frames]
    durations = [max(20, min(f[1], MAX_DELAY_MS)) // 10 * 10 for f in frames]  # round to 10ms

    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        optimize=False,
        duration=durations,
        loop=LOOP,
    )

# ── Main pipeline ─────────────────────────────────────────────────────────────

def render_yaml(yml_path: str, out_path: str | None = None) -> str:
    with open(yml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    config  = data.get("config", {})
    records = data.get("records", [])
    title   = (config.get("frameBox") or {}).get("title", "KAOS")
    cols    = config.get("cols", COLS) if config.get("cols") != "auto" else COLS
    rows    = config.get("rows", ROWS) if config.get("rows") != "auto" else ROWS

    screen, stream = make_screen()

    if out_path is None:
        out_path = yml_path.replace(".yml", ".gif")

    frames: list[tuple[Image.Image, int]] = []
    prev_frame = None

    for record in records:
        delay   = int(record.get("delay", 80))
        content = record.get("content", "")

        if content:
            feed(stream, content)

        img = render_frame(screen, title)

        # Only keep unique frames (deduplicate identical consecutive frames)
        if prev_frame is None or list(img.tobytes()) != list(prev_frame.tobytes()):
            frames.append((img, max(delay, 30)))
            prev_frame = img
        else:
            # Accumulate delay onto last frame
            if frames:
                frames[-1] = (frames[-1][0], frames[-1][1] + delay)

    # Add a 2-second hold on the last frame
    if frames:
        last_img, last_delay = frames[-1]
        frames[-1] = (last_img, last_delay + 2000)

    if not frames:
        print(f"  WARNING: no frames in {yml_path}")
        return out_path

    frames_to_gif(frames, out_path)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"  Saved: {out_path}  ({len(frames)} frames, {size_kb} KB)")
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        targets = sorted(
            os.path.join(script_dir, f)
            for f in os.listdir(script_dir)
            if f.startswith("kaos_") and f.endswith(".yml")
        )

    print(f"Rendering {len(targets)} recording(s)...")
    for yml in targets:
        name = os.path.basename(yml)
        print(f"\n[{name}]")
        try:
            render_yaml(yml)
        except Exception as e:
            print(f"  ERROR: {e}")

    print("\nAll done.")
