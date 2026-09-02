#!/usr/bin/env python3

import json
from itertools import count
import logging

from operator import attrgetter, itemgetter
from text_to_dmd import ColorRamp, RandomColor
from typing import Optional

from settings import SettingsStore
from button import ButtonInput, NavEvent
from dmd_display import DMDDisplay
from screens import Screen

from vm_types import ScreenState, SessionContext

# ---------------------------------------------------------------------------
# Phase 4 — Game selector UI
# ---------------------------------------------------------------------------

class SettingsScreen(Screen):
    """
    Displays the sorted game list on the DMD and handles navigation.

    Responsibilities:
      - Parse games.json into game objects
      - Render scrollable list via DMDDisplay.show_frame()
      - Handle LEFT / RIGHT / SELECT from ButtonInput.get_key_presses()
      - Return the selected GameEntry (or None if BOTH was pressed — the
        caller's cue to fall back to the login screen)
    """

    def __init__(self, display: DMDDisplay, buttons: ButtonInput, settings: SettingsStore) -> None:
        super().__init__(display, buttons)
        self._selected_index = 0
        self.entries = 0
        self.settings = settings
        self.keys = 'settings', 'brightness', 'volume', 'log in first'

    def run(
        self,
        ctx: SessionContext
    ) -> ScreenState:
        """
        Block until the user selects a game.

        Returns the chosen GameEntry, or None if the person chorded both
        flippers (BOTH) — the caller's cue to return to the login screen.
        """

        self._selected_index = 0
        self._active = False
        self.values = self.settings.get_settings()

        for event in self.buttons.get_key_presses():
            if event is NavEvent.BOTH:
                if self._active:
                    self.reset()
                    self._active = False
                else:
                    return ScreenState.SETTINGS_DONE
            if event is NavEvent.SELECT:
                if self._selected_index == 0:
                    self.log.info('back selected')
                    return ScreenState.SETTINGS_DONE
                elif self._active:
                    key = self.keys[self._selected_index]
                    self.settings.set(key, self.values[key])
                    self._active = False
                else:
                    self._active = True
            elif event is NavEvent.LEFT:
                if self._active:
                    self.modify_value(-1)
                else:
                    self.move_index(-1)
            elif event is NavEvent.RIGHT:
                if self._active:
                    self.modify_value(1)
                else:
                    self.move_index(1)
            elif event is NavEvent.NONE:
                pass

            self.draw_frame()
            
        return ScreenState.SETTINGS_DONE

    def move_index(self, by):
        self._selected_index = (self._selected_index + by) % len(self.keys)

    def modify_value(self, modification):
        key = self.keys[self._selected_index]
        value = self.values[key]
        if isinstance(value, bool):
            value = not value
        elif isinstance(value, int):
            value = max(0, min(100, value + modification))
        else:
            raise ValueError(f'unexpected value %s', value)
        self.preview_value(key)
        self.values[key] = value

    def reset(self):
        key = self.keys[self._selected_index]
        self.values[key] = self.settings.get(key)
        self.preview_value(key)
    
    def preview_value(self, key):
        value = self.values[key]
        if key == 'brightness':
            self.display.set_brightness(value)

    def _value_str(self, value):
        self.log.info('value is %s, a %s', value, type(value))
        if isinstance(value, bool):
            if value:
                return 'YES'
            else:
                return 'NO'
        elif isinstance(value, int):
            return str(value)
        raise ValueError(value)

    def draw_frame(self):
        self.text.clear()
        for y, key in zip(count(1, 8), self.keys):
            self.text.draw_text(
                text = key.upper(),
                y = y,
                x = 6,
                font = 7,
                color = 3
            )
            if key != 'settings':
                value = self.values[key]
                self.text.draw_text(
                    text = self._value_str(value),
                    y = y,
                    x = self.text.width - 6,
                    right = True,
                    font = 7,
                    color = 3
                )
        y = 1 + 8 * self._selected_index
        if self._active or self._selected_index == 0:
            text = "<"
        else:
            text = ">"
        if self._active:
            x = self.text.width - 1
            right = True
        else:
            x = 1
            right = False
        self.text.draw_text(
            text = text,
            y = y,
            x = x,
            right = right,
            font = 7,
            color = 3
        )
        self.text.invert(
            x = 0,
            y = 0,
            w = self.text.width,
            h = 8
        )

        self.show()

