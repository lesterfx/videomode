#!/usr/bin/env python3

import json
import logging
from operator import attrgetter, itemgetter
from pathlib import Path
from text_to_dmd import ColorRamp, RandomColor
from typing import Optional

from vm_types import GameEntry, GameParent, EndDetectorConfig
from button import ButtonInput, NavEvent
from dmd_display import DMDDisplay
from screens import Screen
from vm_types import SessionContext, ScreenState
from high_scores import HighScoreStore

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

    def __init__(self,
        display: DMDDisplay,
        buttons: ButtonInput,
        scores: HighScoreStore
    ) -> None:
        super().__init__(display, buttons)
        self._parents: list[GameParent] = []
        self._games: list[GameEntry] = []
        self._selected_index = 0
        self.scores = scores

    def load_games(self) -> None:
        self.screenshots = {key: bytes(int(ch) for ch in screenshot) for key, screenshot in json.load(open(Path(__file__).parent / 'screenshots.json')).items() if screenshot}

        entries = json.load(open(Path(__file__).parent / 'games.json'))
        for entry in entries:
            videomodes = entry.pop('videomodes', [])
            end_cfg = entry.pop('end_detector_config', {})
            entry['end_detector_config'] = EndDetectorConfig(**end_cfg)
            parent = GameParent(**entry)
            if not parent.rom or not (Path.home() / '.pinmame' / 'roms' / (parent.rom + '.zip')).exists():
                parent.rom = None
            if not videomodes:
                self.log.warning(f'NO VIDEO MODES CONFIGURED: {parent}')
            for i, videomode in enumerate(videomodes, 1):
                game = GameEntry(parent=parent, **videomode, snapshot_index=i)
                if not game.ready:
                    game.msg = 'NOT READY'
                if not parent.rom:
                    game.ready = False
                    game.msg = 'NO ROM'
                if not (Path.home() / '.pinmame' / 'sta' / f'{parent.rom}-{game.snapshot_index}.sta').exists():
                    game.ready = False
                    game.msg = 'NO SNAPSHOT'
                    self.log.warning('no snapshot for game %s %s', parent, game)
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
        return f'{score:,}'
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
        ctx: SessionContext
    ) -> ScreenState:
        """
        Block until the user selects a game.

        Returns the chosen GameEntry, or None if the person chorded both
        flippers (BOTH) — the caller's cue to return to the login screen.
        """

        self.log.info('selecting for %s', ctx.initials or 'guest')
        self.reset_timeout()
        self.snapshotter = ctx.snapshotting
        self.screenshotter = ctx.screenshotting
        if self.snapshotter:
            title = 'MAKING ROM SNAPSHOT'
        elif self.screenshotter:
            title = 'SAVING SCREENSHOT'
        else:
            title = f'{ctx.initials or "guest"} SELECT YOUR GAME'

        scores_for_player = self.scores.scores_for_player(ctx.initials)

        for game in self._games:
            if score := scores_for_player.get(game.unique_name):
                game.high_score = score.score
                game.is_high_score = score.is_high_score
            else:
                game.high_score = 0
                game.is_high_score = False
        self.log.info(f'scores for player: {scores_for_player}')

        # self._selected_index = 0

        for event in self.buttons.get_key_presses():
            if event is NavEvent.BOTH:
                self.log.info('backing out of game selector')
                self._scroll = [0, 0]
                self._selected_index = 0
                self.reset_timeout()
                return ScreenState.LOGGED_OUT
            if event is NavEvent.SELECT:
                self.reset_timeout()
                ctx.game = self._selected_game
                if self._selected_game.ready:
                    self.draw_loading()
                    return ScreenState.GAME_SELECTED
                else:
                    ctx.err = self._selected_game.msg
                    return ScreenState.GAME_FAILED
            if event is NavEvent.LEFT:
                move = -1
                self.reset_timeout()
            elif event is NavEvent.RIGHT:
                move = 1
                self.reset_timeout()
            elif event is NavEvent.NONE:
                move = 0
                if self.timeout():
                    return ScreenState.LOGGED_OUT

            self.scroll_by(move, max=len(self._games))
            self._selected_game = self._games[self._selected_index]

            self.draw_frame(title)

            y = self._selected_game.y
            assert y is not None
            self.animate_scroll_toward(0, y)

        raise Exception('no return...')

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
            parent_color = 1
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
                    col = color
                    if game.ready:
                        text = self._format_game(game.high_score)
                        if game.is_high_score:
                            col = ColorRamp(10, 2, lambda x: min(3, max(6-x, 2)))
                    else:
                        text = game.msg
                    self.text.draw_text(
                        text = text,
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