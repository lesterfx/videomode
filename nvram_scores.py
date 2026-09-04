"""
nvram_scores.py — Phase 8 helper: read a game's live Player 1 score.

This program makes use of content from the Pinball Memory Maps project
(https://github.com/tomlogic/pinmame-nvram-maps), by Tom Collins, used
under the GNU Lesser General Public License v3.0. A trimmed subset of
that project's map/platform JSON files — covering just the ROMs in
games.json — is vendored under nvram_maps/.

What this reads
----------------
Each ROM's map file documents a `game_state.scores` list (one entry per
player). We only ever read index 0 ("Player 1") — there is no
multiplayer video mode in this project, so tracking other players'
scores or the persisted high-score table is out of scope here.

How the read works
-------------------
libpinmame exposes PinmameReadMainCPUByte(address, &value), which reads
one byte directly from the main CPU's address space — the same address
space the nvram-maps `start`/`offsets` fields describe. Every platform
in games.json (WPC, Whitestar, Data East, Gottlieb System 3) is a
single-main-CPU, big-endian, BCD-score design, so this module only needs
to support that one combination; it does not implement the rest of the
nvram-maps spec (enum/bits/ch/dipsw/checksums, nibble packing, DIP
switches, etc).

IMPORTANT — call this before PinMAMEBridge.stop()
--------------------------------------------------
PinmameReadMainCPUByte() only succeeds while libpinmame's emulator
thread is still marked running. If you read the score after stop() has
been called, every byte read will fail and get_player1_score() will
return None. rom_session.py currently calls pinmame.stop() before
pinmame.get_score() — that ordering needs to change for scores to
ever come back non-empty; see PinMAMEBridge.get_score().
"""

from __future__ import annotations

import ctypes
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("nvram_scores")

_MAPS_DIR = Path(__file__).parent / "nvram_maps"

_index_cache: Optional[dict] = None
_map_cache: dict[str, dict] = {}
_platform_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Map / platform file loading (cached — these are small, static JSON files)
# ---------------------------------------------------------------------------

def _load_index() -> dict:
    global _index_cache
    if _index_cache is None:
        _index_cache = json.loads((_MAPS_DIR / "index.json").read_text())
    assert isinstance(_index_cache, dict), 'index.json should store a dict'
    return _index_cache


def _load_map(rom_name: str) -> Optional[dict]:
    rel_path = _load_index().get(rom_name)
    if rel_path is None:
        return None
    if rel_path not in _map_cache:
        _map_cache[rel_path] = json.loads((_MAPS_DIR / rel_path).read_text())
    return _map_cache[rel_path]


def _load_platform(name: str) -> dict:
    if name not in _platform_cache:
        path = _MAPS_DIR / "platforms" / f"{name}.json"
        _platform_cache[name] = json.loads(path.read_text())
    return _platform_cache[name]


# ---------------------------------------------------------------------------
# Descriptor interpretation — only the subset this project needs
# ---------------------------------------------------------------------------

def _to_int(value) -> int:
    """Map addresses may be a plain int or a '0xNNNN' hex string."""
    if isinstance(value, str):
        return int(value, 16)
    return int(value)


def _byte_addresses(descriptor: dict) -> list[int]:
    """
    Resolve a descriptor's 'start'+'length' (contiguous) or 'offsets'
    (explicit, for non-contiguous byte layouts e.g. some Data East
    scores) into an ordered list of byte addresses, most-significant
    byte first.
    """
    if "offsets" in descriptor:
        return [_to_int(a) for a in descriptor["offsets"]]
    start = _to_int(descriptor["start"])
    length = descriptor.get("length", 1)
    return list(range(start, start + length))


def _decode_bcd(byte_values: list[int]) -> int:
    """
    Big-endian binary-coded decimal: each byte holds two decimal digits,
    e.g. the byte sequence 0x12 0x34 decodes to 1234. Per the
    nvram-maps spec, nibbles 0xA-0xF count as 0.
    """
    digits: list[int] = []
    for b in byte_values:
        hi, lo = (b >> 4) & 0xF, b & 0xF
        digits.append(hi if hi <= 9 else 0)
        digits.append(lo if lo <= 9 else 0)
    value = 0
    for d in digits:
        value = value * 10 + d
    return value


_DECODERS = {
    "bcd": _decode_bcd,
}


# ---------------------------------------------------------------------------
# libpinmame binding
# ---------------------------------------------------------------------------

def _configure_lib(lib) -> None:
    """Attach ctypes argtypes/restype for PinmameReadMainCPUByte, once
    per lib handle. Idempotent — safe to call on every read."""
    if getattr(lib, "_nvram_scores_configured", False):
        return
    lib.PinmameReadMainCPUByte.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint8),
    ]
    lib.PinmameReadMainCPUByte.restype = ctypes.c_int
    lib._nvram_scores_configured = True


def _read_byte(lib, address: int) -> Optional[int]:
    value = ctypes.c_uint8(0)
    ok = lib.PinmameReadMainCPUByte(address, ctypes.byref(value))
    if not ok:
        return None
    return value.value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def has_map(rom_name: str) -> bool:
    """True if this ROM has a known nvram-maps entry."""
    return rom_name in _load_index()

def get_player1_score(lib, rom_name: str) -> Optional[int]:
    """
    Read Player 1's current score live from the running emulator.

    Args:
        lib:      The ctypes CDLL handle for libpinmame (e.g.
                   PinMAMEBridge._lib).
        rom_name: PinMAME short ROM name, e.g. "t2_l8".

    Returns:
        The score as an int, or None if the ROM has no known map, the
        map has no usable Player 1 score descriptor, or a memory read
        failed (most likely because the emulator has already stopped —
        see the module docstring about call order).
    """
    game_map = _load_map(rom_name)
    if game_map is None:
        log.warning("No nvram map for ROM %r — cannot read score", rom_name)
        return None

    scores = game_map.get("game_state", {}).get("scores")
    if not scores:
        log.warning("Map for %r has no game_state.scores entry", rom_name)
        return None

    descriptor = scores[0]  # Player 1 only — no multiplayer video modes
    encoding = descriptor.get("encoding")
    decode = _DECODERS.get(encoding)
    if decode is None:
        log.warning(
            "Unsupported encoding %r for %r Player 1 score", encoding, rom_name
        )
        return None

    _configure_lib(lib)

    raw_bytes = []
    for address in _byte_addresses(descriptor):
        byte_value = _read_byte(lib, address)
        if byte_value is None:
            log.warning(
                "PinmameReadMainCPUByte failed at 0x%04X for %r",
                address, rom_name,
            )
            return None
        raw_bytes.append(byte_value)

    return decode(raw_bytes)