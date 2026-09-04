#!/usr/bin/env python3

from abc import abstractmethod
import string

from typing import Optional

from screens import Screen
from button import NavEvent

from vm_types import ScreenState, SessionContext
from text_to_dmd import RandomColor

# ---------------------------------------------------------------------------
# InitialsEntryScreen
# ---------------------------------------------------------------------------

class InitialsEntryScreenBase(Screen):
    """
    3-character initials entry on a fixed on-screen QWERTY-ish grid.

    RIGHT steps across columns, LEFT steps down rows, while fewer than 3
    characters have been entered; once full, LEFT/RIGHT instead toggles
    between the confirm/backspace icons on the bottom row. SELECT commits
    the highlighted character (or backspaces on '\r', or finishes entry
    on '\t').
    """

    _COLS: int
    UNDERLINE_Y: int
    CHARACTER_Y: int
    TITLE_CENTER: int
    SPACING_Y: int
    SPACING_X: int
    @abstractmethod
    def get_option_position(self, i: int, ch: str) -> dict: pass
    @abstractmethod
    def move_right(self) -> None: pass
    @abstractmethod
    def move_left(self) -> None: pass
    @abstractmethod
    def scroll(self) -> None: pass

    def run_bool(
        self,
        ctx: SessionContext,
        title: str,
        subtitle: Optional[str] = None
    ) -> bool:

        self.options = []
        for i, ch in enumerate(string.ascii_uppercase + '\r\t'):
            option = {'ch': ch, 'i': i}
            option['center'] = True
            option['color'] = 2
            option.update(self.get_option_position(i, ch))
            if ch in '\t\r':
                option['color'] = 1
            self.options.append(option)

        initials = ''
        self.selected_index = 0

        def draw():
            self.text.clear()

            for option in self.options:
                if option['i'] == self.selected_index:
                    color = 0
                    outline = True
                    outline_color = 3
                else:
                    color = option['color']
                    outline = False
                    outline_color = 0

                self.text.draw_text(
                    text = option['ch'],
                    x = option['x'] - self._scroll[0] + self.text.width//2,
                    y = option['y'] - self._scroll[1],
                    font = 5,
                    center = option['center'],
                    color = color,
                    outline = outline,
                    outline_color = outline_color
                )

            if title:
                self.text.draw_text(
                    text = title,
                    y = 3,
                    x = self.TITLE_CENTER,
                    font = 10,
                    center = True,
                    color = 3
                )
            if subtitle:
                self.text.draw_text(
                    text = subtitle,
                    y = 13,
                    x = self.TITLE_CENTER,
                    font = 10,
                    center = True,
                    color = 1
                )

            for i, x in enumerate([85, 97, 109]):
                color = 1
                if i == len(initials):
                    text = self.options[self.selected_index]['ch']
                    color = RandomColor(2, 3)
                elif i < len(initials):
                    color = 2
                    text = initials[i]
                else:
                    text = ''
                self.text.box(
                    x = x-4,
                    y = self.UNDERLINE_Y,
                    w = 9,
                    h = 2,
                    color = color
                )
                if text in '\t\r':
                    text = ''
                self.text.draw_text(
                    text = text,
                    y = self.CHARACTER_Y,
                    x = x,
                    center = True,
                    font = 15,
                    color = color
                )
            self.show()

        while True:
            for event in self.buttons.get_key_presses():
                if event is NavEvent.SELECT:
                    break

                if len(initials) < 3:
                    if event is NavEvent.RIGHT:
                        self.move_right()
                    elif event is NavEvent.LEFT:
                        self.move_left()
                elif event in (NavEvent.LEFT, NavEvent.RIGHT):
                    self.selected_index = len(self.options) * 2 - 3 - self.selected_index

                # self.selected_index = self.selected_position[0] + self.selected_position[1] * self._COLS
                self.scroll()
                draw()

            ch = self.options[self.selected_index]['ch']
            if ch == '\r':
                initials = initials[:-1]
            elif ch == '\t':
                break
            else:
                initials += ch
            if len(initials) == 3:
                self.selected_index = len(self.options)-1
                # y, x = divmod(len(self.options)-1, self._COLS)
                # self.selected_position[0] = x
                # self.selected_position[1] = y

        ctx.initials = initials
        if initials:
            return True
        else:
            return False

class InitialsEntryScreenGrid(InitialsEntryScreenBase):
    _COLS = 7
    UNDERLINE_Y = 26
    CHARACTER_Y = 14
    TITLE_CENTER = 97
    SPACING_Y = 6
    SPACING_X = 7
    def get_option_position(self, i, ch):
        row, col = divmod(i, self._COLS)
        ret = {}
        ret['row'] = row
        ret['col'] = col
        ret['x'] = 17 - row * 5 + col * self.SPACING_X - self.text.width//2
        ret['y'] = 1 + row * self.SPACING_Y + col
        if ch == '\t':
            ret['y'] += 1
            ret['center'] = False
        elif ch == '\r':
            ret['x'] += 1
        return ret
    
    def move_right(self):
        old = self.options[self.selected_index]
        col = (old['col'] + 1) % self._COLS
        row = old['row']
        for col in (col, 0):
            for option in self.options:
                if option['row'] == row and option['col'] == col:
                    self.selected_index = option['i']
                    return

    def move_left(self):
        old = self.options[self.selected_index]
        col = old['col']
        row = old['row'] + 1
        for row in (row, 0):
            for option in self.options:
                if option['row'] == row and option['col'] == col:
                    self.selected_index = option['i']
                    return

    def scroll(self): pass

class InitialsEntryScreenRow(InitialsEntryScreenBase):
    _COLS = 28
    UNDERLINE_Y = 20
    CHARACTER_Y = 8
    TITLE_CENTER = 40
    SPACING_Y = 6
    SPACING_X = 7
    def get_option_position(self, i, ch):
        ret = {}
        ret['row'] = 0
        ret['col'] = i
        ret['x'] = i * self.SPACING_X
        ret['y'] = self.text.height - self.SPACING_Y
        if ch == '\t': ret['x'] += 6
        return ret

    def move_right(self):
        self.selected_index = (self.selected_index + 1) % self._COLS

    def move_left(self):
        self.selected_index = (self.selected_index - 1) % self._COLS

    def scroll(self):
        opt = self.options[self.selected_index]
        x = opt['x']
        y = opt['y']
        self.animate_scroll_toward(x, 0)



# InitialsEntryScreen = InitialsEntryScreenGrid
InitialsEntryScreen = InitialsEntryScreenRow

class HighScoreInitialsEntry(InitialsEntryScreen):
    def run(self, ctx):
        if not ctx.initials:
            result = self.run_bool(ctx, 'ENTER INITIALS', f'{ctx.score:,}')
        if result:
            return ScreenState.SAVE_HIGH_SCORE
        else:
            return ScreenState.NO_HIGH_SCORE

class CreateUserInitialsEntry(InitialsEntryScreen):
    def run(self, ctx):
        assert not ctx.initials
        result = super().run_bool(ctx, 'CREATE PLAYER')
        if result:
            return ScreenState.LOGGED_IN
        else:
            return ScreenState.LOGGED_OUT
