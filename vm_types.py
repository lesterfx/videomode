from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class GameParent:
    """One entry in the game selection list."""

    name: Optional[str] = None
    # display name shown on DMD

    rom: Optional[str] = None
    # ROM identifier passed to PinMAME

    left_flipper_switch: Optional[int] = None
    right_flipper_switch: Optional[int] = None
    launch_switch: Optional[int] = None
    # switch matrix value for the flipper and launch buttons used in video mode

    children: list['GameEntry'] = field(default_factory=list)
    # populated later, list of child GameEntry instances

    active_switches: list[int] = field(default_factory=list)
    # switches which should be set active during video mode session

    end_detector_config: Optional['EndDetectorConfig'] = None

    screenshot: Optional[str] = None


@dataclass
class GameEntry:
    parent: GameParent

    name: str = ''
    # optional name for this video mode, if more than one in a game

    snapshot_index: Optional[int] = None
    # save state restore index for this snapshot

    initials: Optional[str] = None
    high_score: int = 0
    # initials and points for the current high score

@dataclass
class VideoModeResult:
    """Outcome of a single video mode session."""
    game: GameEntry
    score: int
    duration_seconds: float
    ended_naturally: bool   # False if user quit or error occurred

@dataclass
class EndDetectorConfig:
    """Per-game tuning, sourced from GameEntry at session start."""
    trigger_solenoid: Optional[int] = None
    # Solenoid number that triggers end of video mode

    ignored_solenoids: frozenset[int] = field(default_factory=frozenset)
    # Solenoid numbers that fire during normal video-mode play and must
    # NOT be treated as an end signal (toppers, flashers routed through
    # the solenoid driver board, EB/knocker coils, etc).
 
    grace_period_seconds: float = 5.0
    # Solenoid edges are ignored for this long after reset(). Covers two
    # cases: (1) the snapshot restore itself can report solenoids as
    # "active" on the very first state update simply because that was
    # their held state when the snapshot was captured, and (2) some
    # video modes fire a solenoid (e.g. a flasher) at mode *start* rather
    # than at the end.

    solenoid_trigger_state: bool = True
    # whether rising or falling solenoid state should trigger end