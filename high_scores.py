"""
high_scores.py — Phase 8: High score persistence

Single responsibility: read and write SCORE_DB_PATH (JSON) — a dict keyed
by ROM name. Each ROM entry tracks:

  - high_score : the best score ever recorded for that ROM, no initials
                  attached (just the number).
  - players    : dict of initials -> that player's personal best score
                  on that ROM. Unlimited entries, one per player.

Does not touch the DMD or know about VideoModeResult — ScoreStore composes
this with display logic in a later step.

File format
-----------
{
  "t2_l8": {
    "high_score": 4200000,
    "players": {
      "MHL": 4200000,
      "AAA": 3000000
    }
  }
}

Base file is `{}` and grows from there; a ROM's "players" dict starts
empty and gains an entry the first time that player scores on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
import logging
import os
from pathlib import Path
import time
from typing import Optional

from screens import Screen
from text_to_dmd import RandomColor
from vm_types import GameEntry, VideoModeResult, ScreenState, SessionContext

@dataclass
class RomScores:
    high_score: int = 0
    players: dict[str, int] = field(default_factory=dict)


@dataclass
class SubmitResult:
    is_new_high_score: bool
    is_personal_best: bool
    previous_best: Optional[int]   # this player's previous best on this rom, if any


@dataclass
class PlayerScoreEntry:
    rom: str
    score: int
    is_high_score: bool   # True if this equals the rom's all-time high score

    def __str__(self):
        return f'{self.rom}:{self.score}{"!" if self.is_high_score else ""}'

    def __repr__(self):
        return str(self)


class HighScoreStore:
    """
    Reader/writer for per-ROM high scores: one all-time high score per ROM,
    plus one personal-best score per player (by initials) per ROM.

    Usage
    -----
        store = HighScoreStore(SCORE_DB_PATH)
        result = store.submit_score("t2_l8", 4_200_000, "MHL")
        if result.is_new_high_score:
            print("New high score!")
    """

    def __init__(self, db_path: Optional[Path]=None) -> None:
        if db_path is None:
            db_path = Path(__file__).parent / 'scores.json'
        self.db_path = Path(db_path)
        self.log = logging.getLogger("HighScoreStore")
        self._data: dict[str, RomScores] = {}

        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load the JSON file, or start from an empty table if absent/corrupt."""
        if not self.db_path.exists():
            self.log.info('scores json does not exist. creating %s', self.db_path)
            self._data = {}
            return
        try:
            raw = json.loads(self.db_path.read_text())
        except (json.JSONDecodeError, OSError):
            self.log.error(
                "Could not read %s — starting from an empty table",
                self.db_path, exc_info=True,
            )
            self._data = {}
            return
        self._data = {
            rom: RomScores(
                high_score=entry.get("high_score", 0),
                players=dict(entry.get("players", {})),
            )
            for rom, entry in raw.items()
        }

    def save(self) -> None:
        """Write the current table back to disk (atomic via tmp + replace)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        serialisable = {
            rom: asdict(entry)
            for rom, entry in self._data.items()
        }
        tmp_path = self.db_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(serialisable, indent=2))
        tmp_path.replace(self.db_path)
        self.log.info('saved scores as %s', self.db_path)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def high_score(self, rom: str) -> Optional[int]:
        """All-time high score for rom, or None if no scores recorded yet."""
        entry = self._data.get(rom)
        return entry.high_score if entry else None

    def player_score(self, rom: str, initials: str) -> Optional[int]:
        """A given player's personal best on rom, or None if they haven't played it."""
        entry = self._data.get(rom)
        if not entry:
            return None
        return entry.players.get(initials.upper()[:3])

    def highest_scores(self) -> dict[str, PlayerScoreEntry]:
        results: dict[str, PlayerScoreEntry] = {}
        for rom, entry in self._data.items():
            score = entry.high_score
            if score is None:
                continue
            results[rom] = PlayerScoreEntry(
                rom=rom,
                score=score,
                is_high_score=False,
            )
        return results

    def scores_for_player(self, initials: Optional[str]) -> dict[str, PlayerScoreEntry]:
        """
        All of a player's personal-best scores across every ROM, each
        flagged with whether it's that ROM's all-time high score.
        """
        if initials is None:
            return self.highest_scores()

        initials = initials.upper()[:3]
        results: dict[str, PlayerScoreEntry] = {}
        for rom, entry in self._data.items():
            score = entry.players.get(initials)
            if score is None:
                continue
            results[rom] = PlayerScoreEntry(
                rom=rom,
                score=score,
                is_high_score=(score and score == entry.high_score),
            )
        return results

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def submit_score(self, ctx: SessionContext) -> SubmitResult:
        """
        Record a score for a player on rom.

        Updates the player's personal best only if score beats their prior
        best on this rom (lower scores are ignored, not overwritten).
        Updates the rom's all-time high score if score beats it.
        Saves to disk immediately on any change.
        """
        initials = ctx.initials
        score = ctx.score
        game = ctx.game
        
        self.log.info('submitting score %s on %s for %s', score, game, initials)
        rom = game.unique_name
        score = score or 0

        entry = self._data.setdefault(rom, RomScores())

        previous_best = entry.players.get(initials)

        if initials:
            initials = initials.upper()[:3]
            is_personal_best = previous_best is None or score > previous_best
        else:
            is_personal_best = False

        is_new_high_score = score >= entry.high_score

        changed = False
        if is_personal_best:
            assert initials, 'logic fail, initials is always truthy by now'
            entry.players[initials] = score
            changed = True
        if is_new_high_score:
            entry.high_score = score
            changed = True

        if changed:
            self.save()

        submitted_result = SubmitResult(
            is_new_high_score=is_new_high_score,
            is_personal_best=is_personal_best,
            previous_best=previous_best,
        )
        self.log.info('result %s', submitted_result)
        return submitted_result

class SaveHighScoreScreen(Screen):
    def __init__(self,
        display: DMDDisplay,
        buttons: ButtonInput,
        scores: HighScoreStore,
        players: PlayerStore
    ):
        super().__init__(display, buttons)
        self.scores = scores
        self.players = players

    def run(self, ctx: SessionContext) -> ScreenState:
        if not ctx.initials:
            return ScreenState.NEED_HIGH_SCORE_INITIALS
        self.players.add_player(ctx.initials)
        result = self.scores.submit_score(ctx)
        if result.is_new_high_score:
            end_time = time.monotonic() + 10
            while time.monotonic() < end_time:
                self.text.box(0, 0, self.text.width, self.text.height, color=RandomColor(0,2))
                self.text.draw_text(
                    text = 'NEW HIGH SCORE',
                    font = 15,
                    center = True,
                    x = self.text.width//2,
                    y = 2,
                    outline = 1
                )
                self.text.draw_text(
                    text = f'{ctx.score:,}',
                    font = 15,
                    center = True,
                    x = self.text.width//2,
                    y = self.text.height//2,
                    outline = 1
                )
                self.show()
        return ScreenState.SAVED_HIGH_SCORE
