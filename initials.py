#!/usr/bin/env python3

import string

from typing import Optional

from screens import Screen
from button import NavEvent

from text_to_dmd import RandomColor

# ---------------------------------------------------------------------------
# InitialsEntryScreen
# ---------------------------------------------------------------------------

class InitialsEntryScreen(Screen):
    """
    3-character initials entry on a fixed on-screen QWERTY-ish grid.

    RIGHT steps across columns, LEFT steps down rows, while fewer than 3
    characters have been entered; once full, LEFT/RIGHT instead toggles
    between the confirm/backspace icons on the bottom row. SELECT commits
    the highlighted character (or backspaces on '\\r', or finishes entry
    on '\\t').
    """

    _COLS = 7

    def run(self, title: str = '') -> Optional[str]:
        selected_row = 0
        selected_col = 0
        options = []
        for i, ch in enumerate(string.ascii_uppercase + '\r\t'):
            row, col = divmod(i, self._COLS)
            option = {'ch': ch, 'i': i}
            option['x'] = 17 - row * 5 + col * 7
            option['y'] = 1 + row * 6 + col
            option['center'] = True
            option['color'] = 2
            if ch == '\t':
                option['y'] += 1
                option['center'] = False
                option['color'] = 1
            elif ch == '\r':
                option['color'] = 1
                option['x'] += 1
            options.append(option)

        initials = ''
        selected_index = 0

        def draw():
            self.text.clear()

            for option in options:
                if option['i'] == selected_index:
                    color = 0
                    outline = True
                    outline_color = 3
                else:
                    color = option['color']
                    outline = False
                    outline_color = 0

                self.text.draw_text(
                    text = option['ch'],
                    y = option['y'],
                    x = option['x'],
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
                    x = 97,
                    font = 10,
                    center = True,
                    color = 1
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
                    color = RandomColor(2,3)
                )
            self.show()

        while True:
            for event in self.buttons.get_key_presses():
                if event is NavEvent.BOTH:
                    # No prior UI to fall back to mid-entry today — treat
                    # the chord as "abandon initials entry".  Caller decides
                    # what to do with None (e.g. fall back to 'guest').
                    return None
                if event is NavEvent.SELECT:
                    break

                if len(initials) < 3:
                    if event is NavEvent.RIGHT:
                        selected_col = (selected_col + 1) % self._COLS
                        if (selected_col + selected_row * self._COLS) >= len(options):
                            selected_col = 0
                    elif event is NavEvent.LEFT:
                        selected_row += 1
                        if (selected_col + selected_row * self._COLS) >= len(options):
                            selected_row = 0
                elif event in (NavEvent.LEFT, NavEvent.RIGHT):
                    selected_row = 3
                    selected_col = 11 - selected_col

                selected_index = selected_col + selected_row * self._COLS
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

        return initials or None
