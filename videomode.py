#!/usr/bin/env python

"""
pinmame_player.py — PinMAME Video Mode Player
Main orchestration module for Raspberry Pi 3B

Architecture overview:
  Phase 1: PinMAMEBridge    — libpinmame.so ctypes wrapper
  Phase 2: DMDDisplay       — physical DMD hardware driver
  Phase 3: ButtonInput      — GPIO button event loop
  Phase 4: GameSelector     — game list UI on DMD
  Phase 5: (offline tooling)— snapshot creation, not imported here
  Phase 6: VideoModeSession — load snapshot, run emulation, pass input
  Phase 7: EndDetector      — poll PinMAME state for video mode end
  Phase 8: ScoreStore       — capture score, persist, display result
  Phase 9: (systemd unit)   — boot integration, not imported here

Button mapping (physical → logical):
  GPIO_PIN_LEFT  → LEFT_FLIPPER   (left flipper)
  GPIO_PIN_RIGHT → RIGHT_FLIPPER  (right flipper)
  GPIO_PIN_LAUNCH  → LAUNCH       (launch / select)
"""

import argparse
import logging
from pathlib import Path

from bridge import PinMAMEBridge
from button import ButtonEvent, ButtonInput
from dmd_display import DMDDisplay
from game_selector import GameSelector
from rom_session import VideoModeSession
from snapshotter import Snapshotter
from end_detector import EndDetector
from score_store import ScoreStore
import vm_types

# ---------------------------------------------------------------------------
# Configuration — edit these to match your hardware and paths
# ---------------------------------------------------------------------------

LIBPINMAME_PATH   = Path.home() / "pinmame" / "build" / "libpinmame.so"
ROM_DIR           = Path.home() / ".pinmame" / "roms"
SNAPSHOT_DIR      = Path.home() / ".pinmame" / "snapshots"
SCORE_DB_PATH     = Path.home() / ".pinmame" / "scores.json"

DMD_WIDTH         = 128  # pixels
DMD_HEIGHT        = 32   # pixels

LOG_LEVEL         = logging.DEBUG

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="pinmame video mode player")
    p.add_argument("--snapshotter", action="store_true",
                   help="Run games from boot in order to save snapshot")
    p.add_argument("--screenshotter", action="store_true",
                   help="Run games from boot in order to save screenshot")
    return p.parse_args()



# ---------------------------------------------------------------------------
# Main application loop
# ---------------------------------------------------------------------------

class PinMAMEPlayer:
    """
    Top-level orchestrator.

    Boot sequence:
      1. Initialise all subsystems
      2. Show game selector → user picks a game
      3. Run video mode session
      4. Record score, show result
      5. Return to game selector (loop forever)
    """

    def __init__(self) -> None:
        args = parse_args()
        self.snapshotting = args.snapshotter
        self.screenshotting = args.screenshotter

        logging.basicConfig(filename='videomode.log',
                            filemode='w',
                            format='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging.INFO)
        self.log = logging.getLogger("PinMAMEPlayer")

        self.pinmame  = PinMAMEBridge()
        self.display  = DMDDisplay()
        self.buttons  = ButtonInput()
        self.detector = EndDetector(self.pinmame)
        if self.snapshotting or self.screenshotting:
            self.session = Snapshotter(
                self.pinmame,
                self.display,
                self.buttons,
                self.screenshotting
            )
        else:
            self.session = VideoModeSession(
                self.pinmame,
                self.display,
                self.buttons,
                self.detector
            )
        self.selector = GameSelector(self.display, self.buttons)
        self.scores   = ScoreStore(self.display)

    def startup(self) -> None:
        self.log.info("Starting up")
        self.pinmame.connect()
        self.buttons.start()   # events queued internally; callers use poll()
        self.selector.load_games(self.snapshotting or self.screenshotting, self.screenshotting)

    def shutdown(self) -> None:
        self.log.info("Shutting down")
        self.pinmame.stop()
        self.buttons.stop()
        self.display.shutdown()

    def run(self) -> None:
        self.startup()
        try:
            while True:
                game = self.selector.run(self.snapshotting, self.screenshotting)
                try:
                    result = self.session.run(game)
                except KeyboardInterrupt:
                    continue
                if not self.snapshotting and not self.screenshotting:
                    self.scores.record(result)
        except KeyboardInterrupt:
            self.log.info("KeyboardInterrupt — exiting")
        finally:
            self.shutdown()


if __name__ == "__main__":
    PinMAMEPlayer().run()
