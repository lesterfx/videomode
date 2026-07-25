import logging
import sys
import termios
import tty
import time
from typing import Optional

from bridge import PinMAMEBridge
from dmd_display import DMDDisplay
from button import ButtonInput, ButtonEvent, ButtonName
from vm_types import GameEntry, VideoModeResult



class VideoModeSession:
    """
    Runs one video mode play-through.
 
    Normal mode  (snapshotter=None):
      - Restores game state from GameEntry.snapshot_path
      - Wires DMD frames → DMDDisplay.show_frame()
      - Polls ButtonInput and injects GPIO events into the switch matrix
      - Exits when EndDetector signals the mode has ended
     """
 
    def __init__(
        self,
        pinmame:  PinMAMEBridge,
        display:  DMDDisplay,
        buttons:  ButtonInput,
        detector: "EndDetector"
    ) -> None:
        self.pinmame  = pinmame
        self.display  = display
        self.buttons  = buttons
        self.detector = detector
        self.log      = logging.getLogger("VideoModeSession")
 
    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
 
    def run(
        self,
        game: GameEntry
    ) -> VideoModeResult:
        """
        Load snapshot (or free-run) and play until end detected.
 
        Args:
            game:        Game to run.
            snapshotter: If provided, skip snapshot load and enter
                         interactive keyboard mode for snapshot capture.
                         Call signature: snapshotter() → None.
 
        Returns:
            VideoModeResult with score populated from PinMAMEBridge,
            or score=0 / ended_naturally=False in snapshotter mode.
        """
        # Wire DMD frames to the physical display for both modes.
        self.pinmame.dmd_callback = self.display.show_frame
        self.pinmame.load_game(game.parent.rom)

        for switch in game.parent.active_switches:
            self.pinmame.send_switch(switch, True)

        self.detector.reset(game.parent.end_detector_config, active=False)
        self.load_snapshot(game.snapshot_index)
        self.detector.reset(game.parent.end_detector_config)

        start = time.monotonic()
        self.log.debug("Entering normal play loop")
 
        try:
            while True:
                # --- end detection ------------------------------------------
                if self.detector.ended:
                    self.log.info("EndDetector signalled end of video mode")
                    break
 
                # --- button input -------------------------------------------
                event = self.buttons.poll(timeout=0.05)
                if event:
                    if event.button is ButtonName.LEFT_FLIPPER:
                        if game.parent.left_flipper_switch is None:
                            raise AttributeError('Left Flipper Switch is not defined')
                        self.log.info(f'left flipper [{game.parent.left_flipper_switch}] {event.pressed}')
                        self.pinmame.send_switch(game.parent.left_flipper_switch, event.pressed)
                    elif event.button is ButtonName.RIGHT_FLIPPER:
                        if game.parent.right_flipper_switch is None:
                            raise AttributeError('Right Flipper Switch is not defined')
                        self.log.info(f'right flipper [{game.parent.right_flipper_switch}] {event.pressed}')
                        self.pinmame.send_switch(game.parent.right_flipper_switch, event.pressed)
                    elif event.button is ButtonName.LAUNCH:
                        if game.parent.launch_switch is None:
                            raise AttributeError('Launch Switch is not defined (or 0)')
                        elif game.parent.launch_switch:
                            self.log.info(f'launch [{game.parent.launch_switch}] {event.pressed}')
                            self.pinmame.send_switch(game.parent.launch_switch, event.pressed)
 
        finally:
            self.pinmame.stop()
 
        duration = time.monotonic() - start
        scores   = self.pinmame.get_scores()
        score    = scores[0] if scores else 0
        self.log.info("Session ended (sol %d) — score=%d duration=%.1fs",
            self.detector.triggering_solenoid,
            score,
            duration
        )
 
        return VideoModeResult(
            game=game,
            score=score,
            duration_seconds=duration,
            ended_naturally=self.detector.ended,
        )

    def load_snapshot(self, index: int):
        self.pinmame.load_snapshot(index)
