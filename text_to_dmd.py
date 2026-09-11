#!/usr/bin/env python

from __future__ import annotations

from itertools import count
import logging
import os
from pathlib import Path
from random import randint
import time
import time
from typing import Any, Callable, Generator, Optional

from fonts import FONT

class RandomColor:
    def __init__(self, minval: int, maxval: int):
        self.minval = min(minval, maxval)
        self.maxval = max(minval, maxval)

    def __call__(self, x: int, y: int, t: float) -> int:
        return randint(self.minval, self.maxval)

class ColorRamp:
    def __init__(self, width=10, speed=20, mapper=Callable[[int], int]):
        self.width = width
        self.speed = speed
        self.mapper = mapper

    def __call__(self, x: int, y: int, t: float) -> int:
        val = int(abs(((x + y - t*self.speed) % self.width*2) - self.width))
        val = self.mapper(val)
        return val

class TextTooWide(Exception): pass

class TextRender:
    def __init__(self, width: int, height: int, depth: int) -> None:
        self.width = width
        self.height = height
        self.depth = depth
        self.t = 0
        self.clear()
        self.log = logging.getLogger('TextRender')

    def clear(self) -> None:
        self.t = time.monotonic()
        self.frame = bytearray(self.width * self.height)

    def draw_text(
        self,
        text: str|list[tuple[str, int|Callable[[int, int, int], int]]],
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
        outline_color: int|Callable[[int, int, int], int] = 0,
        minx: Optional[int] = None,
        max_width: Optional[int] = None
    ) -> None:
        y0 = y

        box_x = max(0, box_x or 0)
        box_y = box_y or 0
        box_r = min(self.width, box_r if box_r is not None else self.width)
        box_b = min(self.height, box_b if box_b is not None else self.height)

        cols: list[tuple[int, int, int|Callable[[int, int, int], int]]] = []
        i = 0
        if isinstance(text, str):
            textlist = [(ch, color) for ch in text]
        else:
            textlist = text

        if max_width is not None and isinstance(font, int):
            font = self._fit_font(textlist, font, kerning, max_width)

        cols: list[tuple[int, int, int|Callable[[int, int, int], int]]] = []
        for ch, color in textlist:
            for col in self._char_columns(ch, font=font):
                cols.append((i, col, color))
                i += 1  # next column
            i += kerning  # next character
        i -= kerning  # no kerning after the last character
        if max_width is not None and len(cols) > max_width:
            raise TextTooWide(f'text would have been {len(cols)} pixels wide')

        start_x = x
        if right:
            start_x -= i
        elif center:
            start_x -= i // 2
        if minx is not None:
            start_x = max(start_x, minx)
        
        if outline:
            assert isinstance(font, int)
            self.draw_text(
                text = text,
                y = y-1,
                x = start_x - 1,
                font = (font, 1),
                color = outline_color,
                kerning = kerning - 2,
                max_width=max_width
            )


        for i, col_bits, color in cols:
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

    def _text_width(
        self,
        textlist: list[tuple[str, int|Callable[[int, int, int], int]]],
        font: int|tuple[int, int],
        kerning: int
    ) -> int:
        """Total pixel width of textlist rendered at `font`, incl. kerning."""
        total = 0
        n = 0
        for ch, _ in textlist:
            total += len(self._char_columns(ch, font=font))
            n += 1
        if n:
            total += kerning * (n - 1)
        return total

    def _fit_font(
        self,
        textlist: list[tuple[str, int|Callable[[int, int, int], int]]],
        font: int,
        kerning: int,
        max_width: int
    ) -> int:
        """
        Return the largest font size <= `font` that renders textlist within
        max_width, trying `font` itself first and then stepping down through
        FONT's other integer sizes (sparse — not assumed contiguous) in
        decreasing order. Raises TextTooWide if even the smallest available
        size doesn't fit.
        """
        candidates = sorted((f for f in FONT if isinstance(f, int) and f <= font), reverse=True)
        width = 0
        for candidate in candidates:
            width = self._text_width(textlist, candidate, kerning)
            if width <= max_width:
                return candidate
        raise TextTooWide(
            f'text would have been {width} pixels wide even at the '
            f'smallest available font size {candidates[-1]}'
        )

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
            pass

        # Some fonts only define one case for a letter. Before giving up,
        # try the other case of the same character.
        swapped = ch.upper() if ch.islower() else ch.lower()
        if swapped != ch:
            try:
                return font_d[swapped]
            except KeyError:
                pass

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