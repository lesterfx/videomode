"""
players.py — Phase 8c: Recent players list

Tracks player initials sorted by recency (most recent first), persisted to
players.json.  Lets a returning player quickly pick their initials again
instead of re-entering them, and surfaces the current player at the top
of the list.

File format
-----------
players.json is a JSON array of initials strings, most-recent-first:

    ["ARL", "MHL", "YCL"]

Persistence uses the same atomic write pattern as HighScoreStore: write to
a temporary file, then os.replace() over the target, so a crash mid-write
never leaves a corrupt or truncated players.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional


DEFAULT_PLAYERS_PATH = Path(os.path.dirname(__file__)) / 'players.json'

_MAX_INITIALS_LEN = 3


class PlayerStore:
    """
    Persists and orders the list of player initials by recency.

    Responsibilities
    -----------------
      - get_players()          → full recency-ordered list (most recent first)
      - add_player(initials)   → add a new player at the top of the list
      - move_to_top(initials)  → mark an existing player as most recent

    The list is re-read from disk on every call rather than cached in
    memory, since this is a low-frequency, low-volume operation (a handful
    of reads/writes per session) — a cache isn't worth the risk of going
    stale relative to another process touching the same file.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_PLAYERS_PATH
        self.log = logging.getLogger("PlayerStore")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_players(self) -> list[str]:
        """Return all known player initials, most recently played first."""
        return self._load()

    def add_player(self, initials: Optional[str]) -> None:
        """
        Add a player's initials to the top of the list.

        If the initials are already present, this behaves exactly like
        move_to_top() — no duplicate entry is created.
        """
        if not initials:
            return
        initials = self._normalize(initials)
        players = self._load()
        if initials in players:
            players.remove(initials)
        players.insert(0, initials)
        self._save(players)
        self.log.info("Added/promoted player %r — %d known players",
                       initials, len(players))

    def move_to_top(self, initials: str):
        """
        Move an existing player's initials to the top of the list (most
        recent) — call this once a video mode session finishes.

        If the initials aren't already in the list, they're added, same
        as add_player(). There's no meaningful difference between "new
        player" and "returning player" once a session has just been played.
        """
        self.add_player(initials)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _normalize(self, initials: str) -> str:
        initials = (initials or "").strip().upper()[:_MAX_INITIALS_LEN]
        if not initials:
            raise ValueError("initials must be a non-empty string")
        return initials

    def _load(self) -> list[str]:
        if not self.db_path.exists():
            return []
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.log.error("players.json unreadable/corrupt — treating as empty",
                            exc_info=True)
            return []
        if not isinstance(data, list):
            self.log.error("players.json root is not a list — treating as empty")
            return []
        return [str(p) for p in data]

    def _save(self, players: list[str]) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.db_path.with_suffix(self.db_path.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(players, f)
        tmp_path.replace(self.db_path)


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        store = PlayerStore(Path(tmp) / "players.json")

        print("Empty store:", store.get_players())

        store.add_player("arl")
        store.add_player("mhl")
        store.add_player("ycl")
        print("After 3 adds:", store.get_players())

        store.move_to_top("arl")
        print("After moving ARL to top:", store.get_players())

        store.add_player("mhl")
        print("After re-adding MHL (dup):", store.get_players())

        print("Done.")