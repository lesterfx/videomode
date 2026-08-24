"""
bridge.py — PinMAMEBridge
Phase 1 implementation for pinmame_player.py

Sits between the high-level orchestration in pinmame_player.py and the
low-level ctypes binding in pinmame/session.py.

Lifecycle expected by pinmame_player.py
---------------------------------------
  bridge = PinMAMEBridge()
  bridge.connect()                          # load .so, configure callbacks
  bridge.load_snapshot(rom, snapshot_path)  # start ROM, restore state
  bridge.send_switch(sw, active)            # inject button events
  scores = bridge.get_score()               # read score from emulator memory
  bridge.stop()                             # stop cleanly

Callback hooks (set before load_snapshot)
-----------------------------------------
  bridge.dmd_callback   = callable(frame: bytes, layout: PinmameDisplayLayout)
  bridge.state_callback = callable(sol_no: int, sol_state: int)

The DMD callback fires on every rendered frame (libpinmame's emulation
thread).  Hand off to a queue if you need to do anything heavy.

The state_callback fires on every solenoid change and is the primary signal
used by EndDetector.  Lamp and switch change polling is available via
get_changed_lamps() / get_changed_switches() if needed in later phases.
"""

from __future__ import annotations

import ctypes
import logging
import time
import threading
from pathlib import Path
from typing import Callable, Optional

from pinmame._lib import _find_libpinmame, _load
from pinmame._types import (
    AudioFormat,
    DmdMode,
    FileType,
    SoundMode,
    Status,
    PinmameConfig,
    PinmameDisplayLayout,
    PinmameLampState,
    PinmameSolenoidState,
    PinmameSwitchState,
    OnStateUpdatedFn,
    OnDisplayAvailableFn,
    OnDisplayUpdatedFn,
    OnAudioAvailableFn,
    OnAudioUpdatedFn,
    OnMechAvailableFn,
    OnMechUpdatedFn,
    OnSolenoidUpdatedFn,
    OnConsoleDataUpdatedFn,
    IsKeyPressedFn,
    OnLogMessageFn,
    OnSoundCommandFn,
    Keycode
)

import nvram_scores

# How long to wait for PinmameIsRunning() to become true after PinmameRun()
_STARTUP_TIMEOUT_S  = 3.0
_STARTUP_POLL_S     = 0.05


class PinMAMEBridge:
    """
    Wraps pinmame/session.py (which wraps libpinmame.so) to match the
    interface expected by pinmame_player.py.

    This class owns the emulator lifecycle; PinmameSession.run() (the
    blocking convenience method) is intentionally not used here because
    load_snapshot() must be callable separately from connect().
    """

    def __init__(
        self,
        lib_path:    Optional[Path | str] = None,
        rom_path:    Path | str           = Path.home() / ".pinmame" / "roms",
        nvram_path:  Optional[Path | str] = None,
        dmd_mode:    DmdMode              = DmdMode.RAW,
        sample_rate: int                  = 44100,
    ) -> None:
        self._lib_path   = str(lib_path) if lib_path else None
        self._rom_path   = str(Path(rom_path).expanduser().resolve())
        self._vpm_path   = str(Path(self._rom_path).parent)
        self._nvram_path = (
            str(Path(nvram_path).expanduser().resolve())
            if nvram_path
            else str(Path(self._rom_path).parent / "nvram")
        )
        self._dmd_mode    = dmd_mode
        self._sample_rate = sample_rate

        # Populated in connect()
        self._lib = None

        # C function pointers — kept alive here so the GC never collects them
        # while the emulator thread is still calling into them.
        self._c_callbacks: list = []
        self._config: Optional[PinmameConfig] = None

        # Layout cache: display index → PinmameDisplayLayout
        self._layouts: dict[int, PinmameDisplayLayout] = {}

        # ------------------------------------------------------------------
        # Public callback hooks — assign before calling load_snapshot()
        # ------------------------------------------------------------------

        # dmd_callback(frame: bytes, layout: PinmameDisplayLayout) → None
        # Called on every DMD frame from the emulator thread.
        self.dmd_callback: Optional[Callable] = None

        # state_callback(sol_no: int, sol_state: int) → None
        # Called on every solenoid state change (used by EndDetector).
        self.state_callback: Optional[Callable] = None

        # log_callback(level: int, message: str) → None
        # Optional; defaults to the standard logging module.
        self.log_callback: Optional[Callable] = None

        self._pending_keys: dict[int, tuple[float, float]] = {}

        self.log = logging.getLogger('PinMAMEBridge')


    # ------------------------------------------------------------------
    # connect() — load the library and register all callbacks.
    # Must be called before load_snapshot().
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Load libpinmame.so and wire up all C callbacks."""
        self._lib = _load(_find_libpinmame(self._lib_path))
        self._config = self._build_config()
        lib = self._lib

        lib.PinmameSetConfig(ctypes.byref(self._config))
        lib.PinmameSetPath(FileType.ROMS,  self._rom_path.encode())
        lib.PinmameSetPath(FileType.NVRAM, self._nvram_path.encode())

        lib.PinmameSetHandleKeyboard(0)
        lib.PinmameSetHandleMechanics(0)
        lib.PinmameSetCheat(0)

        self.log.debug("PinMAMEBridge connected — roms=%s  nvram=%s",
                  self._rom_path, self._nvram_path)

    # ------------------------------------------------------------------
    # load_snapshot() — start a ROM and restore saved state.
    # ------------------------------------------------------------------

    def load_game(self, rom_name: str) -> None:
        """
        Start the emulator running rom_name and restore snapshot_path.

        libpinmame has no single "load state" call at startup; the accepted
        pattern is:
          1. PinmameRun(rom_name)          — starts emulation from cold boot
          2. Wait for IsRunning            — emulator thread is live
          3. PinmameSetDmdMode / SoundMode — must be after IsRunning
          4. Restore state file            — via MAME's built-in state system

        State restore (step 4) is done by injecting the MAME "load state"
        switch event.  The switch number is 0 (MAME internal); the snapshot
        filename without extension is passed as the slot name by writing it
        to the standard MAME state path, which libpinmame picks up from nvram.

        NOTE: full state-restore integration is completed in Phase 6.  For
        now this method starts the ROM cleanly and logs the snapshot path so
        Phase 6 can hook in without changing the call site.
        """
        self._rom_name = rom_name

        if self._lib is None:
            raise RuntimeError("connect() must be called before load_snapshot()")

        raw = self._lib.PinmameRun(self._rom_name.encode())
        try:
            status = Status(raw)
        except ValueError:
            status = None

        if status != Status.OK:
            raise RuntimeError(
                f"PinmameRun({self._rom_name!r}) failed: "
                f"{status.name if status else raw}"
            )
        self.log.debug("PinmameRun(%r) → %s", self._rom_name, status.name if status else raw)
        self._lamps = set()

        # Wait for the emulator thread to become ready
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_STARTUP_POLL_S)
            if self._lib.PinmameIsRunning():
                break
        else:
            raise RuntimeError(
                f"Emulator thread did not become ready within "
                f"{_STARTUP_TIMEOUT_S}s"
            )

        # Mode flags must be set after IsRunning
        self._lib.PinmameSetDmdMode(int(self._dmd_mode))
        self._lib.PinmameSetSoundMode(int(SoundMode.DEFAULT))

        self.log.info("Emulator running — ROM=%r", self._rom_name)

    # ------------------------------------------------------------------
    # send_switch() — inject a switch-matrix event into the emulator.
    # ------------------------------------------------------------------

    def send_switch(self, switch_number: int, active: bool) -> None:
        """
        Inject a switch event into the running emulation.

        active=True  → switch closed (button pressed)
        active=False → switch open   (button released)
        """
        if self._lib is None or not self._lib.PinmameIsRunning():
            return
        self._lib.PinmameSetSwitch(switch_number, int(active))

    # ------------------------------------------------------------------
    # get_score() — read current player scores from emulator memory.
    # ------------------------------------------------------------------

    def get_score(self) -> Optional[int]:
        """
        Return current player scores.

        libpinmame exposes raw memory regions but has no dedicated score API;
        scores live at game-specific offsets in the CPU RAM region.

        Phase 8 will implement per-game memory maps.  For now this returns
        an empty list so the call site in pinmame_player.py does not raise.
        """

        if getattr(self, "_rom_name", None) is None:
            return None
        score = nvram_scores.get_player1_score(self._lib, self._rom_name)
        return score

    # ------------------------------------------------------------------
    # stop() — shut down the emulator cleanly.
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop emulation.  Safe to call if already stopped."""
        if self._lib and self._lib.PinmameIsRunning():
            self._lib.PinmameStop()
            self.log.debug("PinMAMEBridge stopped")

    # ------------------------------------------------------------------
    # trigger_keycode() — send a keycode to the emulator for n frames
    # ------------------------------------------------------------------

    def _trigger_keycode(self, *keycodes: int, delay=0, duration=.5) -> None:
        """Report a keycode as pressed for a fixed number of callback invocations."""
        start = time.monotonic() + delay
        for keycode in keycodes:
            self._pending_keys[keycode] = (start, duration)

    def save_snapshot(self, index: int):
        number_code = getattr(Keycode, f'NUMBER_{index}')
        self._trigger_keycode(Keycode.F7, Keycode.LEFT_SHIFT)
        self._trigger_keycode(number_code, delay=1)

    def load_snapshot(self, index: int):
        number_code = getattr(Keycode, f'NUMBER_{index}')
        delay = 3
        self._trigger_keycode(Keycode.F7, delay=delay)
        self._trigger_keycode(number_code, delay=delay+1)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return bool(self._lib and self._lib.PinmameIsRunning())

    def get_changed_solenoids(self) -> list[tuple[int, int]]:
        """
        Poll for solenoid state changes since the last call.
        Returns a list of (sol_no, state) tuples.
        Used by EndDetector in Phase 7 as an alternative to the callback.
        """
        if not self.is_running or not self._lib:
            return []
        buf = (PinmameSolenoidState * 64)()
        count = self._lib.PinmameGetChangedSolenoids(buf)
        return [(buf[i].solNo, buf[i].state) for i in range(count)]

    def get_changed_lamps(self) -> list[tuple[int, int]]:
        """Poll for lamp state changes since the last call."""
        if not self.is_running or not self._lib:
            return []
        buf = (PinmameLampState * 256)()
        count = self._lib.PinmameGetChangedLamps(buf)
        return [(buf[i].lampNo, buf[i].state) for i in range(count)]
    
    def get_lamps(self) -> set[int]:
        for lamp, state in self.get_changed_lamps():
            if state:
                self._lamps.add(lamp)
            else:
                self._lamps.discard(lamp)
        return self._lamps

    # ------------------------------------------------------------------
    # Internal: build PinmameConfig with all C callbacks wired up.
    # ------------------------------------------------------------------

    def _build_config(self) -> PinmameConfig:
        c = self._c_callbacks   # keep all function pointers alive

        # ---- state updated ----------------------------------------------
        def _state_updated(state: int, _ud: ctypes.c_void_p) -> None:
            self.log.debug("on_state_updated: %d", state)

        cb_state = OnStateUpdatedFn(_state_updated)
        c.append(cb_state)

        # ---- display available ------------------------------------------
        def _display_available(
            index: int,
            display_count: int,
            p_layout: ctypes.POINTER(PinmameDisplayLayout),
            _ud: ctypes.c_void_p,
        ) -> None:
            snap = PinmameDisplayLayout()
            ctypes.memmove(ctypes.byref(snap), ctypes.byref(p_layout.contents),
                           ctypes.sizeof(PinmameDisplayLayout))
            self._layouts[index] = snap
            self.log.debug("display_available: index=%d %dx%d depth=%d",
                      index, snap.width, snap.height, snap.depth)

        cb_disp_avail = OnDisplayAvailableFn(_display_available)
        c.append(cb_disp_avail)

        # ---- display updated  →  dmd_callback ---------------------------
        def _display_updated(
            index: int,
            p_data: ctypes.c_void_p,
            p_layout: ctypes.POINTER(PinmameDisplayLayout),
            _ud: ctypes.c_void_p,
        ) -> None:
            if not self.dmd_callback:
                return
            layout = p_layout.contents
            if not layout.is_dmd:
                return
            if p_data is None:
                return
            try:
                n_bytes = layout.width * layout.height
                frame = bytes((ctypes.c_uint8 * n_bytes).from_address(p_data))
                self.dmd_callback(frame, layout)
            except:
                self.log.error('error in display_updated', exc_info=True)

        cb_disp_upd = OnDisplayUpdatedFn(_display_updated)
        c.append(cb_disp_upd)

        # ---- audio (muted stubs) ----------------------------------------
        cb_audio_avail = OnAudioAvailableFn(lambda p, u: 0)
        cb_audio_upd   = OnAudioUpdatedFn(lambda p, n, u: 0)
        c.extend([cb_audio_avail, cb_audio_upd])

        # ---- mechs (stubs) ----------------------------------------------
        cb_mech_avail = OnMechAvailableFn(lambda n, p, u: None)
        cb_mech_upd   = OnMechUpdatedFn(lambda n, p, u: None)
        c.extend([cb_mech_avail, cb_mech_upd])

        # ---- solenoid updated  →  state_callback ------------------------
        def _solenoid_updated(
            p_state: ctypes.POINTER(PinmameSolenoidState),
            _ud: ctypes.c_void_p,
        ) -> None:
            if self.state_callback:
                s = p_state.contents
                self.state_callback(s.solNo, s.state)

        cb_sol = OnSolenoidUpdatedFn(_solenoid_updated)
        c.append(cb_sol)

        # ---- console data (stub) ----------------------------------------
        cb_console = OnConsoleDataUpdatedFn(lambda p, n, u: None)
        c.append(cb_console)

        # ---- IsKeyPressed (no keyboard input) ---------------------------
        def _is_key_pressed(keycode: int, _ud) -> int:
            if keycode in self._pending_keys:
                start, duration = self._pending_keys[keycode]
                now = time.monotonic()
                if now >= start and now <= start+duration:
                    self.log.info(f'reporting key {keycode} ({Keycode(keycode).name}) pressed')
                    return 1
            return 0
        cb_key = IsKeyPressedFn(_is_key_pressed)
        c.append(cb_key)

        # ---- log message — forward to Python logging --------------------
        _libc = ctypes.CDLL(None)
        _libc.vsnprintf.restype  = ctypes.c_int
        _libc.vsnprintf.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t,
            ctypes.c_char_p, ctypes.c_void_p,
        ]

        def _log_message(
            level: int,
            fmt: bytes,
            va_args: ctypes.c_void_p,
            _ud: ctypes.c_void_p,
        ) -> None:
            if not fmt:
                return
            buf = ctypes.create_string_buffer(2048)
            _libc.vsnprintf(buf, ctypes.sizeof(buf), fmt, va_args)
            msg = buf.value.decode(errors="replace").rstrip()
            if self.log_callback:
                self.log_callback(level, msg)
            else:
                # Map libpinmame log levels (0=DEBUG, 1=INFO, 2=ERROR) to
                # Python logging levels
                py_level = (logging.DEBUG, logging.INFO, logging.ERROR)
                self.log.log(py_level[min(level, 2)], "[libpinmame] %s", msg)

        cb_log = OnLogMessageFn(_log_message)
        c.append(cb_log)

        # ---- sound command (stub) ----------------------------------------
        cb_snd = OnSoundCommandFn(lambda b, cmd, u: None)
        c.append(cb_snd)

        # ---- assemble ---------------------------------------------------
        cfg = PinmameConfig()
        cfg.audioFormat             = int(AudioFormat.FLOAT)
        cfg.sampleRate              = self._sample_rate
        cfg.vpmPath                 = (self._vpm_path + "/").encode()
        cfg.cb_OnStateUpdated       = cb_state
        cfg.cb_OnDisplayAvailable   = cb_disp_avail
        cfg.cb_OnDisplayUpdated     = cb_disp_upd
        cfg.cb_OnAudioAvailable     = cb_audio_avail
        cfg.cb_OnAudioUpdated       = cb_audio_upd
        cfg.cb_OnMechAvailable      = cb_mech_avail
        cfg.cb_OnMechUpdated        = cb_mech_upd
        cfg.cb_OnSolenoidUpdated    = cb_sol
        cfg.cb_OnConsoleDataUpdated = cb_console
        cfg.fn_IsKeyPressed         = cb_key
        cfg.cb_OnLogMessage         = cb_log
        cfg.cb_OnSoundCommand       = cb_snd

        return cfg
