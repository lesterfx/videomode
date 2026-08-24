from typing import Optional

from button import ButtonInput, NavEvent
from dmd_display import DMDDisplay
from screens import Screen
from players import PlayerStore
from initials import InitialsEntryScreen
from text_to_dmd import RandomColor, ColorRamp

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
        self.initials_screen = InitialsEntryScreen(display, buttons)

    def run(self) -> Optional[str]:
        SEPARATION = 31
        users = [(0, 'guest')]
        for i, initials in enumerate(self.player_store.get_players() + ['new']):
            users.append((int(SEPARATION * (i + 1.3)), initials))
        wrap_width = users[-1][0] + SEPARATION + 10
        self._selected_index = 0
        self._scroll = [0, 100]
        self.WRAP = len(users) > 5

        def draw(index: int) -> None:
            self.text.clear()
            self.text.box(0, 0, self.text.width, self.text.height//2, RandomColor(1,3))
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
            for i, (x, initials) in enumerate(users):
                if self.WRAP:
                    x = (int(self.text.width//2 + x - self._scroll[0]+wrap_width//4) % wrap_width) - wrap_width//4
                else:
                    x = (int(self.text.width//2 + x - self._scroll[0]+wrap_width//4) ) - wrap_width//4

                self.text.draw_text(
                    initials,
                    center = True,
                    x = x,
                    y = self.text.height//2 + 1 + self._scroll[1],
                    font = 15,
                    color = 3 if (i==index) else 1
                )
            self.show()

        for event in self.buttons.get_key_presses():
            if event is NavEvent.BOTH:
                # Nothing to go "back" to from the root login screen.
                continue
            if event is NavEvent.SELECT:
                break
            elif event is NavEvent.LEFT:
                self._selected_index -= 1
            elif event is NavEvent.RIGHT:
                self._selected_index += 1

            if not self.WRAP:
                self._selected_index = min(len(users)-1, max(self._selected_index, 0))

            wrap_count, index = divmod(self._selected_index, len(users))
            self.animate_scroll_toward(wrap_width*wrap_count + users[index][0], 0)
            draw(index)

        self._scroll = [0, 0]
        initials = users[self._selected_index % len(users)][1]
        if initials == 'new':
            initials = self.initials_screen.run('NEW PLAYER')
        elif initials == 'guest':
            initials = None

        self._selected_index = 0
        return initials

# ---------------------------------------------------------------------------
# LoginSession
# ---------------------------------------------------------------------------

class LoginSession:
    """
    Context manager wrapping PlayerLoginScreen.run() so callers get a
    scoped `initials` value from a single, clear entry/exit point:

        with LoginSession(self.login) as initials:
            ...play games as `initials`...

    There's nothing to release today, but this gives the login flow one
    place to grow into (e.g. clearing the DMD on the way out) without
    touching every call site again.
    """

    def __init__(self, login_screen: PlayerLoginScreen) -> None:
        self.login_screen = login_screen
        self.initials: Optional[str] = None

    def __enter__(self) -> Optional[str]:
        self.initials = self.login_screen.run()
        return self.initials

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False
