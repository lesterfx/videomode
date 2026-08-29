"""
settings.py - Store for persistent user-adjustable settings

Persists to settings.json

File format
-----------
settings.json is a JSON dict of user settings, defaults:

{
    "brightness": 30
}

Persistence uses atomic write pattern: write to a temporary file,
then os.replace() over the target, so a crash mid-write
never leaves a corrupt or truncated settings.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional


DEFAULT_SETTINGS_PATH = Path(os.path.dirname(__file__)) / 'settings.json'

DEFAULT_VALUES = {
    "brightness": 30,
    "volume": 30,
    "log in first": True
}

class SettingsStore:
    """
    Persists and orders the settings.

    Responsibilities
    -----------------
      - get_settings()   → return dict of all settings
      - get_setting(key) → return the setting by key
      - set(key, value)  → update the provided setting, and save

    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_SETTINGS_PATH
        self.log = logging.getLogger("SettingsStore")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_settings(self) -> dict[str, bool|int]:
        """Return dict of all settings"""
        loaded = self._load()
        ret = DEFAULT_VALUES.copy()
        ret.update(loaded)
        return ret

    def get(self, key: str) -> bool|int:
        return self.get_settings()[key]

    def set(self, key: str, value) -> None:
        """
        update the provided setting, and save

        """
        settings = self._load()
        settings[key] = value
        self._save(settings)
        self.log.info("Updated setting %s — %s", key, value)

    def _load(self) -> dict[str, bool|int]:
        if not self.db_path.exists():
            return {}
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.log.error("settings.json unreadable/corrupt — treating as empty",
                            exc_info=True)
            return {}
        if not isinstance(data, dict):
            self.log.error("settings.json root is not a dict — treating as empty")
            return {}
        return data

    def _save(self, settings: dict[str, bool|int]) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.db_path.with_suffix(self.db_path.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(settings, f, indent=2)
        tmp_path.replace(self.db_path)
