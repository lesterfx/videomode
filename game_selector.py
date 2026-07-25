#!/usr/bin/env python3

import dataclasses
from itertools import count
import json
import logging
from operator import attrgetter, itemgetter
import time
from typing import Optional

from vm_types import GameEntry, GameParent, EndDetectorConfig
from button import ButtonName, ButtonInput, ButtonEvent
from dmd_display import DMDDisplay
from text_to_dmd import TextRender

# ---------------------------------------------------------------------------
# Phase 4 — Game selector UI (stub)
# ---------------------------------------------------------------------------

class GameSelector:
    """
    Displays the sorted game list on the DMD and handles navigation.

    Responsibilities:
      - Parse games.json into game objects
      - Render scrollable list via DMDDisplay.show_text()
      - Handle SCROLL_UP / SCROLL_DOWN / LUANCH from ButtonInput
      - Return the selected GameEntry

    Populated in Phase 4.
    """

    def __init__(self, display: DMDDisplay, buttons: ButtonInput) -> None:
        self.log = logging.getLogger('GameSelector')
        self.display = display
        self.buttons = buttons
        self._parents: list[GameParent] = []
        self._games: list[GameEntry] = []
        self._scroll = 0
        self._selected_index = 0

    def load_games(self, allow_no_snapshot: bool=False, only_without_screenshot: bool=False) -> None:
        entries = json.load(open('games.json'))
        entries.sort(key=itemgetter('name'))
        for entry in entries:
            videomodes = entry.pop('videomodes', [])
            end_cfg = entry.pop('end_detector_config', {})
            entry['end_detector_config'] = EndDetectorConfig(**end_cfg)
            parent = GameParent(**entry)
            if parent.screenshot and only_without_screenshot:
                self.log.warn(f'already have screenshot for: {parent.name.replace("\n", " ")}')
                continue
            if not parent.rom:
                self.log.warn(f'NO ROM FOR GAME: {parent.name.replace("\n", " ")}')
                continue
            if not videomodes:
                self.log.warn(f'NO VIDEO MODES CONFIGURED: {parent.name.replace("\n", " ")}')
            for videomode in videomodes:
                game = GameEntry(parent=parent, **videomode)
                if not game.snapshot_index and not allow_no_snapshot:
                    self.log.warn(f'VIDEO MODE HAS NO SNAPSHOT INDEX: {parent.name.replace("\n", " ")} - {game.name.replace("\n", " ")}')
                    continue
                elif not only_without_screenshot and allow_no_snapshot and game.snapshot_index:
                    continue
                parent.children.append(game)
            if not parent.children:
                continue
            self._parents.append(parent)
            parent.children.sort(key=attrgetter('name'))
            self._games.extend(parent.children)
        y = 0
        for parent in self._parents:
            # self.log.info(f'{y} {parent.name}')
            parent.y = y
            y += 8 * len(parent.name.splitlines())
            for game in parent.children:
                game.y = y
                # self.log.info(f'{y} {game.name or "-"}')
                y += 6 * len((game.name + ' ').splitlines())

    def run(self, snapshotter=False, screenshotter=False) -> GameEntry:
        """
        Block until the user selects a game.
        Returns the chosen GameEntry.
        """

        if snapshotter:
            title = 'SNAPSHOTTING'
        elif screenshotter:
            title = 'SCREENSHOTTING'
        else:
            title = None

        need_render = True
        pressed = []
        pressed_at = time.monotonic()

        def left_pressed():
            if self._selected_index > 0:
                self._selected_index -= 1
                need_render = True

        def right_pressed():
            if self._selected_index < len(self._games)-1:
                self._selected_index += 1
                need_render = True

        while True:
            if need_render:
                self.draw_frame(title)
                need_render = False

            now = time.monotonic()
            event = self.buttons.poll(timeout=0.1)
            if event:
                if event.pressed:
                    pressed.append(event.button)
                    pressed_at = now
                else:
                    if event.button in pressed:
                        pressed.remove(event.button)
            if pressed and now >= pressed_at + .3:
                pressed_at = now
                button = pressed.pop(0)
                event = ButtonEvent(button, True)
                pressed.append(button)
            if event and event.pressed:
                if event.button is ButtonName.LEFT_FLIPPER:
                    left_pressed()
                elif event.button is ButtonName.RIGHT_FLIPPER:
                    right_pressed()
                elif event.button is ButtonName.LAUNCH:
                    selected_game = self._games[self._selected_index]
                    self.draw_loading(selected_game)
                    return selected_game
                else:
                    self.log.error('unexpected event', event)

            if self._scroll != self._games[self._selected_index].y:
                diff = (self._scroll-self._games[self._selected_index].y) // 2
                if abs(diff) >= 1:
                    self._scroll -= int(diff)
                else:
                    self._scroll = self._games[self._selected_index].y

                if abs(self._scroll-self._games[self._selected_index].y) < 1: self._scroll = self._games[self._selected_index].y
                need_render = True

    def draw_loading(self, game):
        if screenshot := game.parent.screenshot:
            self.display.show_frame(bytes(int(ch) for ch in screenshot))
            return
        text = TextRender(width=128, height=32, depth=2)
        text.draw_text(
            text='LOADING GAME',
            y = 0,
            x = 30,
            font_size = 7,
            highlight = False
        )
        for i, line in  enumerate(game.parent.name.splitlines()):
            text.draw_text(
                text=line,
                y = 12+i*8,
                x = 0,
                font_size = 7,
                highlight = True
            )
        text.draw_text(
            text=game.name,
            y = 18,
            x = 0,
            font_size = 7,
            highlight = False
        )
        text.draw_text(
            text='NEED SCREENSHOT',
            y = 24,
            x = 25,
            font_size = 7,
            highlight = False
        )
        self.display.show_frame(text.frame)

    def draw_frame(self, title:Optional[str] = None):
        text = TextRender(width=128, height=32, depth=2)

        for parent in self._parents:
            highlighted_child = False
            for game in parent.children:
                highlight = (game is self._games[self._selected_index])
                highlighted_child = highlighted_child or highlight
                for i, line in  enumerate(game.name.splitlines()):
                    text.draw_text(
                        text = str(line).upper(),
                        y = game.y+6*i - self._scroll + 16,
                        x = 6 if i else 4,
                        # box_y = y,
                        # box_b = details_end-1,
                        font_size = 5,
                        highlight = highlight
                    )
                if game.initials:
                    text.draw_text(
                        text = str(game.initials),
                        y = game.y - self._scroll + 16,
                        right = True,
                        x = 127,
                        # box_y = y,
                        # box_b = details_end-1,
                        font_size = 5,
                        highlight = highlight
                    )
                text.draw_text(
                    text = str(game.high_score or 0),
                    y = game.y - self._scroll + 16,
                    right = True,
                    x = 127-18,
                    # box_y = y,
                    # box_b = details_end-1,
                    font_size = 5,
                    highlight = highlight
                )
            for i, line in enumerate(parent.name.splitlines()):
                text.draw_text(
                    text = line,
                    y = parent.y+8*i - self._scroll + 16,
                    x = 2 if i else 0,
                    highlight = highlighted_child
                )

            # text.invert(0, parent.y - self._scroll, 128, 9)

        if title:
            text.draw_text(
                text = title,
                right=True,
                y = 0,
                x = 127,
                font_size = 5,
                highlight = True,
                background = True
            )

        self.display.show_frame(text.frame)

