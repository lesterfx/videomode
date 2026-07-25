"""
snapshotter.py — Phase 5: Snapshot Creation Tooling
One-time offline step for each game: start the ROM, navigate to the moment
video mode begins, press Enter to capture a .sta file that Phase 6 loads.

Snapshot format
---------------
libpinmame delegates save/restore to MAME's built-in state system.  A .sta
file is a zlib-compressed binary blob containing:

  - CPU register dumps for every CPU core in the driver
  - Full RAM region contents for every memory region
  - Timer state, video state, sound chip registers

The file is written by MAME's save-state machinery when we call
PinmameSaveState() (or inject the equivalent internal event).  It is read
back by PinmameLoadState() during Phase 6.  We do not parse the binary
format ourselves; MAME owns the schema and we treat the file as opaque.

Filename convention (must match Phase 6 expectations)
------------------------------------------------------
  <SNAPSHOT_DIR>/<rom_name>/<rom_name>_<YYYYMMDD_HHMMSS>.sta

  The subdirectory per ROM keeps things tidy and mirrors where MAME itself
  writes auto-saves.  Phase 6's load_snapshot() receives the full Path so
  there is no implicit discovery at load time.

Save-state API
--------------
libpinmame exposes two functions (resolved via ctypes at runtime):

  PinmameSaveState(const char *filename)   →  int  (0 = ok)
  PinmameLoadState(const char *filename)   →  int  (0 = ok)

  'filename' is the full path including the .sta extension.
  Both calls are synchronous from the Python side; MAME flushes state on the
  emulation thread but the functions do not return until the file is written /
  read.

  If the symbols are absent from a particular libpinmame build (older forks
  sometimes omit them) we fall back to the raw-memory approach: dump every
  region returned by PinmameGetRawMemoryRegion() into a simple envelope
  defined in this module (see _RawSnapshot below).
"""

from __future__ import annotations

import ctypes
import json
import logging
import struct
import sys
import termios
import time
import tty
import zlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from bridge import PinMAMEBridge
from dmd_display import DMDDisplay
from button import ButtonInput
from vm_types import GameEntry, VideoModeResult


# ---------------------------------------------------------------------------
# Phase 5 — Snapshotter
# ---------------------------------------------------------------------------

class Snapshotter:
    """
    Offline snapshot creation tool.

    Usage
    -----
    Instantiate, call run(game).  The operator navigates the ROM to the
    moment video mode begins, then presses Enter.  A .sta file is written to
    SNAPSHOT_DIR and the path is printed to stdout.

    Key map (raw terminal mode)
    ---------------------------
      '0'–'9'  → switches  0– 9  (toggle on each press)
      'a'–'z'  → switches 10–35  (toggle on each press)
      Enter    → capture snapshot and exit
      Ctrl-C   → abort without writing a file
    """

    _SNAPSHOTTER_KEYS: list[int] = [
         1,  2,  3,  4,  5,  6,  7,  8,
        11, 12, 13, 14, 15, 16, 17, 18,
        21, 22, 23, 24, 25, 26, 27, 28,
        31, 32, 33, 34, 35, 36, 37, 38,
        41, 42, 43, 44, 45, 46, 47, 48,
        51, 52, 53, 54, 55, 56, 57, 58,
        61, 62, 63, 64, 65, 66, 67, 68,
        71, 72, 73, 74, 75, 76, 77, 78,
        81, 82, 83, 84, 85, 86, 87, 88,
    ]
    _SNAPSHOTTER_CHARS: str = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()-_=+[{]}\\|;:'\",<.>/?"

    def __init__(
        self,
        pinmame:  PinMAMEBridge,
        display:  DMDDisplay,
        buttons:  ButtonInput,
        screenshotting: bool = False
    ) -> None:
        self.pinmame  = pinmame
        self.display  = display
        self.buttons  = buttons
        self.screenshotting = screenshotting
        self.log      = logging.getLogger("Snapshotter")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, game: GameEntry) -> VideoModeResult:
        """
        Free-run emulation with keyboard → switch-matrix control.

        Blocks until the operator presses Enter (snapshot saved) or Ctrl-C
        (abort).  Returns a VideoModeResult with score=0 and
        ended_naturally=False in both cases.
        """
        self.log.info("Snapshotter mode for %s — no snapshot loaded", game.parent.rom)
        self.pinmame.dmd_callback = self.display.show_frame

        # Start emulation from cold boot (no snapshot to restore yet).
        # connect() is assumed already called by the caller / startup().
        self.pinmame.load_game(game.parent.rom)

        self.active_switches: set[int] = set()
        self.display.label_getter = self.get_label
        start = time.monotonic()

        self.log.info("\nSnapshotter mode — navigate to video mode then press Enter.")
        self.log.info(
            f"Keys: {''.join(self._SNAPSHOTTER_CHARS)}"
            "  |  Enter = snapshot  |  Ctrl-C = abort\n"
        )

        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        saved_path: Optional[Path] = None

        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)

            while True:
                ch = sys.stdin.read(1)

                # Enter (\r in raw mode) → capture and exit
                if ch in ("\r", "\n"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    if self.screenshotting:
                        self.log.info('Capturing screenshot...')
                        last_frames = self.display.stack
                        for last_frame in last_frames:
                            chars = ''.join([str(int(ch)) for ch in last_frame])
                            self.log.info(chars)
                        self.log.info('Screenshot above')
                    else:
                        self.log.info('Capturing snapshot...')
                        saved_path = self._capture()
                        self.log.info('Snapshot saved')
                    break

                # Ctrl-C → abort
                if ch == "\x03":
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    self.log.info('Aborted - no snapshot written.')
                    break

                # Switch toggle
                sw = self._switch_for_key(ch)
                if sw is not None:
                    if sw in self.active_switches:
                        self.active_switches.discard(sw)
                        self.pinmame.send_switch(sw, False)
                    else:
                        self.active_switches.add(sw)
                        self.pinmame.send_switch(sw, True)

        except KeyboardInterrupt:
            pass
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass
            self.pinmame.stop()

        duration = time.monotonic() - start
        return VideoModeResult(
            game=game,
            score=0,
            duration_seconds=duration,
            ended_naturally=False,
        )

    # ------------------------------------------------------------------
    # Snapshot capture — called when operator presses Enter
    # ------------------------------------------------------------------

    def _capture(self):
        self.pinmame.save_snapshot()

    # ------------------------------------------------------------------
    # Terminal helpers
    # ------------------------------------------------------------------

    def get_label(self) -> str:
        try:
            return self._get_switches_label() + '\r\n' + self._get_lamps_label()
        except:
            logging.error('error getting label', exc_info=True)

    def _get_switches_label(self) -> str:
        r = 'switches: '
        for i, idx in enumerate(self._SNAPSHOTTER_KEYS):
            if idx in self.active_switches:
                r += self._SNAPSHOTTER_CHARS[i]
            else:
                r += ' '
        return r

    def _get_lamps_label(self):
        r = 'lamps: '
        lamps = self.pinmame.get_lamps()
        for idx in self._SNAPSHOTTER_KEYS:
            # if idx not in {28, 35, 37, 38, 36}: continue
            if idx in lamps:
                r += str(idx)
            else:
                r += ' '*len(str(idx))
            r += ' '
        logging.info(r)
        return r

    def _switch_for_key(self, ch: str) -> Optional[int]:
        try:
            return self._SNAPSHOTTER_KEYS[self._SNAPSHOTTER_CHARS.index(ch)]
        except (ValueError, IndexError):
            return None

