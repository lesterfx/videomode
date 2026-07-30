#!/usr/bin/env python3

import dataclasses
from itertools import count
import json
import logging
from operator import attrgetter, itemgetter
from random import choice
import string
import time
from typing import Optional

from vm_types import GameEntry, GameParent, EndDetectorConfig
from button import ButtonName, ButtonInput, ButtonEvent
from dmd_display import DMDDisplay
from text_to_dmd import TextRender
from players import PlayerStore

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
        self._scroll = [0, 0]
        self._selected_index = 0
        self.text = TextRender(width=128, height=32, depth=2)
        self.players = PlayerStore()
        self.initials = None

    def load_games(self, allow_no_snapshot: bool=False, only_without_screenshot: bool=False) -> None:
        self.screenshots = {key: bytes(int(ch) for ch in screenshot) for key, screenshot in json.load(open('screenshots.json')).items() if screenshot}

        entries = json.load(open('games.json'))
        entries.sort(key=itemgetter('name'))
        for entry in entries:
            videomodes = entry.pop('videomodes', [])
            end_cfg = entry.pop('end_detector_config', {})
            entry['end_detector_config'] = EndDetectorConfig(**end_cfg)
            parent = GameParent(**entry)
            if only_without_screenshot and self.screenshots.get(parent.rom):
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

    def log_in(self):
        SEPARATION = 31
        users = []
        users.append((0, 'guest'))
        for i, initials in enumerate(self.players.get_players() + ['new']):
            users.append((int(SEPARATION*(i+1.3)), initials))
        wrap_width = users[-1][0] + SEPARATION + 10
        self._selected_index = 0
        self._scroll = [0, 100]

        for move in self.get_key_presses():
            self._selected_index += move
            wrap_count, index = divmod(self._selected_index, len(users))
            if self.animate_scroll_toward(wrap_width*wrap_count + users[index][0], 0):
                need_render = True

            self.text.clear()
            self.text.box(0, 0, 128, 16, lambda:choice((1, 2)))
            self.text.draw_text(
                'Select player',
                center = True,
                x = 64,
                y = 2-self._scroll[1],
                font = 12,
                color = 3,
                outline = True,
                kerning = 1
            )
            for i, (x, initials) in enumerate(users):
                self.text.draw_text(
                    initials,
                    center = True,
                    x = (int(64 + x - self._scroll[0]+wrap_width//4) % wrap_width) - wrap_width//4,
                    y = 17 + self._scroll[1],
                    font = 15,
                    color = 3 if (i==index) else 1
                )
            self.show()
        
        self._scroll = [0, 0]
        initials = users[self._selected_index % len(users)][1]
        if initials == 'new':
            initials = self.get_initials('NEW PLAYER')

        self._selected_index = 0
        self.initials = initials

    def get_initials(self, title):
        selected_row = 0
        selected_col = 0
        cols = 7
        options = []
        for i, ch in enumerate(string.ascii_uppercase + '\r\t'):
            row, col = divmod(i, cols)
            option = {}
            options.append(option)
            option['ch'] = ch
            option['x'] = 15 - row*5 + col*7
            option['y'] = 1 + row*6 + col
            option['i'] = i
            if ch == '\t':
                option['x'] += 1
                option['y'] += 1

        initials = ''

        def draw():
            self.text.clear()

            for option in options:
                if option['i'] == selected_index:
                    color = 0
                    outline = 1
                    outline_color = 3
                else:
                    color = 2
                    outline = 0
                    outline_color = 0

                self.text.draw_text(
                    text = option['ch'],
                    y = option['y'],
                    x = option['x'],
                    font = 5,
                    color = color,
                    outline = outline,
                    outline_color = outline_color
                )
            
            if title:
                self.text.draw_text(
                    text = title,
                    y = 3,
                    x = 97,
                    font = 10,
                    center = True,
                    color = 2
                )

            for i, x in enumerate([85, 97, 109]):
                self.text.box(
                    x = x-4,
                    y = 26,
                    w = 9,
                    h = 2,
                    color = 2
                )
                if i == len(initials):
                    text = options[selected_index]['ch']
                elif i < len(initials):
                    text = initials[i]
                else:
                    text = ''
                if text in '\t\r':
                    text = ''
                self.text.draw_text(
                    text = text,
                    y = 14,
                    x = x,
                    center = True,
                    font = 15,
                    color = 3
                )
            self.show()

        while True:
            for move in self.get_key_presses():
                if len(initials) < 3:
                    if move == 1:
                        selected_col = (selected_col + 1) % cols
                        if (selected_col + selected_row*cols) >= len(options):
                            selected_col = 0
                    elif move == -1:
                        selected_row += 1
                        if (selected_col + selected_row*cols) >= len(options):
                            selected_row = 0
                elif move:
                    selected_row = 3
                    selected_col = 11-selected_col
                selected_index = selected_col + selected_row*cols
                draw()
            ch = options[selected_index]['ch']
            if ch == '\r':
                initials = initials[:-1]
            elif ch == '\t':
                break
            else:
                initials += ch
            if len(initials) == 3:
                selected_row = 3
                selected_col = 6

        return initials or 'guest'

    def show(self):
        self.display.show_frame(self.text.frame)

    def run(self, scores, snapshotter=False, screenshotter=False) -> GameEntry:
        """
        Block until the user selects a game.
        Returns the chosen GameEntry.
        """

        self.log.info('logged in as %s', self.initials)

        if snapshotter:
            title = 'MAKING ROM SNAPSHOT'
        elif screenshotter:
            title =  'SAVING SCREENSHOT'
        else:
            title = f'{self.initials} SELECT YOUR GAME'

        if self.initials == 'guest':
            initials = None
        else:
            initials = self.initials
        scores_for_player = scores.scores_for_player(initials)

        for game in self._games:
            game_score = None
            if score := scores_for_player.get(game.unique_name):
                game_score = score.score
                self.log.info('high score for %s is %s', game.unique_name, game_score)
                game.high_score = f'{game_score:,}'
                game.is_high_score = score.is_high_score
            else:
                self.log.info('no high score for %s in %s', game.unique_name, scores_for_player)
                game.high_score = 'NOT SCORED'
                game.is_high_score = False
        self.log.info(scores_for_player)

        need_render = True
        for move in self.get_key_presses():
            if True:
                self.draw_frame(title)
                need_render = False

            need_render = self.scroll_by(move, max=len(self._games))
            if self.animate_scroll_toward(0, self._games[self._selected_index].y):
                need_render = True

        selected_game = self._games[self._selected_index]
        self.draw_loading(selected_game)

        return selected_game

    def scroll_by(self, move: int, max: int) -> bool:
        if move == -1 and self._selected_index > 0:
            self._selected_index += move
            return True
        elif move == 1 and self._selected_index < max - 1:
            self._selected_index += move
            return True
        return False

    def animate_scroll_toward(self, x, y) -> bool:
        xy = x,y
        moved = False
        for i in range(2):
            if self._scroll[i] != xy[i]:
                diff = (self._scroll[i]-xy[i]) // 2
                if abs(diff) >= 1:
                    self._scroll[i] -= int(diff)
                else:
                    self._scroll[i] = xy[i]

                if abs(self._scroll[i]-xy[i]) < 1: self._scroll[i] = xy[i]
                moved = True
        return moved

    def get_key_presses(self) -> int:
        pressed = []
        pressed_at = time.monotonic()

        while True:
            move = 0
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
                    move -= 1
                elif event.button is ButtonName.RIGHT_FLIPPER:
                    move += 1
                elif event.button is ButtonName.LAUNCH:
                    break
                else:
                    self.log.error('unexpected event', event)
            yield move

    def draw_loading(self, game):
        if screenshot := self.screenshots.get(game.parent.rom):
            self.display.show_frame(screenshot)
            return

        self.text.clear()
        self.text.draw_text(
            text='LOADING GAME',
            y = 0,
            x = 30,
            center = True,
            font = 7,
            color = 2
        )
        for i, line in enumerate(game.parent.name.splitlines()):
            self.text.draw_text(
                text=line,
                y = 12+i*8,
                x = 0,
                center = True,
                font = 7,
                color = 3
            )
        self.text.draw_text(
            text=game.name.upper(),
            y = 18,
            x = 0,
            font = 7,
            color = 2
        )
        self.text.draw_text(
            text='NEED SCREENSHOT',
            y = 24,
            x = 25,
            font = 7,
            color = 2
        )
        self.show()

    def draw_frame(self, title:Optional[str] = None):
        self.text.clear()

        if title:
            box_y = 6
        else:
            box_y = 0
        OFFSET = 24
        for parent in self._parents:
            parent_color = 2
            for game in parent.children:
                color = 3 if (game is self._games[self._selected_index]) else 1
                parent_color = max(color, parent_color)
                for i, line in  enumerate(game.name.splitlines()):
                    self.text.draw_text(
                        text = str(line).upper(),
                        y = game.y+6*i - self._scroll[1] + OFFSET,
                        x = 6 if i else 4,
                        box_y = box_y,
                        # box_b = details_end-1,
                        font = 5,
                        color = color,
                        outline = True
                    )
                # if game.initials:
                #     self.text.draw_text(
                #         text = str(game.initials),
                #         y = game.y - self._scroll[1] + OFFSET,
                #         right = True,
                #         x = 127,
                #         # box_y = y,
                #         # box_b = details_end-1,
                #         font = 5,
                #         color = color
                #     )
                if game.is_high_score:
                    col = lambda:choice((2, color))
                else:
                    col = color
                self.text.draw_text(
                    text = str(game.high_score),
                    y = game.y - self._scroll[1] + OFFSET,
                    right = True,
                    x = 128,
                    box_y = box_y,
                    # box_b = details_end-1,
                    font = 5,
                    color = col
                )
            for i, line in enumerate(parent.name.splitlines()):
                self.text.draw_text(
                    text = line,
                    font = 10,
                    y = parent.y+8*i - self._scroll[1] + OFFSET,
                    x = 0,
                    box_y = box_y,
                    color = parent_color
                )

            # self.text.invert(0, parent.y - self._scroll[1], 128, 9)

        if title:
            # self.text.box(
            #     0, 0, 128, 6, 1
            # )
            self.text.draw_text(
                text = title.upper(),
                center=True,
                y = 0,
                x = 64,
                font = 5,
                color = 3
            )

        self.show()

