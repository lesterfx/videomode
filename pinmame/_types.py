"""
pinmame/_types.py
-----------------
ctypes mirror of libpinmame.h  (vpinball/pinmame master, May 2026).

Every enum, struct, and callback typedef lives here so the rest of the
binding can import cleanly without touching ctypes directly.
"""

import ctypes
import enum

# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

PINMAME_MAX_PATH   = 512
PINMAME_MAX_MECHSW = 20


# ---------------------------------------------------------------------------
# Enums  (pure-Python IntEnum – used for readability; raw ints go into C)
# ---------------------------------------------------------------------------

class LogLevel(enum.IntEnum):
    DEBUG = 0
    INFO  = 1
    ERROR = 2


class Status(enum.IntEnum):
    OK                    = 0
    CONFIG_NOT_SET        = 1
    GAME_NOT_FOUND        = 2
    GAME_ALREADY_RUNNING  = 3
    EMULATOR_NOT_RUNNING  = 4
    MECH_HANDLE_MECHANICS = 5
    MECH_NO_INVALID       = 6


class FileType(enum.IntEnum):
    ROMS      = 0
    NVRAM     = 1
    SAMPLES   = 2
    CONFIG    = 3
    HIGHSCORE = 4


class DmdMode(enum.IntEnum):
    BRIGHTNESS = 0   # 0-100 brightness per pixel
    RAW        = 1   # raw shade values (0-3 for 4-shade, 0-15 for 16-shade)


class SoundMode(enum.IntEnum):
    DEFAULT  = 0
    ALTSOUND = 1


class AudioFormat(enum.IntEnum):
    INT16 = 0
    FLOAT = 1


class DisplayType(enum.IntEnum):
    SEG16   = 0   # 16 segments
    SEG16R  = 1   # 16 segments, comma/period reversed
    SEG10   = 2   # 9 segs + comma
    SEG9    = 3
    SEG8    = 4   # 7 segs + comma
    SEG8D   = 5   # 7 segs + period
    SEG7    = 6
    SEG87   = 7   # 7 segs, comma every 3
    SEG87F  = 8
    SEG98   = 9
    SEG98F  = 10
    SEG7S   = 11  # small
    SEG7SC  = 12  # small + comma
    SEG16S  = 13  # split top/bottom
    DMD     = 14
    VIDEO   = 15
    SEG16N  = 16  # no commas
    SEG16D  = 17  # periods only
    # Modifier flags
    SEGHIBIT    = 0x40
    SEGREV      = 0x80
    DMDNOAA     = 0x100
    NODISP      = 0x200
    VIDEO_ROT90 = 0x400

    @classmethod
    def is_dmd(cls, raw: int) -> bool:
        return (raw & 0x3F) == cls.DMD


# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------

class PinmameDisplayLayout(ctypes.Structure):
    """Mirrors PinmameDisplayLayout in libpinmame.h."""
    _fields_ = [
        ("type",   ctypes.c_int32),
        ("top",    ctypes.c_int32),
        ("left",   ctypes.c_int32),
        ("length", ctypes.c_int32),
        ("width",  ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("depth",  ctypes.c_int32),
    ]

    @property
    def is_dmd(self) -> bool:
        return DisplayType.is_dmd(self.type)

    def __repr__(self) -> str:
        kind = "DMD" if self.is_dmd else "SEG"
        return (f"<DisplayLayout {kind} {self.width}×{self.height} "
                f"depth={self.depth} pos=({self.top},{self.left})>")


class PinmameAudioInfo(ctypes.Structure):
    _fields_ = [
        ("format",          ctypes.c_int),
        ("channels",        ctypes.c_int),
        ("sampleRate",      ctypes.c_double),
        ("framesPerSecond", ctypes.c_double),
        ("samplesPerFrame", ctypes.c_int),
        ("bufferSize",      ctypes.c_int),
    ]


class PinmameSwitchState(ctypes.Structure):
    _fields_ = [("swNo", ctypes.c_int), ("state", ctypes.c_int)]


class PinmameSolenoidState(ctypes.Structure):
    _fields_ = [("solNo", ctypes.c_int), ("state", ctypes.c_int)]


class PinmameLampState(ctypes.Structure):
    _fields_ = [("lampNo", ctypes.c_int), ("state", ctypes.c_int)]


class PinmameGIState(ctypes.Structure):
    _fields_ = [("giNo", ctypes.c_int), ("state", ctypes.c_int)]


class PinmameLEDState(ctypes.Structure):
    _fields_ = [
        ("ledNo",  ctypes.c_int),
        ("chgSeg", ctypes.c_int),
        ("state",  ctypes.c_int),
    ]


class PinmameMechSwitchConfig(ctypes.Structure):
    _fields_ = [
        ("swNo",     ctypes.c_int),
        ("startPos", ctypes.c_int),
        ("endPos",   ctypes.c_int),
        ("pulse",    ctypes.c_int),
    ]


class PinmameMechConfig(ctypes.Structure):
    _fields_ = [
        ("type",       ctypes.c_int),
        ("sol1",       ctypes.c_int),
        ("sol2",       ctypes.c_int),
        ("length",     ctypes.c_int),
        ("steps",      ctypes.c_int),
        ("initialPos", ctypes.c_int),
        ("acc",        ctypes.c_int),
        ("ret",        ctypes.c_int),
        ("sw",         PinmameMechSwitchConfig * PINMAME_MAX_MECHSW),
    ]


class PinmameMechInfo(ctypes.Structure):
    _fields_ = [
        ("type",   ctypes.c_int),
        ("length", ctypes.c_int),
        ("steps",  ctypes.c_int),
        ("pos",    ctypes.c_int),
        ("speed",  ctypes.c_int),
    ]


class PinmameGame(ctypes.Structure):
    _fields_ = [
        ("name",         ctypes.c_char_p),
        ("clone_of",     ctypes.c_char_p),
        ("description",  ctypes.c_char_p),
        ("year",         ctypes.c_char_p),
        ("manufacturer", ctypes.c_char_p),
        ("flags",        ctypes.c_uint32),
        ("found",        ctypes.c_int32),
    ]


# ---------------------------------------------------------------------------
# Callback typedefs  (must match PINMAMECALLBACK = default calling convention)
# ---------------------------------------------------------------------------

# void (*)(int state, void*)
OnStateUpdatedFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_int,       # state
    ctypes.c_void_p,    # userData
)

# void (*)(int index, int displayCount, PinmameDisplayLayout*, void*)
OnDisplayAvailableFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(PinmameDisplayLayout),
    ctypes.c_void_p,
)

# void (*)(int index, void* displayData, PinmameDisplayLayout*, void*)
OnDisplayUpdatedFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.POINTER(PinmameDisplayLayout),
    ctypes.c_void_p,
)

# int (*)(PinmameAudioInfo*, void*)
OnAudioAvailableFn = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.POINTER(PinmameAudioInfo),
    ctypes.c_void_p,
)

# int (*)(void* buffer, int samples, void*)
OnAudioUpdatedFn = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
)

# void (*)(int mechNo, PinmameMechInfo*, void*)
OnMechAvailableFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_int,
    ctypes.POINTER(PinmameMechInfo),
    ctypes.c_void_p,
)
OnMechUpdatedFn = OnMechAvailableFn

# void (*)(PinmameSolenoidState*, void*)
OnSolenoidUpdatedFn = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(PinmameSolenoidState),
    ctypes.c_void_p,
)

# void (*)(void* data, int size, void*)
OnConsoleDataUpdatedFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
)

# int (*)(PINMAME_KEYCODE keycode, void*)   — PINMAME_KEYCODE is unsigned int
IsKeyPressedFn = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_uint,
    ctypes.c_void_p,
)

# void (*)(PINMAME_LOG_LEVEL, const char* format, va_list args, void*)
# va_list is opaque — expose as void* so Python can at least hold the pointer
OnLogMessageFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_int,       # logLevel
    ctypes.c_char_p,    # format
    ctypes.c_void_p,    # va_list (opaque)
    ctypes.c_void_p,    # userData
)

# void (*)(int boardNo, int cmd, void*)
OnSoundCommandFn = ctypes.CFUNCTYPE(
    None,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_void_p,
)

# void (*)(PinmameGame*, void*)
GameCallbackFn = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(PinmameGame),
    ctypes.c_void_p,
)


# ---------------------------------------------------------------------------
# PinmameConfig  (struct passed to PinmameSetConfig)
# ---------------------------------------------------------------------------

class PinmameConfig(ctypes.Structure):
    """
    Mirrors PinmameConfig in libpinmame.h.

    Field order is CRITICAL – it must match the C struct byte-for-byte.
    vpmPath is a fixed-length char array of PINMAME_MAX_PATH bytes.
    """
    _fields_ = [
        ("audioFormat",           ctypes.c_int),                        # PINMAME_AUDIO_FORMAT
        ("sampleRate",            ctypes.c_int),
        ("vpmPath",               ctypes.c_char * PINMAME_MAX_PATH),
        ("cb_OnStateUpdated",     OnStateUpdatedFn),
        ("cb_OnDisplayAvailable", OnDisplayAvailableFn),
        ("cb_OnDisplayUpdated",   OnDisplayUpdatedFn),
        ("cb_OnAudioAvailable",   OnAudioAvailableFn),
        ("cb_OnAudioUpdated",     OnAudioUpdatedFn),
        ("cb_OnMechAvailable",    OnMechAvailableFn),
        ("cb_OnMechUpdated",      OnMechUpdatedFn),
        ("cb_OnSolenoidUpdated",  OnSolenoidUpdatedFn),
        ("cb_OnConsoleDataUpdated", OnConsoleDataUpdatedFn),
        ("fn_IsKeyPressed",       IsKeyPressedFn),
        ("cb_OnLogMessage",       OnLogMessageFn),
        ("cb_OnSoundCommand",     OnSoundCommandFn),
    ]


# ---------------------------------------------------------------------------
# Keycodes  (PINMAME_KEYCODE enum from libpinmame.h)
# ---------------------------------------------------------------------------
 
class Keycode(enum.IntEnum):
    A               = 0
    B               = 1
    C               = 2
    D               = 3
    E               = 4
    F               = 5
    G               = 6
    H               = 7
    I               = 8
    J               = 9
    K               = 10
    L               = 11
    M               = 12
    N               = 13
    O               = 14
    P               = 15
    Q               = 16
    R               = 17
    S               = 18
    T               = 19
    U               = 20
    V               = 21
    W               = 22
    X               = 23
    Y               = 24
    Z               = 25
    NUMBER_0        = 26
    NUMBER_1        = 27
    NUMBER_2        = 28
    NUMBER_3        = 29
    NUMBER_4        = 30
    NUMBER_5        = 31
    NUMBER_6        = 32
    NUMBER_7        = 33
    NUMBER_8        = 34
    NUMBER_9        = 35
    KEYPAD_0        = 36
    KEYPAD_1        = 37
    KEYPAD_2        = 38
    KEYPAD_3        = 39
    KEYPAD_4        = 40
    KEYPAD_5        = 41
    KEYPAD_6        = 42
    KEYPAD_7        = 43
    KEYPAD_8        = 44
    KEYPAD_9        = 45
    F1              = 46
    F2              = 47
    F3              = 48
    F4              = 49
    F5              = 50
    F6              = 51
    F7              = 52   # MAME default: save state
    F8              = 53   # MAME default: load state
    F9              = 54
    F10             = 55
    F11             = 56
    F12             = 57
    ESCAPE          = 58
    GRAVE_ACCENT    = 59
    MINUS           = 60
    EQUALS          = 61
    BACKSPACE       = 62
    TAB             = 63
    LEFT_BRACKET    = 64
    RIGHT_BRACKET   = 65
    ENTER           = 66
    SEMICOLON       = 67
    QUOTE           = 68
    BACKSLASH       = 69
    COMMA           = 71
    PERIOD          = 72
    SLASH           = 73
    SPACE           = 74
    INSERT          = 75
    DELETE          = 76
    HOME            = 77
    END             = 78
    PAGE_UP         = 79
    PAGE_DOWN       = 80
    LEFT            = 81
    RIGHT           = 82
    UP              = 83
    DOWN            = 84
    KEYPAD_DIVIDE   = 85
    KEYPAD_MULTIPLY = 86
    KEYPAD_SUBTRACT = 87
    KEYPAD_ADD      = 88
    KEYPAD_ENTER    = 90
    PRINT_SCREEN    = 91
    PAUSE           = 92
    LEFT_SHIFT      = 93
    RIGHT_SHIFT     = 94
    LEFT_CONTROL    = 95
    RIGHT_CONTROL   = 96
    LEFT_ALT        = 97
    RIGHT_ALT       = 98
    SCROLL_LOCK     = 99
    NUM_LOCK        = 100
    CAPS_LOCK       = 101
    LEFT_SUPER      = 102
    RIGHT_SUPER     = 103
    MENU            = 104
