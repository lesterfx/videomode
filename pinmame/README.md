# Phase 1 — libpinmame Python binding

## What's here

```
pinmame/
  __init__.py       – package root
  _types.py         – ctypes mirrors of every struct / enum / callback typedef
                      from libpinmame.h (master, May 2026)
  _lib.py           – library discovery + argtypes/restype binding for every
                      exported symbol
  session.py        – PinmameSession  (high-level context-manager wrapper)
  dmd_render.py     – ASCII-art + ANSI-colour terminal renderers

dmd_demo.py         – runnable smoke-test / demo
```

---

## Getting libpinmame.so

Build it from source (takes ~5 min on a modern box):

```bash
git clone --recursive https://github.com/vpinball/pinmame.git
cd pinmame
cmake -B build -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIB=ON
cmake --build build -j$(nproc)
# Output: build/libpinmame.so  (Linux) or build/libpinmame.dylib  (macOS)
```

Put your ROM zips in `~/.pinmame/roms/`.

---

## Quickstart

```bash
# Auto-detect the library
python dmd_demo.py --game t2_l8 --roms ~/.pinmame/roms

# Explicit .so path
python dmd_demo.py --game t2_l8 \
                   --roms ~/.pinmame/roms \
                   --lib ./build/libpinmame.so

# ANSI 256-colour mode (requires a modern terminal)
python dmd_demo.py --game t2_l8 --roms ~/.pinmame/roms --ansi

# Verify ctypes struct layout without a .so (run this first)
python dmd_demo.py --verify-only
```

Or as a library:

```python
from pinmame.session import PinmameSession
from pinmame.dmd_render import print_ascii_frame
from pinmame._types import DmdMode

def on_frame(index, frame_bytes, layout):
    print_ascii_frame(frame_bytes, layout, header=f"frame index={index}")

with PinmameSession(rom_path="~/.pinmame/roms", game="t2_l8") as pm:
    pm.on_display_updated = on_frame
    pm.run()
```

---

## Architecture decisions

| Decision | Rationale |
|---|---|
| `ctypes` over `cffi` | Zero build step; ships with CPython; argtypes/restype give adequate type safety for this surface area |
| All callbacks kept alive in `self._c_callbacks` | ctypes `CFUNCTYPE` objects are reference-counted; if they're GC'd the emulation thread crashes |
| `DmdMode.RAW` default | Raw shade values (0–3 for 4-shade, 0–15 for 16-shade) are lossless; BRIGHTNESS mode normalises to 0–100 which loses precision |
| `bytes()` snapshot in callback | The `p_displayData` pointer is only valid inside the callback; we copy out immediately before returning |
| `on_log_message` receives format string only | `va_list` is opaque in ctypes; the C string is the format template. If you need formatted output, pipe the log to `PinmameSetPath` or filter from the emulator thread |

---

## Callback firing order for a DMD game (e.g. T2)

```
PinmameRun("t2_l8")
  → on_state_updated(state=1)        # emulator started
  → on_display_available(index=0)    # DMD registered: 128×32, depth=2
  → on_display_updated(index=0, ...) # first frame (and every ~16 ms after)
  → on_solenoid_updated(...)         # coils fire during attract mode
  → ...
Ctrl-C
  → PinmameStop()
  → on_state_updated(state=0)
```

---

## Known rough edges / next steps

- **`va_list` in log callback** — ctypes cannot portably iterate a `va_list`.
  For now the raw format string is forwarded.  A C shim that pre-formats it
  would be clean but adds a build step (Phase 2 concern).
- **Audio** — `on_audio_available` / `on_audio_updated` stubs return 0 (mute).
  Wire up to `sounddevice` or `pyaudio` in Phase 2.
- **Solenoid mask** — `PinmameSetSolenoidMask` is bound but not exposed on
  `PinmameSession`; add if needed.
- **Thread safety** — callbacks fire on the libpinmame emulation thread.
  For anything beyond printing, push frames to a `queue.Queue` and consume
  on the main thread.
