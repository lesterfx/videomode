#!/usr/bin/env python

"""
dmd_display.py — Phase 2: DMD hardware driver
Raspberry Pi 3B + Adafruit/hzeller RGB LED matrix (or terminal fallback)
 
Responsibilities (Phase 2 only):
  - Accept a raw pixel buffer (bytes, 1 byte per pixel, value 0-15)
  - Route it to either the physical LED matrix or the terminal renderer
 
Pixel buffer convention (shared across the whole project):
  - bytes object, length == width * height
  - each byte is one pixel, value 0-15 (4-bit intensity)
  - row-major order: pixel(x, y) == buf[y * width + x]
 
Text rendering and UI layouts are NOT handled here; see Phase 4 (GameSelector)
and Phase 8 (ScoreStore) which call render_text_to_frame() before show_frame().
 
DMD_TO_TERMINAL flag
    Set to True (or export DMD_TO_TERMINAL=1 in environment) to skip all
    hardware init and render every frame to the terminal via terminal_dmd.
    Useful for development and CI.
 
Hardware wiring assumptions (hzeller/rpi-rgb-led-matrix):
    - Two 64×32 panels chained horizontally → 128×32 total
    - GPIO mapping: adafruit-hat (change MATRIX_OPTIONS below if different)
    - Run as root or with appropriate GPIO permissions
"""
 
from __future__ import annotations

from collections import deque
import logging
import os
from random import random
import time
from typing import Callable, Optional
 
# ---------------------------------------------------------------------------
# Optional hardware import — graceful fallback
# ---------------------------------------------------------------------------
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore
    _HW_AVAILABLE = True
except ImportError:
    _HW_AVAILABLE = False
 

try:
    import numpy as np  # type: ignore
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

from terminal_dmd import print_frame
 
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

 
# Force terminal rendering even on hardware-capable machines
DMD_TO_TERMINAL: bool = bool(int(os.environ.get("DMD_TO_TERMINAL", "0")))
 
# hzeller matrix tuning — edit to match your panel wiring
MATRIX_OPTIONS: dict = dict(
    rows                     = 32,
    cols                     = 64,
    chain_length             = 2,       # two 64×32 panels chained
    parallel                 = 1,
    hardware_mapping         = "adafruit-hat",
    gpio_slowdown            = 4,       # default 2, increase if you see flickering on Pi 3
    brightness               = 30,      # 0-100
    disable_hardware_pulsing = True,    # avoids needing --led-no-hardware-pulse
    drop_privileges          = False,   # stay root — matches the whole reason we run as root
)
 
 
# ---------------------------------------------------------------------------
# DMDDisplay
# ---------------------------------------------------------------------------
 
class DMDDisplay:
    """
    Phase 2 — DMD hardware driver.
 
    Single responsibility: accept a pixel buffer and display it.
 
    Backends (selected at construction time):
      hardware  — hzeller/rpi-rgb-led-matrix (requires rgbmatrix package)
      terminal  — ANSI colour output via terminal_dmd.print_ascii_frame()
 
    Parameters
    ----------
    width, height   : panel dimensions in pixels (default 128×32)
    terminal_mode   : override; True forces terminal, False forces hardware,
                      None (default) uses DMD_TO_TERMINAL env flag and then
                      hardware auto-detection.
    label           : printed above each terminal frame (e.g. ROM name)
    """
 
    def __init__(
        self,
        width:         int            ,
        height:        int            ,
        terminal_mode: Optional[bool] = None,
        label:         str            = "",
        brightness:    int            = 30,
    ) -> None:

        # Amber colour mapping for hardware: intensity 0-15 → (R, G, B)
        # Real DMD phosphor is roughly (255, 88, 0) at full bright.
        self._R_MAX = 255
        self._G_MAX = 88
        self._B_MAX = 0

        self.set_bit_depth(2)

        self.width  = width
        self.height = height
        self.label  = label
        self.log    = logging.getLogger('DMDDisplay')

        self.shown = False
        self.label_getter: Optional[Callable] = None

        self.screenshotting = False
        self.stack = deque(maxlen=50)
        self.last_fps = time.monotonic()
        self.frames_since_last_fps = 0

        # Resolve backend
        if terminal_mode is True:
            self._use_terminal = True
        elif terminal_mode is False:
            self._use_terminal = False
        else:
            self._use_terminal = DMD_TO_TERMINAL or not _HW_AVAILABLE
 
        if self._use_terminal:
            self.log.info("DMDDisplay: terminal (ASCII) mode")
            self._matrix = None
            self._canvas = None
        else:
            self.log.info("DMDDisplay: hardware (rgbmatrix) mode")
            self._matrix, self._canvas = self._init_hardware(brightness)

        self.hardware = not self._use_terminal

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
 
    def set_bit_depth(self, depth: int) -> None:
        self.max_intensity = 2**depth-1
        def _intensity_to_rgb(intensity: int) -> tuple[int, int, int]:
            t = max(0, min(self.max_intensity, intensity)) / self.max_intensity
            return (round(self._R_MAX * t), round(self._G_MAX * t), round(self._B_MAX * t))
        
        # Pre-compute lookup table
        self._rgb_lut: list[tuple[int, int, int]] = [_intensity_to_rgb(i) for i in range(self.max_intensity+1)]



    def show_frame(self, frame: bytearray|bytes, layout=None) -> None:
        """
        Push a raw pixel buffer to the display.
 
        Parameters
        ----------
        frame : bytes of length width*height, each byte value 0-15
        """
        expected = self.width * self.height
        if len(frame) == expected:
            pass
        elif len(frame) < expected:
            letterbox = bytes((expected - len(frame)) // 2)
            frame = letterbox + frame + letterbox
        else:
            if len(frame) == 12288:
                src_w = 192
                src_h = 64
            else:
                raise ValueError(f'Unknown frame size {len(frame)}')
            frame = self._resample(frame, src_w, src_h)

        if self.screenshotting:
            self.stack.append(frame)

        if self._use_terminal:
            print_frame(frame, self.shown, self.label_getter, width=self.width, height=self.height)
            self.shown = True
        else:
            self._push_to_matrix(frame)

        self.frames_since_last_fps += 1
        now = time.monotonic()
        if now > self.last_fps + 1:
            # if not self.label_getter:
                # self.log.info('%d fps', self.frames_since_last_fps)
            self.last_fps = now
            self.frames_since_last_fps = 0

    def clear(self) -> None:
        """Blank the display."""
        self.show_frame(bytes(self.width * self.height))

    def set_brightness(self, level: int) -> None:
        """
        Adjust display brightness at runtime (0-100).
 
        RGBMatrixOptions.brightness only seeds the *initial* value at
        RGBMatrix() construction time; the options object itself is inert
        afterward. The live-adjustable knob is RGBMatrix.brightness — a
        property exposed directly on the matrix object that calls through
        to the underlying C++ SetBrightness() and takes effect on the very
        next frame, no reinitialisation needed. No-op in terminal mode.
        """
        level = max(0, min(100, level))
        if self._use_terminal or self._matrix is None:
            self.log.debug("set_brightness(%d) ignored — no hardware matrix", level)
            return
        self._matrix.brightness = level
        self.log.info("Brightness set to %d", level)

    def shutdown(self) -> None:
        """Release hardware resources."""
        if not self._use_terminal and self._matrix is not None:
            self.log.info("DMDDisplay shutdown")
            if self._canvas:
                self._canvas.Clear()
            self._matrix.SwapOnVSync(self._canvas)
            self._matrix = None
            self._canvas  = None
 
    # ------------------------------------------------------------------
    # Hardware initialisation
    # ------------------------------------------------------------------
 
    def _init_hardware(self, brightness):
        opts = RGBMatrixOptions()
        for attr, val in MATRIX_OPTIONS.items():
            setattr(opts, attr, val)
        opts.brightness = brightness
        matrix = RGBMatrix(options=opts)
        canvas = matrix.CreateFrameCanvas()
        self.log.debug(
            "LED matrix initialised: %dx%d chain=%d",
            opts.cols * opts.chain_length,
            opts.rows,
            opts.chain_length,
        )
        return matrix, canvas
 
    def _push_to_matrix(self, frame: bytearray|bytes) -> None:
        """Write pixel buffer to the LED matrix canvas and flip."""
        canvas = self._canvas
        if not self._matrix: return
        if canvas:
            canvas.Clear()
            for y in range(self.height):
                row_off = y * self.width
                for x in range(self.width):
                    intensity = frame[row_off + x] & 0x0F
                    try:
                        r, g, b   = self._rgb_lut[intensity]
                    except IndexError:
                        self.log.error(f'intensity {intensity} out of range')
                        raise
                    canvas.SetPixel(x, y, r, g, b)
        self._canvas = self._matrix.SwapOnVSync(canvas)
 
 
    def _resample(self, frame: bytearray|bytes, src_w: int, src_h: int) -> bytes:
        """
        Scale a frame from (src_w, src_h) down to fit the panel while
        preserving its aspect ratio, then center it on the panel with black
        bars (pillarbox if the source is relatively wider, letterbox if
        relatively taller).
 
        Scaling is done with an integer box filter (mean-pool over kxk
        blocks) rather than a stretch-to-fit resize, so a 3:1 source
        (e.g. 192×64) keeps its true proportions on a 4:1 panel (128×32)
        instead of being squashed. We pick the smallest integer factor k
        that (a) evenly divides both source dimensions, so the box average
        is exact with no edge-pixel weighting, and (b) brings the result
        within the panel's bounds. For 192×64 -> 128×32 this gives k=2,
        producing 96×32 content pillarboxed with 16px black bars each side.
 
        numpy's reshape+mean is used instead of a general image-resize
        library: since k is always an exact integer divisor here, this is
        just block-averaging, which numpy does in one vectorized call with
        no interpolation, image-object overhead, or extra imaging codecs
        needed on the Pi.
        """
        if not _NUMPY_AVAILABLE:
            raise RuntimeError(
                "Frame resolution "
                f"{src_w}×{src_h} does not match panel {self.width}×{self.height} "
                "and numpy is not installed. Install it with: "
                "pip install numpy --break-system-packages"
            )
 
        # Find the smallest integer downscale factor k (>=1) that evenly
        # divides both source dimensions AND brings the result within the
        # panel's bounds. Evenly dividing keeps the box average exact, with
        # no partial/edge-weighted blocks.
        k = None
        for candidate in range(1, max(src_w, src_h) + 1):
            if src_w % candidate or src_h % candidate:
                continue
            if src_w // candidate <= self.width and src_h // candidate <= self.height:
                k = candidate
                break
        if k is None:
            raise ValueError(
                f"Cannot box-filter {src_w}×{src_h} down to fit the "
                f"{self.width}×{self.height} panel — no integer factor both "
                "divides the source evenly and fits the panel. Pick a source "
                "resolution that's an exact multiple of a clean downscale factor."
            )
 
        content_w, content_h = src_w // k, src_h // k
 
        arr = np.frombuffer(frame, dtype=np.uint8).reshape(src_h, src_w)
        content = (
            arr.reshape(content_h, k, content_w, k)
            .mean(axis=(1, 3))
            .round()
            .astype(np.uint8)
        )
 
        canvas = np.zeros((self.height, self.width), dtype=np.uint8)
        x_off = (self.width  - content_w) // 2   # pillarbox (left/right bars)
        y_off = (self.height - content_h) // 2   # letterbox (top/bottom bars)
        canvas[y_off:y_off + content_h, x_off:x_off + content_w] = content
 
        return canvas.tobytes()

    def make_gradient_frame(self, width: int, height: int, dither: bool=True) -> bytes:
        """
        Generate a gradient test pattern:
        - horizontal ramp 0→15 across the width
        """
        buf = bytearray(width * height)
        if dither:
            row_bright = self.max_intensity
        else:
            row_bright = self.max_intensity+1

        for row in range(height):
            for col in range(width):
                intensity = col/width * row_bright
                if dither:
                    floor, frac = divmod(col/width * row_bright, 1)
                    intensity = floor if random() > frac else floor+1
                buf[row * width + col] = int(intensity)
        return bytes(buf)
    
    
    def make_checkerboard_frame(self, width: int, height: int, box_size: int=1) -> bytes:
        """Full-bright checkerboard — verifies pixel addressing."""
        buf = bytearray(width * height)
        for row in range(height):
            for col in range(width):
                buf[row * width + col] = self.max_intensity if (row//box_size + col//box_size) % 2 == 0 else 0
        return bytes(buf)
 
# ---------------------------------------------------------------------------
# CLI smoke test — verifies the pixel pipeline end-to-end
# ---------------------------------------------------------------------------
 
if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
 
    display = DMDDisplay(label="SMOKE TEST", width=128, height=32)
 
    print("=== gradient ===")
    start = time.monotonic()
    while time.monotonic() < start+5:
        display.show_frame(make_gradient_frame(display.width, display.height))
 
    print("\n=== checkerboard ===")
    for box_size in range(1, display.height+1):
        display.show_frame(make_checkerboard_frame(display.width, display.height, box_size))
        time.sleep(0.5)
 
    print("\n=== blank ===")
    display.clear()
 
    display.shutdown()
    print("Done.")