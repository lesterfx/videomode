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

import logging
import select
import sys
import termios
import tty
from typing import Optional

from bridge import PinMAMEBridge
from dmd_display import DMDDisplay
from button import ButtonInput
from vm_types import GameEntry, ScreenState, SessionContext, Arrow

_ARROW_MAP = {
    'A': Arrow.UP,
    'B': Arrow.DOWN,
    'C': Arrow.RIGHT,
    'D': Arrow.LEFT,
}

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
        self.display.snapshotting = not screenshotting
        self.active_solenoids = set()
        self.log      = logging.getLogger("Snapshotter")

        self.switch_matrix_indexes: dict[str, tuple[int, ...]] = {
            'wpc': (
                1,2,3,4,5,6,7,8,
                11, 21, 31, 41, 51, 61, 71, 81,
                12, 22, 32, 42, 52, 62, 72, 82,
                13, 23, 33, 43, 53, 63, 73, 83,
                14, 24, 34, 44, 54, 64, 74, 84,
                15, 25, 35, 45, 55, 65, 75, 85,
                16, 26, 36, 46, 56, 66, 76, 86,
                17, 27, 37, 47, 57, 67, 77, 87,
                18, 28, 38, 48, 58, 68, 78, 88,
                112,114

            ),
            'sega': (
                1, 9,  17, 25, 33, 41, 49, 57,
                2, 10, 18, 26, 34, 42, 50, 58,
                3, 11, 19, 27, 35, 43, 51, 59,
                4, 12, 20, 28, 36, 44, 52, 60,
                5, 13, 21, 29, 37, 45, 53, 61,
                6, 14, 22, 30, 38, 46, 54, 62,
                7, 15, 23, 31, 39, 47, 55, 63,
                8, 16, 24, 32, 40, 48, 56, 64,

                -6, -7
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
            ),
            'stern': (
                1, 9,  17, 25, 33, 41, 49, 57,
                2, 10, 18, 26, 34, 42, 50, 58,
                3, 11, 19, 27, 35, 43, 51, 59,
                4, 12, 20, 28, 36, 44, 52, 60,
                5, 13, 21, 29, 37, 45, 53, 61,
                6, 14, 22, 30, 38, 46, 54, 62,
                7, 15, 23, 31, 39, 47, 55, 63,
                8, 16, 24, 32, 40, 48, 56, 64,
            ),
        }
        self.switch_matrix_cols: dict[str, int] = {
            'wpc': 8,
            'sega': 8,
            'gottlieb': 8,
            'stern': 8
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
        for switch in self.game.parent.snapshot_startup_switches:
            self.active_switches.add(switch)
        # self.display.label_getter = self.get_label

        self.log.info("\nSnapshotter mode — navigate to video mode then press Enter.")
        self.log.info("  |  Enter = snapshot  |  Ctrl-C = abort")
        r = ''
        for i, idx in enumerate(self.switch_matrix_indexes[self.game.parent.platform]):
            if not (i % self.switch_matrix_cols[self.game.parent.platform]) and r:
                self.log.info(r)
                r = ''
            r += f'{idx:>3}-{self._SNAPSHOTTER_CHARS[i]} '
        self.log.info(r)

        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            self._read_key()

            for sw in self.active_switches:
                self.pinmame.send_switch(sw, True)

            while True:
                ch = self._read_key()

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

                self.show_label(self.get_label())

                # Switch toggle
                if isinstance(ch, str):
                    sw = self._switch_for_key(ch)
                    if sw is not None:
                        self.switch(sw)
                    elif ch == ' ':
                        self.display.CROP_TO_FIT = not self.display.CROP_TO_FIT
                        self.display.redraw()
                elif isinstance(ch, Arrow):
                    pan = self.display.pan(ch)
                    self.log.info('pan: %d %d', *pan)

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

    def switch(self, sw: int, state:bool|None=None):
        if state is None:
            state = sw not in self.active_switches
        if state:
            self.active_switches.add(sw)
            self.pinmame.send_switch(sw, True)
        else:
            self.active_switches.discard(sw)
            self.pinmame.send_switch(sw, False)

    def _read_key(self) -> Optional[str|Arrow]:
        # return sys.stdin.read(1)
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)  # 50ms poll
        if not ready:
            return None
        ch = sys.stdin.read(1)
        self.log.info(ch)
        if ch != '\x1b':
            return ch

        # Possible escape sequence — arrow keys send ESC [ <letter>.
        # Give it a short window to arrive; if nothing follows, it was a bare Escape.
        while not select.select([sys.stdin], [], [], 0.2)[0]:
            pass
        ch2 = sys.stdin.read(1)

        if ch2 != "[":
            self.log.warning('received escape code without [, not an arrow')
            return "\x1b"  # not an arrow sequence — treat as bare Escape

        while not select.select([sys.stdin], [], [], 0.2)[0]:
            pass
        ch3 = sys.stdin.read(1)

        return _ARROW_MAP.get(ch3, "\x1b")  # unmapped final byte → treat as Escape

    def show_label(self, label: str):
        lines = len(label.split('\n'))
        sys.stdout.write(f"\x1b[{lines}A\x1b[J")
        print(label)
    
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
        r = 'switches:\r\n'
        for i, idx in enumerate(self.switch_matrix_indexes[self.game.parent.platform]):
            if not (i % self.switch_matrix_cols[self.game.parent.platform]): r += '\r\n'
            if idx in self.active_switches:
                r += self._SNAPSHOTTER_CHARS[i]
            else:
                r += ' '
            r += '  '
        r += '\r\n'
        return r

    def _get_lamps_label(self):
        r = f'lamps:\r\n'
        lamps = self.pinmame.get_lamps()
        for i, idx in enumerate(self.switch_matrix_indexes[self.game.parent.platform]):
            if not (i % self.switch_matrix_cols[self.game.parent.platform]): r += '\r\n'
            # if idx not in {28, 35, 37, 38, 36}: continue
            # if idx not in {47, 27, 43, 34, 25, 41, 53, 32, 21, 57, 51, 18}: continue  # indiana jones
            # if idx not in {77, 76, 75, 74, 73, 72, 71}: continue  # black rose
            if idx in lamps:
                r += str(idx).center(3)
            else:
                r += '   '
            r += '  '
        r += '\r\n'
        return r

    def _switch_for_key(self, ch: str) -> Optional[int]:
        try:
            return self.switch_matrix_indexes[self.game.parent.platform][self._SNAPSHOTTER_CHARS.index(ch)]
        except (ValueError, IndexError):
            self.log.info('no switch assigned to %s', ch)
            return None

    def on_state_update(self, solenoid, state):
        try:
            if state:
                self.active_solenoids.add(solenoid)
            else:
                self.active_solenoids.remove(solenoid)
            all_solenoids = ['  ']* (max(self.active_solenoids or {0})+1)
            for a_solenoid in self.active_solenoids:
                all_solenoids[a_solenoid] = str(a_solenoid).rjust(2)
            self.log.info('solenoids: %s', ' '.join(all_solenoids))
            if state:
                self.auto_switch(solenoid)
        except:
            self.log.error('error getting solenoid label', exc_info=True)

    def auto_switch(self, solenoid):
        strsolenoid = str(solenoid)  # json requires string keys
        if strsolenoid not in self.game.parent.auto_switches:
            self.log.info(f'solenoid {strsolenoid} has no autoswitches')
            return
        autoswitches = self.game.parent.auto_switches[strsolenoid]
        if not autoswitches: return
        labels = []
        for switch, state in autoswitches:
            # self.log.info(f'solenoid {strsolenoid} turned switch {switch} {state}')
            self.switch(switch, state)
            label = self._SNAPSHOTTER_CHARS[self.switch_matrix_indexes[self.game.parent.platform].index(switch)]
            if state:
                label = f'[{label} on]'
            else:
                label = f'[{label} off]'
            labels.append(label)
        labels_str = ' '.join(labels)
        if comment := self.game.parent.auto_switches.get(strsolenoid+'_'):
            labels_str += ' ' + str(comment)
        self.log.info(f'solenoid # {strsolenoid} switches %s', labels_str)
