#!/usr/bin/env python3
"""
dmd_demo.py
-----------
Phase 1 smoke-test: load libpinmame, fire up a game, and print every DMD
frame as ASCII art to the terminal.

Usage
-----
    # Minimal – uses env var / auto-detection for the .so path
    python dmd_demo.py --game t2_l8 --roms ~/.pinmame/roms

    # Explicit library path
    python dmd_demo.py --game t2_l8 --roms ~/.pinmame/roms \\
                       --lib /usr/local/lib/libpinmame.so

    # Dry-run: verify ctypes binding loads without needing a real .so
    python dmd_demo.py --verify-only

Controls
--------
Ctrl-C  →  stop emulator and exit cleanly.
"""

import argparse
import sys
import os
import time
import ctypes
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="libpinmame DMD terminal demo")
    p.add_argument("--game",  default="t2_l8",
                   help="ROM short name  (default: t2_l8)")
    p.add_argument("--roms",  default=str(Path.home() / ".pinmame" / "roms"),
                   help="Path to ROM directory")
    p.add_argument("--lib",   default=None,
                   help="Explicit path to libpinmame.so/.dylib")
    p.add_argument("--fps",   type=float, default=10.0,
                   help="Max frames to print per second (default: 10)")
    p.add_argument("--verify-only", action="store_true",
                   help="Just verify the ctypes binding builds; don't run a game")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Stand-alone struct/type verification (no .so required)
# ---------------------------------------------------------------------------

def verify_binding() -> None:
    """
    Instantiate every struct and callback type to confirm ctypes sizes match
    the C layout.  Does NOT load the shared library.
    """
    # Local import so the rest of the file doesn't depend on the package root.
    sys.path.insert(0, str(Path(__file__).parent))
    from pinmame._types import (
        PinmameConfig,
        PinmameDisplayLayout,
        PinmameAudioInfo,
        PinmameMechConfig,
        PINMAME_MAX_PATH,
        PINMAME_MAX_MECHSW,
    )
    import ctypes

    print("Verifying ctypes struct sizes against libpinmame.h expectations …\n")

    checks = [
        # (struct class, expected sizeof in bytes, description)
        (PinmameDisplayLayout, 7 * 4,  "PinmameDisplayLayout (7×int32)"),
        (PinmameAudioInfo,
         4 + 4 + 8 + 8 + 4 + 4,       "PinmameAudioInfo (int,int,dbl,dbl,int,int)"),
    ]
    all_ok = True
    for cls, expected, label in checks:
        actual = ctypes.sizeof(cls)
        status = "✓" if actual == expected else f"✗  got {actual}"
        print(f"  sizeof({label}) = {actual}  {status}")
        if actual != expected:
            all_ok = False

    print(f"\n  sizeof(PinmameConfig)       = {ctypes.sizeof(PinmameConfig)}")
    print(f"  PINMAME_MAX_PATH            = {PINMAME_MAX_PATH}")
    print(f"  PINMAME_MAX_MECHSW          = {PINMAME_MAX_MECHSW}")

    # Verify vpmPath field offset – should be 8 (two ints before it)
    off = PinmameConfig.vpmPath.offset
    print(f"  PinmameConfig.vpmPath offset= {off}  "
          f"{'✓' if off == 8 else '✗ expected 8'}")
    if off != 8:
        all_ok = False

    print()
    if all_ok:
        print("All checks passed. ✓")
    else:
        print("Some checks FAILED.  The struct layout may differ from the header.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    if args.verify_only:
        verify_binding()
        return

    # -- imports (after path fixup so we can run the script from its own dir)
    sys.path.insert(0, str(Path(__file__).parent))
    from pinmame.session import PinmameSession
    from terminal_dmd import print_frame
    from pinmame._types import DmdMode, DisplayType

    min_interval = 1.0 / max(0.1, args.fps)
    last_print: dict[int, float] = {}
    frame_counter: dict[int, int] = {}

    def on_display_available(index, display_count, layout):
        kind = "DMD" if layout.is_dmd else "SEG"
        print(f"[display_available] index={index} count={display_count} "
              f"type={kind} {layout.width}×{layout.height} depth={layout.depth}")

    def on_display_updated(index, frame, layout):
        nonlocal last_print
        if not layout.is_dmd:
            return  # ignore alphanumeric segment displays for now

        now = time.monotonic()
        if now - last_print.get(index, 0) < min_interval:
            return
        last_print[index] = now
        frame_counter[index] = frame_counter.get(index, 0) + 1

        header = (f"DMD #{index}  {layout.width}×{layout.height}  "
                  f"depth={layout.depth}  frame={frame_counter[index]}")

        # Clear previous frame: move cursor up (height + 2 border lines)
        if frame_counter[index] > 1:
            total_lines = layout.height + 2
            sys.stdout.write(f"\x1b[{total_lines}A\x1b[J")

        print_frame(frame, layout, header=header)

    def on_log(level, message):
        # Suppress noisy INFO messages; show WARN/ERROR only
        # if level >= 2:
            print(f"[libpinmame] {message}", file=sys.stderr)

    print(f"Starting {args.game!r} from {args.roms!r} …")
    print("Press Ctrl-C to stop.\n")

    with PinmameSession(
        rom_path=args.roms,
        game=args.game,
        lib_path=args.lib,
        dmd_mode=DmdMode.RAW,
    ) as pm:
        pm.on_display_available = on_display_available
        pm.on_display_updated   = on_display_updated
        pm.on_log_message       = on_log
        pm.run()

    print("\nStopped.")


if __name__ == "__main__":
    main()
