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
from vm_types import GameEntry, ScreenState, SessionContext


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

    _SNAPSHOTTER_CHARS: str = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()-_=+[{]}\\|;:'\",<.>/?"

    game: GameEntry
    def __init__(
        self,
        pinmame:  PinMAMEBridge,
        display:  DMDDisplay,
        buttons:  ButtonInput,
        screenshotting: bool = False,
        **kw
    ) -> None:
        self.pinmame  = pinmame
        self.display  = display
        self.buttons  = buttons
        self.screenshotting = screenshotting
        self.display.screenshotting = screenshotting
        self.active_solenoids = set()
        self.log      = logging.getLogger("Snapshotter")

        self.switch_matrix_indexes: dict[str, tuple[int, ...]] = {
            'wpc': (
                1,  2,  3,  4,  5,  6,  7,  8,
                11, 12, 13, 14, 15, 16, 17, 18,
                21, 22, 23, 24, 25, 26, 27, 28,
                31, 32, 33, 34, 35, 36, 37, 38,
                41, 42, 43, 44, 45, 46, 47, 48,
                51, 52, 53, 54, 55, 56, 57, 58,
                61, 62, 63, 64, 65, 66, 67, 68,
                71, 72, 73, 74, 75, 76, 77, 78,
                81, 82, 83, 84, 85, 86, 87, 88,
                112, 114
            ),
            'sega': (
                 1,  2,  3,  4,  5,  6,  7 , 8,
                 9, 10, 11, 12, 13, 14, 15, 16,
                17, 18, 19, 20, 21, 22, 23, 24,
                25, 26, 27, 28, 29, 30, 31, 32,
                33, 34, 35, 36, 37, 38, 39, 40,
                41, 42, 43, 44, 45, 46, 47, 48,
                49, 50, 51, 52, 53, 54, 55, 56,
                57, 58, 59, 60, 61, 62, 63, 64,
                65, 66, 67, 68, 69, 70, 71, 72
            ),
            'gottlieb': (
                 0,  1,  2,  3,  4,  5,  6,  7,
                10, 11, 12, 13, 14, 15, 16, 17,
                20, 21, 22, 23, 24, 25, 26, 27,
                30, 31, 32, 33, 34, 35, 36, 37,
                40, 41, 42, 43, 44, 45, 46, 47,
                50, 51, 52, 53, 54, 55, 56, 57,
                60, 61, 62, 63, 64, 65, 66, 67,
                70, 71, 72, 73, 74, 75, 76, 77,
                80, 81, 82, 83, 84, 85, 86, 87,
                90, 91, 92, 93, 94, 95, 96, 97,
               100,101,102,103,104,105,106,107,
               110,111,112,113,114,115,116,117
            )
        }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        ctx: SessionContext
    ) -> ScreenState:
        """
        Free-run emulation with keyboard → switch-matrix control.

        Blocks until the operator presses Enter (snapshot saved) or Ctrl-C
        (abort). 
        """

        assert ctx.game, 'no game provided to snapshotter'
        self.game = ctx.game

        self.log.info("Snapshotter mode for %s — no snapshot loaded", self.game.parent.rom)
        self.pinmame.dmd_callback = self.display.show_frame

        # Start emulation from cold boot (no snapshot to restore yet).
        # connect() is assumed already called by the caller / startup().
        assert self.game.parent.rom, f"game {self.game.parent} has no rom"
        self.pinmame.load_game(self.game.parent.rom)
        self.pinmame.state_callback = self.on_state_update

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
                            chars = ''.join([hex(int(ch))[2:] for ch in last_frame])
                            self.log.info(chars)
                        self.log.info('Screenshot above')
                        break
                    else:
                        self.log.info('Capturing snapshot...')
                        self._capture()
                        self.log.info('switches: %s', sorted(self.active_switches))
                        self.log.info('Snapshot saved')

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
            self.display.label_getter = None
            self.log.info('stopping pinmame')

        return ScreenState.SNAPSHOTTED

    # ------------------------------------------------------------------
    # Snapshot capture — called when operator presses Enter
    # ------------------------------------------------------------------

    def _capture(self):
        self.pinmame.save_snapshot(self.game.snapshot_index)

    # ------------------------------------------------------------------
    # Terminal helpers
    # ------------------------------------------------------------------

    def get_label(self) -> str:
        try:
            return self._get_switches_label() + '\r\n' + self._get_lamps_label()
        except:
            logging.error('error getting label', exc_info=True)
            return ''

    def _get_switches_label(self) -> str:
        r = 'switches: '
        for i, idx in enumerate(self.switch_matrix_indexes[self.game.parent.platform]):
            if idx in self.active_switches:
                r += self._SNAPSHOTTER_CHARS[i]
            else:
                r += ' '
        return r

    def _get_lamps_label(self):
        r = f'{str(self.game)} lamps: '
        lamps = self.pinmame.get_lamps()
        for idx in self.switch_matrix_indexes[self.game.parent.platform]:
            # if idx not in {28, 35, 37, 38, 36}: continue
            # if idx not in {47, 27, 43, 34, 25, 41, 53, 32, 21, 57, 51, 18}: continue  # indiana jones
            # if idx not in {77, 76, 75, 74, 73, 72, 71}: continue  # black rose
            if idx in lamps:
                r += str(idx)
            else:
                r += ' '*len(str(idx))
            r += ' '
        logging.info(r)
        return r

    def _switch_for_key(self, ch: str) -> Optional[int]:
        try:
            return self.switch_matrix_indexes[self.game.parent.platform][self._SNAPSHOTTER_CHARS.index(ch)]
        except (ValueError, IndexError):
            return None

    def on_state_update(self, solenoid, state):
        try:
            if state:
                self.active_solenoids.add(solenoid)
            else:
                self.active_solenoids.remove(solenoid)
            all_solenoids = ['  ']* (max(self.active_solenoids or {0})+1)
            for solenoid in self.active_solenoids:
                all_solenoids[solenoid] = str(solenoid).rjust(2)
            # self.log.info('solenoids: %s', ' '.join(all_solenoids))
        except:
            self.log.error('error getting solenoid label', exc_info=True)