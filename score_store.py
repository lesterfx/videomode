from pathlib import Path
from typing import Optional
import typing
if typing.TYPE_CHECKING:
    from dmd_display import DMDDisplay

from vm_types import VideoModeResult

# ---------------------------------------------------------------------------
# Phase 8 — Score store (stub)
# ---------------------------------------------------------------------------

class ScoreStore:
    """
    Persists video mode results and displays outcome on DMD.

    Responsibilities:
      - Read score from VideoModeResult (sourced from PinMAMEBridge.get_scores())
      - Append to SCORE_DB_PATH (JSON)
      - Compute and display high score on DMD
      - Brief pause before returning control to GameSelector

    Populated in Phase 8.
    """

    def __init__(self, display: 'DMDDisplay', db_path: Optional[Path]=None) -> None:
        self.display = display
        self.db_path = db_path

    def record(self, result: VideoModeResult) -> None:
        """Persist result and show score screen on DMD."""
        raise NotImplementedError("Phase 8")

    def high_score(self, rom_name: str) -> Optional[int]:
        """Return best recorded score for a given ROM, or None."""
        raise NotImplementedError("Phase 8")
