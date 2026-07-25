"""
pinmame/dmd_render.py
---------------------
Terminal rendering helpers for DMD frames.

Two renderers are provided:

  render_ascii(frame, layout)
      Classic ASCII art – maps shade values to  ░▒▓█  block characters.
      Works in any terminal that supports Unicode.

  render_ansi(frame, layout)
      ANSI 256-colour dot rendering – each pixel becomes a coloured "●"
      or space on a black background.  Looks great in modern terminals.

Both functions return a list of strings (one per row) so you can print,
log, or forward them however you like.
"""

from __future__ import annotations

import sys
import time

from pinmame._types import PinmameDisplayLayout

width = 128
height = 32
depth = 2                                # bits per pixel (usually 2 or 4)


# Shade ramp for RAW mode (depth=2 → 4 shades, depth=4 → 16 shades)
# For BRIGHTNESS mode the values are 0-100; we map to the same ramp.
_ASCII_RAMP = " ░▒▓█"   # 5 chars  → index = (value * 4) // max_value


def _shade_to_idx(value: int, max_value: int) -> int:
    """Map a pixel value in [0, max_value] to a ramp index in [0, 4]."""
    if max_value <= 0:
        return 0
    return min(4, (value * 4 + max_value // 2) // max_value)


# ---------------------------------------------------------------------------
# ASCII art renderer
# ---------------------------------------------------------------------------

def render_ascii(
    frame: bytes | bytearray,
    *,
    double_wide: bool = True,
) -> list[str]:
    """
    Convert a raw DMD frame to ASCII art rows.

    Parameters
    ----------
    frame
        Raw pixel bytes from the ``on_display_updated`` callback.
    double_wide
        If True, each pixel is printed twice to preserve the aspect ratio
        of a real DMD (pixels are roughly 1:1 physically but terminals
        use ~2:1 character cells).

    Returns
    -------
    list[str]
        One string per row, not newline-terminated.
    """
    max_val = (1 << depth) - 1               # 3 for depth=2, 15 for depth=4

    rows: list[str] = []
    for y in range(height):
        row_chars: list[str] = []
        for x in range(width):
            idx_data = y * width + x
            value = frame[idx_data] if idx_data < len(frame) else 0
            ch = _ASCII_RAMP[_shade_to_idx(value, max_val)]
            row_chars.append(ch if not double_wide else ch + ' ')
        rows.append("".join(row_chars))
    return rows


def print_ascii_frame(
    frame: bytes | bytearray,
    label='',
    double_wide: bool = True,
    header: str = "",
) -> None:
    """Print a DMD frame to stdout with an optional header line."""
    w, h = width, height
    if not isinstance(label, str):
        label = ''
    sep = label.center(w * (2 if double_wide else 1), '-')
    if header:
        print(f"┌─ {header} {'─' * max(0, len(sep) - len(header) - 3)}┐", end='\r\n')
    else:
        print(f"┌{sep}┐", end='\r\n')
    for row in render_ascii(frame, double_wide=double_wide):
        print(f"│{row}│", end='\r\n')
    print(f"└{sep}┘", end='\r\n')


# ---------------------------------------------------------------------------
# ANSI colour renderer
# ---------------------------------------------------------------------------

# Classic orange DMD palette: 0 → black … depth → bright amber
_ANSI_PALETTE = {
    # (r, g, b) tuples for 16-shade ramp – nearest xterm-256 index
    0:  (0,   0,   0),
    1:  (40,  10,  0),
    2:  (80,  20,  0),
    3:  (120, 35,  0),
    4:  (160, 50,  0),
    5:  (180, 65,  0),
    6:  (200, 80,  0),
    7:  (215, 100, 0),
    8:  (225, 120, 5),
    9:  (230, 140, 10),
    10: (235, 155, 15),
    11: (238, 170, 20),
    12: (240, 185, 30),
    13: (242, 200, 40),
    14: (245, 215, 55),
    15: (255, 230, 80),
}


def _rgb_to_ansi256(r: int, g: int, b: int) -> int:
    """Nearest xterm-256 colour index for an (r,g,b) triple."""
    if r == g == b:
        if r < 8:   return 16
        if r > 248: return 231
        return round((r - 8) / 247 * 24) + 232
    ri = round(r / 255 * 5)
    gi = round(g / 255 * 5)
    bi = round(b / 255 * 5)
    return 16 + 36 * ri + 6 * gi + bi


_ANSI_BG  = "\x1b[40m"           # black background
_ANSI_RST = "\x1b[0m"
_DOT_ON   = "●"
_DOT_OFF  = " "


def render_ansi(
    frame: bytes | bytearray,
    double_wide: bool = True
) -> list[str]:
    """
    Convert a raw DMD frame to ANSI-coloured terminal rows.

    Each pixel is rendered as "● " (two chars wide) with an orange-tinted
    foreground colour proportional to its brightness.  Requires a 256-colour
    terminal.
    """
    max_val = max(1, (1 << depth) - 1)

    rows: list[str] = []
    for y in range(height):
        parts: list[str] = [_ANSI_BG]
        for x in range(width):
            idx_data = y * width + x
            raw = frame[idx_data] if idx_data < len(frame) else 0
            # Map to 0-15 range for palette lookup
            shade = min(15, (raw * 15 + max_val // 2) // max_val)
            r, g, b = _ANSI_PALETTE[shade]
            fg = _rgb_to_ansi256(r, g, b)
            if shade == 0:
                parts.append(f"\x1b[38;5;{fg}m{_DOT_OFF}")
            else:
                parts.append(f"\x1b[38;5;{fg}m{_DOT_ON}")
        parts.append(_ANSI_RST)
        if double_wide:
            rows.append(" ".join(parts))
        else:
            rows.append("".join(parts))
    return rows

_last_print = time.monotonic()
def print_ansi_frame(
    frame: bytes | bytearray,
    scroll_to_top: bool = False,
    label_getter: Optional(callable) = None
) -> None:
    """Print an ANSI-coloured frame """
    now = time.monotonic()
    if now - _last_print < 1/10:
        return
    last_print = time.monotonic()
    if scroll_to_top:
        SCROLL_HEIGHT = height+4
        sys.stdout.write(f"\x1b[{SCROLL_HEIGHT}A\x1b[J")

    if label_getter:
        print(label_getter(), end='\r\n')
    else:
        print(end='\r\n')

    for row in render_ansi(frame, double_wide=True):
        print(row, end='\r\n')

print_frame = print_ansi_frame
