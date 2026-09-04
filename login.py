from enum import Enum, auto
from typing import Optional
import time

from button import ButtonInput, NavEvent
from dmd_display import DMDDisplay
from screens import Screen
from players import PlayerStore

from text_to_dmd import RandomColor, ColorRamp

from vm_types import ScreenState, SessionContext

class Login(Enum):
    BACK = auto()

# ---------------------------------------------------------------------------
# PlayerLoginScreen
# ---------------------------------------------------------------------------

class PlayerLoginScreen(Screen):
    """
    Recency-ordered player strip: guest, then every known player
    (most-recently-played first), then "new". Picking "new" hands off to
    InitialsEntryScreen, which this screen owns internally — nothing
    outside the login flow needs to know initials entry exists.
    """

    def __init__(self, display: DMDDisplay, buttons: ButtonInput, player_store: PlayerStore) -> None:
        super().__init__(display, buttons)
        self.player_store = player_store

    def run(
        self,
        ctx: SessionContext
    ) -> ScreenState:
        if ctx.initials: return ScreenState.LOGGED_IN
        self.reset_timeout()
        SEPARATION = 31
        self.users = [(0, 'guest')]
        for i, initials in enumerate(self.player_store.get_players() + ['new']):
            self.users.append((int(SEPARATION * (i + 1.3)), initials))
        self.wrap_width = self.users[-1][0] + SEPARATION + 10
        self._selected_index = 0
        self._scroll = [0, self.text.height]
        self.scroll_target_y = 0
        self.WRAP = len(self.users) > 5

        back_duration = time.monotonic()
        for event in self.buttons.get_key_presses():
            self.scroll_target_y = 0
            if event is not NavEvent.BOTH: back_duration = time.monotonic()
            if event is NavEvent.BOTH:
                self.timeout(force=True)
                self.log.info('force log out')
                self.scroll_target_y = self.text.height//2
                if time.monotonic() - back_duration > 2:
                    return ScreenState.LOGIN_BACK
            elif event is NavEvent.SELECT:
                if self.reset_timeout():
                    break
            elif event is NavEvent.LEFT:
                if self.reset_timeout():
                    self._selected_index -= 1
            elif event is NavEvent.RIGHT:
                if self.reset_timeout():
                    self._selected_index += 1
            elif event is NavEvent.NONE:
                if self.timeout():
                    self.scroll_target_y = self.text.height//2

            if not self.WRAP:
                self._selected_index = min(len(self.users)-1, max(self._selected_index, 0))

            wrap_count, index = divmod(self._selected_index, len(self.users))
            self.animate_scroll_toward(self.wrap_width*wrap_count + self.users[index][0], self.scroll_target_y)
            self.draw(index)

        self._scroll = [0, 0]
        initials = self.users[self._selected_index % len(self.users)][1]
        self._selected_index = 0
        if initials == 'new':
            ctx.initials = None
            return ScreenState.CREATE_USER
            initials = self.initials_screen.run('NEW PLAYER')
        elif initials == 'guest':
            ctx.initials = None
            return ScreenState.GUEST_SELECTED
        else:
            ctx.initials = initials
            return ScreenState.LOGGED_IN

    def draw(self, index: int) -> None:
        self.text.clear()
        height = self.text.height//2-abs(self._scroll[1])
        height = max(height, 0)
        self.text.box(0, self.text.height//2-height, self.text.width, height, RandomColor(1,3))
        self.text.draw_text(
            'Select player',
            center = True,
            x = self.text.width//2,
            y = self.text.height//2-14-self._scroll[1],
            font = 12,
            color = 3,
            outline = True,
            kerning = 1
        )
        for i, (x, initials) in enumerate(self.users):
            if self.WRAP:
                x = (int(self.text.width//2 + x - self._scroll[0]+self.wrap_width//4) % self.wrap_width) - self.wrap_width//4
            else:
                x = (int(self.text.width//2 + x - self._scroll[0]+self.wrap_width//4) ) - self.wrap_width//4

            self.text.draw_text(
                initials,
                center = True,
                x = x,
                y = self.text.height//2 + 1 + self._scroll[1],
                font = 15,
                color = 3 if (i==index) else 1
            )
        self.show()
