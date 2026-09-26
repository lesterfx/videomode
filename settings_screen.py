#!/usr/bin/env python3

from itertools import count

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
        self.keys = ['settings'] + self.settings.keys()

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
            move = 0
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
                    move = -1
            elif event is NavEvent.RIGHT:
                if self._active:
                    self.modify_value(1)
                else:
                    move = 1
            elif event is NavEvent.NONE:
                pass
            self.scroll_by(move, max=len(self.keys))
            self.animate_scroll_toward(0, self._selected_index * 8)
            self.draw_frame()
            
        return ScreenState.SETTINGS_DONE

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
        OFFSET = self.text.height - 16
        for y, key in zip(count(1, 8), self.keys):
            self.text.draw_text(
                text = key.upper(),
                y = y - self._scroll[1] + OFFSET,
                x = 6,
                font = 7,
                color = 3
            )
            if key != 'settings':
                value = self.values[key]
                self.text.draw_text(
                    text = self._value_str(value),
                    y = y - self._scroll[1] + OFFSET,
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
            y = y - self._scroll[1] + OFFSET,
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

