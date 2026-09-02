#!/usr/bin/env python

"""
screens.py — DMD menu screens

Three small screens share a display/button/text-rendering substrate:

  Screen              — base class: TextRender frame, show(), scroll helpers
  PlayerLoginScreen    — recency-ordered player strip; delegates to...
  InitialsEntryScreen  — fixed on-screen keyboard grid for a new player
  LoginSession         — context manager wrapping PlayerLoginScreen.run()

GameSelectScreen (the game/video-mode list) also subclasses Screen, but
lives in game_selector.py since it owns a fair amount of its own
game-loading logic that has nothing to do with login.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from button import ButtonInput, NavEvent
from dmd_display import DMDDisplay
from players import PlayerStore
from text_to_dmd import TextRender

from vm_types import ScreenState

# ---------------------------------------------------------------------------
# Screen — shared substrate
# ---------------------------------------------------------------------------

class Screen:
    """
    Shared substrate for DMD-driven menu screens.

    Owns the TextRender frame and the scroll-easing helpers used by any
    screen that has more content than fits on the panel at once
    (PlayerLoginScreen, GameSelectScreen). InitialsEntryScreen doesn't
    scroll — every key is already visible, only the highlighted cell
    changes — so it simply doesn't call scroll_by()/animate_scroll_toward().
    """

    def __init__(self, display: DMDDisplay, buttons: ButtonInput) -> None:
        self.display = display
        self.buttons = buttons
        self.text = TextRender(width=display.width, height=display.height, depth=2)
        self.log = logging.getLogger(type(self).__name__)

        self._selected_index = 0
        self._scroll = [0, 0]
        self._timeout = None

    def show(self) -> None:
        self.display.show_frame(self.text.frame)

    def scroll_by(self, move: int, max: int) -> bool:
        if move == -1 and self._selected_index > 0:
            self._selected_index += move
            return True
        elif move == 1 and self._selected_index < max - 1:
            self._selected_index += move
            return True
        return False

    def animate_scroll_toward(self, x: int, y: int) -> bool:
        xy = x, y
        moved = False
        for i in range(2):
            if self._scroll[i] != xy[i]:
                diff = (self._scroll[i] - xy[i]) // 2
                if abs(diff) >= 1:
                    self._scroll[i] -= int(diff)
                else:
                    self._scroll[i] = xy[i]

                if abs(self._scroll[i] - xy[i]) < 1:
                    self._scroll[i] = xy[i]
                moved = True
        return moved

    TIMEOUT = 30
    def timeout(self, force=False) -> bool:
        now = time.monotonic()
        if force: self._timeout = now - self.TIMEOUT
        if self._timeout is None:
            self._timeout = now
        if self._timeout + self.TIMEOUT <= now:
            return True
        else:
            return False

    def reset_timeout(self):
        was_timed_out = self.timeout()
        self._timeout = time.monotonic()
        return not was_timed_out

class GenericMessage(Screen):
    def __call__(self, message: str, return_value: ScreenState):
        def run(ctx):
            font = 15
            end_time = time.monotonic() + 5
            while time.monotonic() < end_time:
                self.text.draw_text(
                    text = message,
                    font = font,
                    x = self.text.width//2,
                    y = self.text.height//2 - font//2,
                    color = 0,
                    outline = True,
                    outline_color = 3,
                    center = True,
                    kerning = 5
                )
                if ctx.err:
                    self.text.draw_text(
                        text = ctx.err,
                        font = 5,
                        x = self.text.width//2,
                        y = self.text.height//2 + font//2 + 2,
                        color = 3,
                        center = True,
                        minx = 0
                    )
                self.show()
                time.sleep(0.4)
                self.text.clear()
                self.show()
                time.sleep(0.1)

            ctx.err = None
            return return_value
        return run
