import sys, os, ctypes, time
sys.path.insert(0, '.')
from pinmame._lib import _find_libpinmame, _load
from pinmame._types import *

lib = _load(_find_libpinmame())

# Minimal config with a key-reporting fn_IsKeyPressed
frame = [0]
cfg = PinmameConfig()
cfg.audioFormat = int(AudioFormat.FLOAT)
cfg.sampleRate  = 44100
cfg.vpmPath     = os.path.expanduser("~/.pinmame/").encode()

cfg.cb_OnStateUpdated      = OnStateUpdatedFn(lambda s, u: None)
cfg.cb_OnDisplayAvailable  = OnDisplayAvailableFn(lambda i, n, p, u: None)
cfg.cb_OnDisplayUpdated    = OnDisplayUpdatedFn(lambda i, d, p, u: None)
cfg.cb_OnAudioAvailable    = OnAudioAvailableFn(lambda p, u: 0)
cfg.cb_OnAudioUpdated      = OnAudioUpdatedFn(lambda p, n, u: 0)
cfg.cb_OnMechAvailable     = OnMechAvailableFn(lambda n, p, u: None)
cfg.cb_OnMechUpdated       = OnMechAvailableFn(lambda n, p, u: None)
cfg.cb_OnSolenoidUpdated   = OnSolenoidUpdatedFn(lambda p, u: None)
cfg.cb_OnConsoleDataUpdated= OnConsoleDataUpdatedFn(lambda p, n, u: None)
cfg.cb_OnSoundCommand      = OnSoundCommandFn(lambda b, c, u: None)

_libc = ctypes.CDLL(None)
_libc.vsnprintf.restype = ctypes.c_int
_libc.vsnprintf.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                             ctypes.c_char_p, ctypes.c_void_p]
def _log(level, fmt, va, ud):
    if fmt:
        buf = ctypes.create_string_buffer(512)
        _libc.vsnprintf(buf, 512, fmt, va)
        print(f"[L{level}] {buf.value.decode(errors='replace').rstrip()}")
cfg.cb_OnLogMessage = OnLogMessageFn(_log)

# Key sequence: frames 0-9 = Shift+F7 (save), frames 10-19 = NUMBER_1 (slot)
def _key(keycode, ud):
    f = frame[0]
    if   0  < f < 10  and keycode in (Keycode.LEFT_SHIFT, Keycode.F7):
        print(f'{f} shift+f7')
        return 1
    elif 10 <= f < 20  and keycode == Keycode.NUMBER_1:
        print(f'{f} 1')
        return 1
    return 0
cfg.fn_IsKeyPressed = IsKeyPressedFn(_key)

lib.PinmameSetConfig(ctypes.byref(cfg))
lib.PinmameSetPath(FileType.ROMS,  os.path.expanduser("~/.pinmame/roms").encode())
lib.PinmameSetPath(FileType.NVRAM, os.path.expanduser("~/.pinmame/nvram").encode())
lib.PinmameSetHandleKeyboard(0)
lib.PinmameSetHandleMechanics(0)
lib.PinmameSetDmdMode(0)

lib.PinmameRun(b"t2_l8")
time.sleep(1)   # let it boot

sta_dir = os.path.expanduser("~/.pinmame/sta/")
os.makedirs(sta_dir, exist_ok=True)

print("Triggering Shift+F7 → 1 ...")
for _ in range(120):           # 2 s at ~60 fps
    frame[0] += 1
    time.sleep(1/60)

lib.PinmameStop()
import glob
print("sta files:", glob.glob(sta_dir + "*.sta"))