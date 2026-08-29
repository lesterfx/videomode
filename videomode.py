#!/usr/bin/env python3

"""
pinmame_player.py — PinMAME Video Mode Player
Main orchestration module for Raspberry Pi 3B

Architecture overview:
  Phase 1: PinMAMEBridge    — libpinmame.so ctypes wrapper
  Phase 2: DMDDisplay       — physical DMD hardware driver
  Phase 3: ButtonInput      — GPIO button event loop
  Phase 4: PlayerLoginScreen / GameSelectScreen — DMD menu screens
  Phase 5: (offline tooling)— snapshot creation, not imported here
  Phase 6: VideoModeSession — load snapshot, run emulation, pass input
  Phase 7: EndDetector      — poll PinMAME state for video mode end
  Phase 8: ScoreStore       — capture score, persist, display result
  Phase 9: (systemd unit)   — boot integration, not imported here

Button mapping (physical → logical):
  GPIO_PIN_LEFT  → LEFT_FLIPPER   (left flipper)
  GPIO_PIN_RIGHT → RIGHT_FLIPPER  (right flipper)
  GPIO_PIN_LAUNCH  → LAUNCH       (launch / select)

Login/selection flow:
  PinMAMEPlayer owns the PlayerStore directly (it's shared state that
  outlives any one screen) and hands it to PlayerLoginScreen, which owns
  InitialsEntryScreen internally as an implementation detail of "logging
  in". A LoginSession context manager scopes the `initials` value for a
  play session; from GameSelectScreen, chording both flippers (NavEvent.BOTH)
  returns None from run(), which is PinMAMEPlayer's cue to end the inner
  play loop and return to the login screen.
"""

import argparse
import contextlib
import logging
from pathlib import Path
import sys

from bridge import PinMAMEBridge
from button import ButtonInput
from dmd_display import DMDDisplay
from game_selector import GameSelectScreen
from settings_screen import SettingsScreen
from login import PlayerLoginScreen, Login
from players import PlayerStore
from rom_session import VideoModeSession
from snapshotter import Snapshotter
from end_detector import EndDetector
from high_scores import HighScoreStore
from settings import SettingsStore
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
      2. Log in (skipped in snapshotter/screenshotter mode) → initials
      3. Show game selector → user picks a game, or backs out to re-login
      4. Run video mode session
      5. Record score, show result
      6. Loop back to game selector (same login), until BOTH backs out
    """

    def __init__(self) -> None:
        args = parse_args()
        self.snapshotting = args.snapshotter
        self.screenshotting = args.screenshotter

        logging.basicConfig(
            format='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.INFO,
            filename='videomode.log',
            filemode='a'
        )
        self.log = logging.getLogger("PinMAMEPlayer")

        self.settings = SettingsStore()
        self.pinmame  = PinMAMEBridge()
        self.display  = DMDDisplay(width=DMD_WIDTH, height=DMD_HEIGHT, brightness=self.settings.get('brightness'))
        if self.display.hardware:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.DEBUG)
            stderr_handler.setFormatter(logging.getLogger().handlers[0].formatter)
            logging.getLogger().addHandler(stderr_handler)

        self.buttons  = ButtonInput()
        self.settings_screen = SettingsScreen(self.display, self.buttons, self.settings)
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

        self.players = PlayerStore()
        self.login = PlayerLoginScreen(self.display, self.buttons, self.players)
        self.game_select = GameSelectScreen(self.display, self.buttons)
        self.scores = HighScoreStore()

    def startup(self) -> None:
        self.log.info("Starting up")
        self.pinmame.connect()
        self.buttons.start()   # events queued internally; callers use poll()
        # self.game_select.load_games(self.snapshotting or self.screenshotting, self.screenshotting)
        self.game_select.load_games(True, self.screenshotting)

    def shutdown(self) -> None:
        self.log.info("Shutting down")
        self.pinmame.stop()
        self.buttons.stop()
        self.display.shutdown()

    def run(self) -> None:
        self.startup()
        try:
            while True:
                self.settings_screen.run()

                while True:
                    if self.snapshotting or self.screenshotting:
                        initials = None
                    elif self.settings.get('log in first'):
                        initials = self.login.run()
                        if initials is Login.BACK:
                            break
                    else:
                        initials = None

                    while True:
                        game = self.game_select.run(
                            self.scores, initials, self.snapshotting, self.screenshotting
                        )
                        if game is None:
                            # BOTH was pressed on the game list — back out
                            # to the login screen for a fresh initials pick.
                            break
                        try:
                            self.display.set_bit_depth(game.parent.bit_depth)
                            result = self.session.run(game)
                        except KeyboardInterrupt:
                            continue
                        except:
                            self.log.error('error in video mode', exc_info=True)
                            continue
                        finally:
                            self.display.set_bit_depth(2)
                        if self.snapshotting or self.screenshotting:
                            self.log.info('no player handling while snapshotting or screenshotting')
                            continue
                        if not initials:
                            self.log.info('no player handling for guest')
                            continue

                        # Only bump recency once the player has actually
                        # played something — logging in and backing out
                        # immediately shouldn't move them to the top.
                        self.players.add_player(initials)
                        self.scores.submit_score(result, initials)

        except KeyboardInterrupt:
            self.log.info("KeyboardInterrupt — exiting")
        finally:
            self.shutdown()


if __name__ == "__main__":
    PinMAMEPlayer().run()