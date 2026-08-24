#!/usr/bin/env python3

import json
import logging
from operator import attrgetter, itemgetter
from text_to_dmd import ColorRamp, RandomColor
from typing import Optional

from vm_types import GameEntry, GameParent, EndDetectorConfig
from button import ButtonInput, NavEvent
from dmd_display import DMDDisplay
from screens import Screen

# ---------------------------------------------------------------------------
# Phase 4 — Game selector UI
# ---------------------------------------------------------------------------

class GameSelectScreen(Screen):
    """
    Displays the sorted game list on the DMD and handles navigation.

    Responsibilities:
      - Parse games.json into game objects
      - Render scrollable list via DMDDisplay.show_frame()
      - Handle LEFT / RIGHT / SELECT from ButtonInput.get_key_presses()
      - Return the selected GameEntry (or None if BOTH was pressed — the
        caller's cue to fall back to the login screen)
    """

    def __init__(self, display: DMDDisplay, buttons: ButtonInput) -> None:
        super().__init__(display, buttons)
        self._parents: list[GameParent] = []
        self._games: list[GameEntry] = []

    def load_games(self, allow_no_snapshot: bool=False, only_without_screenshot: bool=False) -> None:
        self.screenshots = {key: bytes(int(ch) for ch in screenshot) for key, screenshot in json.load(open('screenshots.json')).items() if screenshot}

        entries = json.load(open('games.json'))
        for entry in entries:
            videomodes = entry.pop('videomodes', [])
            end_cfg = entry.pop('end_detector_config', {})
            entry['end_detector_config'] = EndDetectorConfig(**end_cfg)
            parent = GameParent(**entry)
            if only_without_screenshot and self.screenshots.get(parent.rom):
                self.log.warning(f'already have screenshot for: {parent}')
                continue
            if not parent.rom:
                self.log.warning(f'NO ROM FOR GAME: {parent}')
                continue
            if not videomodes:
                self.log.warning(f'NO VIDEO MODES CONFIGURED: {parent}')
            for i, videomode in enumerate(videomodes, 1):
                game = GameEntry(parent=parent, **videomode, snapshot_index=i)
                if not game.ready and not allow_no_snapshot:
                    self.log.warning(f'VIDEO MODE HAS NO SNAPSHOT INDEX: %s - %s', game.parent, game.snapshot_index)
                    continue
                elif not only_without_screenshot and allow_no_snapshot and game.ready:
                    continue
                parent.children.append(game)
            if not parent.children:
                continue
            self._parents.append(parent)
            parent.children.sort(key=attrgetter('name'))
            self._games.extend(parent.children)
        y = 0
        for parent in self._parents:
            parent.y = y
            y += 8 * len(parent.name.splitlines())
            for game in parent.children:
                game.y = y
                y += 6 * len((game.name + ' ').splitlines())

    @staticmethod
    def _format_game(score):
        unit = ''
        if score:
            for new_unit in 'KMB':
                new_score, remainder = divmod(score, 1000)
                if remainder:
                    break
                else:
                    unit = new_unit
                    score = new_score
        return f'{score:,}{unit}'

    def run(
        self,
        scores,
        initials: Optional[str],
        snapshotter: bool = False,
        screenshotter: bool = False,
    ) -> Optional[GameEntry]:
        """
        Block until the user selects a game.

        Returns the chosen GameEntry, or None if the person chorded both
        flippers (BOTH) — the caller's cue to return to the login screen.
        """

        self.log.info('selecting for %s', initials or 'guest')

        self.snapshotter = snapshotter
        self.screenshotter = screenshotter
        if self.snapshotter:
            title = 'MAKING ROM SNAPSHOT'
        elif self.screenshotter:
            title = 'SAVING SCREENSHOT'
        else:
            title = f'{initials or "guest"} SELECT YOUR GAME'

        scores_for_player = scores.scores_for_player(initials)

        for game in self._games:
            game_score = None
            if score := scores_for_player.get(game.unique_name):
                game_score = score.score
                game.high_score = self._format_game(game_score)
                game.is_high_score = score.is_high_score
            else:
                # self.log.info('no high score for %s in %s', game.unique_name, scores_for_player)
                game.high_score = '0'
                game.is_high_score = False
        self.log.info(f'scores for player: {scores_for_player}')

        self._selected_index = 0

        for event in self.buttons.get_key_presses():
            if event is NavEvent.BOTH:
                self.log.info('backing out of game selector')
                return None
            if event is NavEvent.SELECT:
                break

            if event is NavEvent.LEFT:
                move = -1
            elif event is NavEvent.RIGHT:
                move = 1
            else:
                move = 0

            self.scroll_by(move, max=len(self._games))
            self._selected_game = self._games[self._selected_index]

            self.draw_frame(title)

            y = self._selected_game.y
            assert y is not None
            self.animate_scroll_toward(0, y)

        self.draw_loading()

        return self._selected_game

    def draw_loading(self):
        game = self._selected_game

        if screenshot := self.screenshots.get(game.parent.rom):
            self.display.show_frame(screenshot)
            return

        self.text.clear()
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
        OFFSET = self.text.height // 2 + 8
        for parent in self._parents:
            parent_color = 2
            for game in parent.children:
                assert game.y is not None
                color = 3 if (game is self._selected_game) else 1
                parent_color = max(color, parent_color)
                for i, line in  enumerate(game.name.splitlines()):
                    self.text.draw_text(
                        text = str(line).upper(),
                        y = game.y+6*i - self._scroll[1] + OFFSET,
                        x = 6 if i else 4,
                        box_y = box_y,
                        # box_b = details_end-1,
                        font = 5,
                        color = color
                    )
                if not self.snapshotter and not self.screenshotter:
                    if game.is_high_score:
                        # col = RandomColor(2, color)
                        col = ColorRamp(10, 2, lambda x: min(3, max(6-x, 2)))
                    else:
                        col = color
                    self.text.draw_text(
                        text = str(game.high_score),
                        y = game.y - self._scroll[1] + OFFSET,
                        right = True,
                        x = self.text.width,
                        box_y = box_y,
                        font = 5,
                        color = col
                    )
            assert parent.y is not None
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
                x = self.text.width//2,
                font = 5,
                color = 3
            )

        self.show()