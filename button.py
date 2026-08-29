#!/usr/bin/env python

from dataclasses import dataclass, field

import logging
from enum import Enum, auto
from typing import Optional
import queue
import time


GPIO_PIN_LEFT     = 25   # left flipper  → LEFT_FLIPPER
GPIO_PIN_RIGHT    = 19   # right flipper → RIGHT_FLIPPER
GPIO_PIN_LAUNCH   = 7   # launch button → LAUNCH



# ---------------------------------------------------------------------------
# Phase 3 — GPIO button input
# ---------------------------------------------------------------------------
 
#: Two debounce layers are intentional:
#:   1. gpiozero bounce_time — filters electrical noise before Python sees it
#:   2. _last_press guard    — catches rapid repeat presses that slip through
DEBOUNCE_S = 0.03   # 50 ms; raise to ~0.08 if double-fires occur; lower to ~0.03 if missed

#: How long a flipper must be held before get_key_presses() re-fires it as a
#: fresh press, so holding a flipper down keeps scrolling a menu.
REPEAT_INTERVAL_S = 0.3

class ButtonName(Enum):
    LEFT_FLIPPER   = auto()
    RIGHT_FLIPPER  = auto()
    LAUNCH         = auto()


class NavEvent(Enum):
    """
    Menu-navigation signal produced by ButtonInput.get_key_presses().

    NONE   — nothing changed on this tick (still useful to callers that
             redraw/animate every tick regardless of input)
    LEFT   — left flipper pressed (or held past REPEAT_INTERVAL_S)
    RIGHT  — right flipper pressed (or held past REPEAT_INTERVAL_S)
    SELECT — launch button pressed; terminal — get_key_presses() returns
             after yielding this once
    BOTH   — left and right flippers are held down at the same time;
             terminal — get_key_presses() returns after yielding this once

    BOTH only reports that the chord happened. What it *means* — back,
    cancel, or nothing at all — is entirely up to the caller; ButtonInput
    has no opinion about menu semantics.
    """
    NONE   = auto()
    LEFT   = auto()
    RIGHT  = auto()
    SELECT = auto()
    BOTH   = auto()


@dataclass(frozen=True)
class ButtonEvent:
    """A single press or release edge for one logical button."""
    button:    ButtonName
    pressed:   bool
    timestamp: float = field(default_factory=time.monotonic)



class ButtonInput:
    """
    Reads three GPIO buttons and emits ButtonEvent values for both press
    and release edges, and tracks current held state per button.

    Press/release matters because PinMAME's switch matrix models a real
    switch's on/off state, not a momentary tap — a held flipper button is
    a switch that stays closed until released. Downstream phases send both
    edges to PinMAMEBridge.send_switch(number, active) so the emulated
    switch state matches the physical button state at all times.

    Events are pushed onto an internal queue so that any phase (GameSelector,
    VideoModeSession) can call poll() independently without needing a callback
    wired at construction time.  start() therefore takes no callback argument —
    callers own their event loops and pull from the queue as needed.

    is_held() gives current state directly, which VideoModeSession can use to
    sync switches at session start (e.g. if FIRE is already held down when a
    video mode begins).

    On non-Pi hardware gpiozero will raise an error; the class falls back to a
    stdin-driven stub so the rest of the stack can be tested on a desktop. The
    stub cannot detect real key-up over a terminal, so each keypress there is
    treated as an instantaneous press+release pair — it can't simulate holds,
    which also means get_key_presses()'s NavEvent.BOTH chord can't be
    exercised from the stub; it requires real, overlapping GPIO holds.

    GPIO wiring (BCM, active-low, internal pull-up):
      pin_left  (default 25) → left flipper  → SCROLL_UP
      pin_right (default 19) → right flipper → SCROLL_DOWN
      pin_fire  (default 7)  → launch button → FIRE
    """

 
    def __init__(
        self,
        pin_left:  int = GPIO_PIN_LEFT,
        pin_right: int = GPIO_PIN_RIGHT,
        pin_launch:  int = GPIO_PIN_LAUNCH,
    ) -> None:
        self.log = logging.getLogger("Buttons")
        self.pin_left  = pin_left
        self.pin_right = pin_right
        self.pin_launch  = pin_launch
 
        self._log = logging.getLogger('ButtonInput')
        self._queue: queue.Queue[ButtonEvent] = queue.Queue()
        self._buttons: list = []          # gpiozero Button objects
        self._stub_mode = False

        self._held: dict[ButtonName, bool] = {b: False for b in ButtonName}
        # Debounce guard is keyed by (button, pressed) so a press and its
        # eventual release are never mistaken for one another.
        self._last_edge: dict[tuple[ButtonName, bool], float] = {
            (b, a): 0.0 for b in ButtonName for a in (True, False)
        }
 
    # ── Lifecycle ─────────────────────────────────────────────────────────────
 
    def start(self) -> None:
        """Configure GPIO pins and begin listening for button presses."""
        pin_map = {
            self.pin_left:  ButtonName.LEFT_FLIPPER,
            self.pin_right: ButtonName.RIGHT_FLIPPER,
            self.pin_launch:  ButtonName.LAUNCH,
        }
        try:
            from gpiozero import Button as _GpioButton
            for pin, button in pin_map.items():
                btn = _GpioButton(pin, pull_up=True, bounce_time=DEBOUNCE_S)
                btn.when_pressed  = lambda b=button: self._handle_edge(b, True)
                btn.when_released = lambda b=button: self._handle_edge(b, False)
                self._buttons.append(btn)
                self._log.info('set up button %s', btn)
                self._log.info("GPIO pin %d (BCM) → %s", pin, button.name)
        except Exception as exc:
            self._log.warning(
                "gpiozero unavailable (%s) — stdin stub active. "
                "Keys: a=LEFT_FLIPPER  d=RIGHT_FLIPPER  s=LAUNCH", exc
            )
            self._stub_mode = True
 
    def poll(self, timeout: float = 0.0) -> Optional[ButtonEvent]:
        """
        Block for up to *timeout* seconds and return the next ButtonEvent,
        or None if no button was pressed in that window.
 
        In stub mode, also drains any keypresses from stdin (non-blocking).
        """
        # if self._stub_mode:
        self._stub_drain()
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
 
    def is_held(self, button: ButtonName) -> bool:
        """True if *button* is currently pressed down."""
        return self._held[button]

    def get_key_presses(self):
        """
        Generator for menu/list navigation.

        Yields a NavEvent on every poll tick — NavEvent.NONE when nothing
        changed, otherwise LEFT/RIGHT for the flippers. A held flipper
        re-fires every REPEAT_INTERVAL_S so callers get hold-to-repeat
        scrolling without extra bookkeeping.

        Terminates by yielding one of two terminal signals and then
        returning (the generator is exhausted — a subsequent `next()`
        raises StopIteration, which ends a `for event in ...:` loop
        naturally):

          NavEvent.SELECT — the launch button was pressed
          NavEvent.BOTH   — both flippers are currently held down

        Callers are responsible for deciding what SELECT/BOTH mean in
        context (e.g. "confirm" / "back") — this method only reports
        what the hardware is doing.
        """

        # pretend remnant presses are nothing until nothing is actually pressed
        for event in self._get_key_presses():
            yield NavEvent.NONE
            if event == NavEvent.NONE:
                break
        for event in self._get_key_presses():
            if event is not NavEvent.NONE:
                self.log.info('passing event, %s', event)
            yield event

    def _get_key_presses(self):
        pressed: list[ButtonName] = []
        pressed_at = time.monotonic()
        was_both = False

        while self.poll(timeout=0):
            pass
        while True:
            now = time.monotonic()
            event = self.poll(timeout=0.0)
            if event:
                if event.pressed:
                    if event.button not in pressed:
                        pressed.append(event.button)
                    pressed_at = now
                else:
                    if event.button in pressed:
                        pressed.remove(event.button)

            if pressed and now >= pressed_at + REPEAT_INTERVAL_S:
                pressed_at = now
                button = pressed.pop(0)
                pressed.append(button)
                event = ButtonEvent(button, True)

            if self.is_held(ButtonName.LEFT_FLIPPER) and self.is_held(ButtonName.RIGHT_FLIPPER):
                yield NavEvent.BOTH
                was_both = True

            elif event and event.pressed:
                if event.button is ButtonName.LEFT_FLIPPER:
                    if was_both:
                        was_both = False
                        yield NavEvent.NONE
                    else:
                        yield NavEvent.LEFT
                elif event.button is ButtonName.RIGHT_FLIPPER:
                    if was_both:
                        was_both = False
                        yield NavEvent.NONE
                    else:
                        yield NavEvent.RIGHT
                elif event.button is ButtonName.LAUNCH:
                    yield NavEvent.SELECT
                else:
                    self._log.error('unexpected event: %s', event)
                    yield NavEvent.NONE
            else:
                yield NavEvent.NONE

    def stop(self) -> None:
        """Release GPIO resources."""
        for btn in self._buttons:
            try:
                btn.close()
            except Exception:
                pass
        self._buttons.clear()
        self._log.info("GPIO buttons released")
 
    # ── Internal ──────────────────────────────────────────────────────────────
 
    def _handle_edge(self, button: ButtonName, pressed: bool) -> None:
        """Software debounce guard, update held state, then enqueue."""
        self._log.debug("Button event: %s/%s", button.name, pressed)
        now = time.monotonic()
        key = (button, pressed)
        if now - self._last_edge[key] < DEBOUNCE_S:
            self._log.debug("Debounce suppressed %s/%s", button.name, pressed)
            return
        self._last_edge[key] = now

        self._held[button] = pressed
        event = ButtonEvent(button=button, pressed=pressed, timestamp=now)
        self._log.debug("Button event: %s/%s", button.name, pressed)
        self._queue.put_nowait(event)

    def _stub_drain(self) -> None:
        """
        Non-blocking stdin read for desktop testing (requires a tty).
        Terminals don't deliver key-up over SSH, so each keypress is
        synthesized as an immediate press followed by a release — this
        can exercise event plumbing but not true hold duration.
        """
        import sys, select
        if not sys.stdin.isatty():
            return
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return
        ch = sys.stdin.read(1).lower()
        mapping = {'a': ButtonName.LEFT_FLIPPER,
                   'd': ButtonName.RIGHT_FLIPPER,
                   's': ButtonName.LAUNCH}
        if ch in mapping:
            button = mapping[ch]
            self._handle_edge(button, True)
            self._handle_edge(button, False)
 
if __name__ == '__main__':
    # ── Phase 3 button test ───────────────────────────────────────────
    # Instantiates ButtonInput in isolation and polls for events.
    # Press each button; you should see a timestamped line per press.
    # Ctrl-C to exit.
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    buttons = ButtonInput()
    buttons.start()
    print("Button test — press LEFT_FLIPPER / RIGHT_FLIPPER / LAUNCH.  Ctrl-C to quit.")
    try:
        while True:
            event = buttons.poll(timeout=0.0)
            if event is not None:
                print(f"[{time.strftime('%H:%M:%S')}] {event.button.name} {event.pressed}")
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        buttons.stop()