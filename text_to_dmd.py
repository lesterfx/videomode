#!/usr/bin/env python

from __future__ import annotations

from itertools import count
import logging
import os
from pathlib import Path
from random import randint
from typing import Any, Callable, Generator, Optional

from fonts import FONT

class RandomColor:
    def __init__(self, minval: int, maxval: int):
        self.minval = min(minval, maxval)
        self.maxval = max(minval, maxval)

    def __call__(self, x: int, y: int, t: int) -> int:
        return randint(self.minval, self.maxval)

class ColorRamp:
    def __init__(self, width=10, speed=1, mapper=Callable[[int], int]):
        self.width = width
        self.speed = speed
        self.mapper = mapper

    def __call__(self, x: int, y: int, t: int) -> int:
        val = abs(((x + y - t*self.speed) % self.width*2) - self.width)
        val = self.mapper(val)
        return val

class TextRender:
    def __init__(self, width: int, height: int, depth: int) -> None:
        self.width = width
        self.height = height
        self.depth = depth
        self.t = 0
        self.clear()
        self.log = logging.getLogger('TextRender')

    def clear(self) -> None:
        self.t += 1
        self.frame = bytearray(self.width * self.height)

    def draw_text(
        self,
        text: str,
        y: int,
        x: int = 0,
        right: bool = False,
        center: bool = False,
        color: int|Callable[[int, int, int], int] = 3,
        font: int|tuple[int, int] = 7,
        box_x: Optional[int] = None,
        box_y: Optional[int] = None,
        box_r: Optional[int] = None,
        box_b: Optional[int] = None,
        background: bool = False,
        outline: bool = False,
        kerning: int = 1,
        outline_color: int|Callable[[int, int, int], int] = 0
    ) -> None:
        
        if outline:
            assert isinstance(font, int)
            self.draw_text(
                text = text,
                y = y-1,
                x = x-1,
                right = right,
                center = center,
                font = (font, 1),
                color = outline_color,
                kerning = kerning - 2
            )
        
        y0 = y

        box_x = max(0, box_x or 0)
        box_y = box_y or 0
        box_r = min(self.width, box_r if box_r is not None else self.width)
        box_b = min(self.height, box_b if box_b is not None else self.height)

        cols = []
        i = 0
        for ch in str(text):
            for col in self._char_columns(ch, font=font):
                cols.append((i, col))
                i += 1
            i += kerning
        i -= 1

        start_x = x
        if right:
            start_x -= i
        elif center:
            start_x -= i // 2

        for i, col_bits in cols:
            x = start_x + i
            if x < box_x:
                continue
            if x >= box_r:
                continue
            for row_i in count():
                if not col_bits: break

                y = y0 + row_i

                if box_y <= y < box_b:
                    if bool(col_bits & 1):
                        if callable(color):
                            intensity = color(x, y, self.t)
                        else:
                            intensity = color
                        self.frame[y * self.width + x] = intensity
                    elif background:
                        self.frame[y * self.width + x] = 0
   
                col_bits = col_bits >> 1

    def _char_columns(self, ch: str, font: int|tuple[int, int]=7) -> tuple[int, ...]:
        """Return the 5 column bytes for a printable ASCII character."""
        try:
            font_d = FONT[font]
        except KeyError:
            self.log.error('font size %s not available in %s', font, list(FONT))
            raise
        try:
            return font_d[ch]
        except KeyError:
            self.log.error(f'missing character: {ch}')
            return font_d['?']

    def _box(self, x:int, y:int, w:int, h:int) -> Generator[tuple[int, int, int], Any, None]:
        r = x + w
        t = y + h
        x = min(max(0, x), self.width)
        y = min(max(0, y), self.height)
        r = min(max(0, r), self.width)
        t = min(max(0, t), self.height)
        for row_i in range(y, t):
            for col_i in range(x, r):
                index = row_i * self.width + col_i
                yield index, col_i, row_i

    def invert(self, x:int, y:int, w:int, h:int) -> None:
        for index, _x, _y in self._box(x, y, w, h):
            self.frame[index] = (2**self.depth-1) - self.frame[index]

    def box(self, x:int, y:int, w:int, h:int, color: int|Callable[[int, int, int], int]) -> None:
        for index, _x, _y in self._box(x, y, w, h):
            if callable(color):
                col = color(_x, _y, self.t)
            else:
                col = color
            self.frame[index] = col

    def image(self, data: bytes|bytearray) -> None:
        self.frame[:] = data

# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dmd_display import DMDDisplay
    import time
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    display = DMDDisplay(terminal_mode=True, label="SELFTEST")
    text = TextRender(width=128, height=32, depth=2)

    text.clear()
    for font_size in sorted(FONT):
        text.clear()
        for i, line in enumerate(['the quick brown fox', 'jumps over the lazy dog']):
            text.draw_text(
                text = line,
                font = font_size,
                x = 64,
                center = True,
                y = i*font_size,
                color = 1
            )
        display.show_frame(text.frame)
        time.sleep(2)
