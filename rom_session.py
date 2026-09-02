import logging
import sys
import termios
import tty
import time
from typing import Optional

from bridge import PinMAMEBridge
from dmd_display import DMDDisplay
from button import ButtonInput, ButtonEvent, ButtonName
from vm_types import GameEntry, SessionContext, ScreenState
from end_detector import EndDetector, EndDetectorTimedOut



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
        ctx: SessionContext
    ) -> ScreenState:
        """
        Load snapshot (or free-run) and play until end detected.
 
        Args:
            game:        Game to run.
            snapshotter: If provided, skip snapshot load and enter
                         interactive keyboard mode for snapshot capture.
                         Call signature: snapshotter() → None.
 
        """
        game = ctx.game
        self.log.info('disabling dmd')
        # self.pinmame.dmd_callback = self.display.show_frame
        self.pinmame.dmd_callback = lambda x, y=0: None # self.log.info('discarding frame')
        assert game.parent.rom, f'{game.parent} has no rom defined - {game.parent.rom}'
        assert game.snapshot_index, f'{game} has no snapshot - {game.snapshot_index}'
        self.pinmame.load_game(game.parent.rom)

        try:
            self.display.set_bit_depth(game.parent.bit_depth)
            self.detector.reset(game.parent.end_detector_config, active=False)
            self.load_snapshot(game.snapshot_index)

            start_time = time.monotonic()
            start_score = 0

            while time.monotonic() < start_time + 10:
                for switch in game.parent.active_switches:
                    self.pinmame.send_switch(switch, True)
                time.sleep(0.1)
                score_now = self.pinmame.get_score()
                # self.log.info('start_score is %s', start_score)
                if score_now is not None:
                    start_score = score_now
                    if time.monotonic() < start_time + 3:
                        continue
                    break
            else:
                raise ValueError('NO START SCORE AFTER 10 SECONDS')

            self.log.info('start score: %d', start_score)

            # Wire DMD frames to the physical display for both modes.
            self.log.info('setting up dmd for real now')
            self.pinmame.dmd_callback = self.display.show_frame
            self.display.label_getter = self.score_label_getter
            self.detector.reset(game.parent.end_detector_config)

            self.log.debug("Entering normal play loop")
    
            score = None

            while True:

                # --- end detection ------------------------------------------
                if self.detector.ended:
                    self.log.info("EndDetector signalled end of video mode")
                    end_time = time.monotonic()
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

            self.pinmame.dmd_callback = lambda x, y=0: self.log.info('discarding frame')
            self.display.clear()

            while time.monotonic() < end_time + 5:
                self.log.info('waiting for the end, score is %s', self.pinmame.get_score())
                time.sleep(0.1)

        except EndDetectorTimedOut:
            self.log.error('game timed out. fix configuration, or increase timeout')
            ctx.err = 'VIDEO MODE TIMEOUT'
            return ScreenState.GAME_FAILED
        except Exception as e:
            ctx.err = str(e)
            self.log.error('game error', exc_info=True)
            return ScreenState.GAME_FAILED

        finally:
            self.display.set_bit_depth(2)
            end_score = self.pinmame.get_score()
            self.pinmame.stop()

        if start_score is not None and end_score is not None:
            score = end_score - start_score

        duration = end_time - start_time
        self.log.info("Session ended (sol %d) — score=%s duration=%.1fs",
            self.detector.triggering_solenoid,
            score,
            duration
        )
 
        ctx.game = game
        ctx.score = score
        return ScreenState.GAME_COMPLETED

    def score_label_getter(self):
        return f'score: {self.pinmame.get_score()}'

    def load_snapshot(self, index: int):
        self.pinmame.load_snapshot(index)

def was_game_high_score(ctx: SessionContext) -> ScreenState:
    return ScreenState.SAVE_HIGH_SCORE
    return ScreenState.NO_HGIH_SCORE