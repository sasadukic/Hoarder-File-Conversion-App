import json
import sys
from pathlib import Path
from typing import Any, Dict


def _settings_path() -> Path:
    # When running as a PyInstaller bundle, save settings next to the exe so
    # they persist across runs and travel with the portable folder.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "settings.json"
    return Path(__file__).parent / "settings.json"


_SETTINGS_PATH = _settings_path()

_DEFAULTS: Dict[str, Any] = {
    "delete_flac": False,
    "auto_convert": False,
    "minimize_to_tray": False,
    "start_on_startup": False,
    "sounds_enabled": True,
    "monitor_enabled": False,
    "monitor_folder": None,
    "torrent_enabled": False,
    "torrent_delete_source": False,
    "move_music_enabled": False,
    "move_music_folder": None,
    "move_video_enabled": False,
    "move_video_folder": None,
    "proxy_enabled": False,
    "proxy_host": None,
    "proxy_port": None,
    "proxy_username": None,
    "proxy_password": None,
}


def load() -> Dict[str, Any]:
    """Load settings from disk. Returns defaults on missing or corrupt file."""
    try:
        raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULTS, **{k: raw[k] for k in _DEFAULTS if k in raw}}
    except Exception:
        return dict(_DEFAULTS)


def save(data: Dict[str, Any]) -> None:
    """Atomically write settings to disk."""
    tmp = _SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_PATH)
