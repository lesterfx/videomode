import logging
import time
import typing
from typing import Optional

from vm_types import EndDetectorConfig

if typing.TYPE_CHECKING:
    from videomode import PinMameBridge
 
class EndDetector:
    """
    Watches PinMAME internal state to detect when video mode ends.
 
    Detection strategy (v1): almost any solenoid firing during a video
    mode means the ball has been kicked out of a saucer/VUK/trough and
    the mode is over — that's true across the vast majority of DMD-era
    video modes we've looked at. So rather than maintain a per-game
    "this is the end solenoid" allowlist, we watch for ANY solenoid
    activation and treat it as an end signal — except numbers in
    `ignored_solenoids`, which is a short per-game denylist for coils
    that legitimately fire mid-mode (e.g. Fish Tales' topper fish-tail
    flapper on an extra-ball award).
 
    Detection is edge-triggered: we only fire on a solenoid transitioning
    from inactive to active, not on sustained "is active" level. This
    matches how real coils behave (they pulse) and avoids ever getting
    stuck in a state where the flag can't be set because something was
    already "on".
 
    Responsibilities:
      - Receive solenoid / lamp / switch state updates from PinMAMEBridge
      - Apply the any-solenoid-except-ignored heuristic above
      - Signal VideoModeSession when mode has concluded
 
    Populated in Phase 7.
    """
 
    def __init__(self, pinmame: 'PinMAMEBridge') -> None:
        self.pinmame = pinmame
        self._ended: bool = False
        self._config = EndDetectorConfig()
        self._started_at: float = 0.0
        self._triggering_solenoid: Optional[int] = None
        self._active = False
        self.log = logging.getLogger('EndDetector')

        self.pinmame.state_callback = self.on_state_update
 
    def reset(self, config: EndDetectorConfig, active: bool = True) -> None:
        """
        Call before each session to clear prior state.
 
        `config` should normally be built from the GameEntry being
        played, e.g.:
            detector.reset(EndDetectorConfig(
                ignored_solenoids=frozenset(game.ignored_solenoids)))
        """
        self._active = active
        self._ended = False
        self._config = config
        self._started_at = time.monotonic()
        self._triggering_solenoid = None
 
    def on_state_update(self, solenoid, state) -> None:
        """
        Receive a solenoid state update from PinMAMEBridge callback.

        """
        try:
            session_age = time.monotonic() - self._started_at
            if self._started_at == 0:
                session_age = 0
            # self.log.info(
            #     f"At {session_age:.4f}, solenoid {solenoid} changed state to {state}"
            # )

            if self._ended:
                return
                # self.log.info(
                #     f"Ignore solenoid {solenoid} change because ended"
                # )
            if not self._active:
                return
                # self.log.info(
                #     f"Ignore solenoid {solenoid} change because not active"
                # )
            if session_age < self._config.grace_period_seconds:
                # self.log.info(
                #     f"{session_age:.4f} < grace period {self._config.grace_period_seconds}"
                # )
                return
            if self._config.trigger_solenoid is not None and solenoid != self._config.trigger_solenoid:
                self.log.info(
                    f"Ignore solenoid {solenoid} because is not trigget_solenoid {self._config.trigger_solenoid}"
                )
                return
            if bool(state) != bool(self._config.solenoid_trigger_state):
                # self.log.info(
                #     f"Ignore solenoid {solenoid} change because state is not {self._config.solenoid_trigger_state}"
                # )
                return
            if solenoid in self._config.ignored_solenoids:
                # self.log.info(
                #     f"solenoid {solenoid} ignored in {self._config.ignored_solenoids}"
                # )
                return

            self._triggering_solenoid = solenoid
            self._ended = True
            self.log.info(
                "Video mode end detected: solenoid %d fired",
                self._triggering_solenoid,
            )

        except:
            self.log.error('error in on_state_udate', exc_info=True)
 
    @property
    def ended(self) -> bool:
        """True once video mode end has been detected."""
        return self._ended
 
    @property
    def triggering_solenoid(self) -> Optional[int]:
        """Which solenoid number triggered the end, once ended is True."""
        return self._triggering_solenoid
 