"""
pinmame/_lib.py
---------------
Low-level ctypes wrapper around libpinmame.so / libpinmame.dylib.

Exposes every public symbol from the header with correct argtypes/restype,
then wraps them in thin Python methods on `PinmameLib`.

Callers normally don't use this directly – see PinmameSession in session.py.
"""

import ctypes
import ctypes.util
import os
import platform
import sys
from pathlib import Path
from typing import Optional

from ._types import (
    PINMAME_MAX_PATH,
    AudioFormat,
    DmdMode,
    FileType,
    SoundMode,
    Status,
    # structs
    PinmameConfig,
    PinmameDisplayLayout,
    PinmameAudioInfo,
    PinmameSwitchState,
    PinmameSolenoidState,
    PinmameLampState,
    PinmameGIState,
    PinmameLEDState,
    PinmameMechConfig,
    PinmameMechInfo,
    # callbacks
    GameCallbackFn,
)


# ---------------------------------------------------------------------------
# Library discovery
# ---------------------------------------------------------------------------

def _find_libpinmame(hint: Optional[str] = None) -> str:
    """
    Return the path to libpinmame shared library, raising OSError if none
    can be found.

    Search order:
      1. `hint` (caller-supplied explicit path)
      2. LIBPINMAME_PATH env var
      3. LIBPINMAME_PATH attribute on __main__
      4. Standard platform search (ctypes.util.find_library)
      5. A handful of well-known install locations
    """
    candidates: list[str] = []

    if hint:
        candidates.append(hint)

    env = os.environ.get("LIBPINMAME_PATH")
    if env:
        candidates.append(env)

    import __main__
    candidates.append(getattr(__main__, 'LIBPINMAME_PATH'))
    # ctypes.util.find_library searches LD_LIBRARY_PATH / dyld paths etc.
    found = ctypes.util.find_library("pinmame")
    if found:
        candidates.append(found)

    # Well-known paths
    system = platform.system()
    if system == "Linux":
        candidates += [
            "/usr/lib/libpinmame.so",
            "/usr/local/lib/libpinmame.so",
            str(Path.home() / ".pinmame" / "libpinmame.so"),
            "./libpinmame.so",
        ]
    elif system == "Darwin":
        candidates += [
            "/usr/local/lib/libpinmame.dylib",
            str(Path.home() / ".pinmame" / "libpinmame.dylib"),
            "./libpinmame.dylib",
        ]
    elif system == "Windows":
        candidates += [
            "libpinmame.dll",
            "./libpinmame.dll",
        ]

    for path in candidates:
        if path and Path(path).exists():
            return path
        # For bare names (no path separator) let the OS find them
        if path and os.sep not in path and "." in path:
            try:
                ctypes.CDLL(path)  # probe
                return path
            except OSError:
                pass

    raise OSError(
        "libpinmame shared library not found.\n"
        "  • Build from source: https://github.com/vpinball/pinmame\n"
        "  • Or set LIBPINMAME_PATH=/path/to/libpinmame.so"
    )


# ---------------------------------------------------------------------------
# Low-level loader
# ---------------------------------------------------------------------------

def _load(lib_path: str) -> ctypes.CDLL:
    lib = ctypes.CDLL(lib_path)
    _bind(lib)
    return lib


def _bind(lib: ctypes.CDLL) -> None:
    """Attach argtypes + restype to every exported symbol."""

    # ---- game enumeration ------------------------------------------------
    lib.PinmameGetGame.argtypes  = [ctypes.c_char_p, GameCallbackFn, ctypes.c_void_p]
    lib.PinmameGetGame.restype   = ctypes.c_int

    lib.PinmameGetGames.argtypes = [GameCallbackFn, ctypes.c_void_p]
    lib.PinmameGetGames.restype  = ctypes.c_int

    # ---- configuration ---------------------------------------------------
    lib.PinmameSetConfig.argtypes = [ctypes.POINTER(PinmameConfig)]
    lib.PinmameSetConfig.restype  = None

    lib.PinmameSetPath.argtypes = [ctypes.c_int, ctypes.c_char_p]
    lib.PinmameSetPath.restype  = None

    # ---- simple flags / modes -------------------------------------------
    for name in ("PinmameGetCheat", "PinmameGetHandleKeyboard",
                 "PinmameGetHandleMechanics"):
        getattr(lib, name).argtypes = []
        getattr(lib, name).restype  = ctypes.c_int

    for name in ("PinmameSetCheat", "PinmameSetHandleKeyboard",
                 "PinmameSetHandleMechanics"):
        getattr(lib, name).argtypes = [ctypes.c_int]
        getattr(lib, name).restype  = None

    lib.PinmameGetDmdMode.argtypes = []
    lib.PinmameGetDmdMode.restype  = ctypes.c_int
    lib.PinmameSetDmdMode.argtypes = [ctypes.c_int]
    lib.PinmameSetDmdMode.restype  = None

    lib.PinmameGetSoundMode.argtypes = []
    lib.PinmameGetSoundMode.restype  = ctypes.c_int
    lib.PinmameSetSoundMode.argtypes = [ctypes.c_int]
    lib.PinmameSetSoundMode.restype  = None

    # ---- lifecycle -------------------------------------------------------
    lib.PinmameRun.argtypes      = [ctypes.c_char_p]
    lib.PinmameRun.restype       = ctypes.c_int

    lib.PinmameIsRunning.argtypes = []
    lib.PinmameIsRunning.restype  = ctypes.c_int

    lib.PinmamePause.argtypes    = [ctypes.c_int]
    lib.PinmamePause.restype     = ctypes.c_int

    lib.PinmameIsPaused.argtypes = []
    lib.PinmameIsPaused.restype  = ctypes.c_int

    lib.PinmameReset.argtypes    = []
    lib.PinmameReset.restype     = ctypes.c_int

    lib.PinmameStop.argtypes     = []
    lib.PinmameStop.restype      = None

    lib.PinmameGetHardwareGen.argtypes = []
    lib.PinmameGetHardwareGen.restype  = ctypes.c_uint64

    # ---- switches --------------------------------------------------------
    lib.PinmameGetSwitch.argtypes  = [ctypes.c_int]
    lib.PinmameGetSwitch.restype   = ctypes.c_int

    lib.PinmameSetSwitch.argtypes  = [ctypes.c_int, ctypes.c_int]
    lib.PinmameSetSwitch.restype   = None

    lib.PinmameSetSwitches.argtypes = [
        ctypes.POINTER(PinmameSwitchState), ctypes.c_int
    ]
    lib.PinmameSetSwitches.restype = None

    # ---- solenoids -------------------------------------------------------
    lib.PinmameGetMaxSolenoids.argtypes = []
    lib.PinmameGetMaxSolenoids.restype  = ctypes.c_int

    lib.PinmameGetSolenoid.argtypes  = [ctypes.c_int]
    lib.PinmameGetSolenoid.restype   = ctypes.c_int

    lib.PinmameGetChangedSolenoids.argtypes = [ctypes.POINTER(PinmameSolenoidState)]
    lib.PinmameGetChangedSolenoids.restype  = ctypes.c_int

    # ---- lamps -----------------------------------------------------------
    lib.PinmameGetMaxLamps.argtypes = []
    lib.PinmameGetMaxLamps.restype  = ctypes.c_int

    lib.PinmameGetLamp.argtypes  = [ctypes.c_int]
    lib.PinmameGetLamp.restype   = ctypes.c_int

    lib.PinmameGetChangedLamps.argtypes = [ctypes.POINTER(PinmameLampState)]
    lib.PinmameGetChangedLamps.restype  = ctypes.c_int

    # ---- GIs -------------------------------------------------------------
    lib.PinmameGetMaxGIs.argtypes = []
    lib.PinmameGetMaxGIs.restype  = ctypes.c_int

    lib.PinmameGetGI.argtypes  = [ctypes.c_int]
    lib.PinmameGetGI.restype   = ctypes.c_int

    lib.PinmameGetChangedGIs.argtypes = [ctypes.POINTER(PinmameGIState)]
    lib.PinmameGetChangedGIs.restype  = ctypes.c_int

    # ---- LEDs ------------------------------------------------------------
    lib.PinmameGetMaxLEDs.argtypes = []
    lib.PinmameGetMaxLEDs.restype  = ctypes.c_int

    lib.PinmameGetChangedLEDs.argtypes = [
        ctypes.c_uint64, ctypes.c_uint64, ctypes.POINTER(PinmameLEDState)
    ]
    lib.PinmameGetChangedLEDs.restype  = ctypes.c_int

    # ---- mechs -----------------------------------------------------------
    lib.PinmameGetMaxMechs.argtypes = []
    lib.PinmameGetMaxMechs.restype  = ctypes.c_int

    lib.PinmameGetMech.argtypes  = [ctypes.c_int]
    lib.PinmameGetMech.restype   = ctypes.c_int

    lib.PinmameSetMech.argtypes  = [ctypes.c_int, ctypes.POINTER(PinmameMechConfig)]
    lib.PinmameSetMech.restype   = ctypes.c_int

    # ---- DIP switches ---------------------------------------------------
    lib.PinmameGetDIP.argtypes = [ctypes.c_int]
    lib.PinmameGetDIP.restype  = ctypes.c_int

    lib.PinmameSetDIP.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.PinmameSetDIP.restype  = None

    # ---- user data -------------------------------------------------------
    lib.PinmameSetUserData.argtypes = [ctypes.c_void_p]
    lib.PinmameSetUserData.restype  = None

    # ---- raw memory (added in recent libpinmame) -------------------------
    lib.PinmameGetRawMemoryRegion.argtypes = [ctypes.c_int]
    lib.PinmameGetRawMemoryRegion.restype  = ctypes.POINTER(ctypes.c_uint8)

    lib.PinmameGetRawMemoryRegionLength.argtypes = [ctypes.c_int]
    lib.PinmameGetRawMemoryRegionLength.restype  = ctypes.c_size_t
