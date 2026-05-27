import json
import pytest
from pathlib import Path
import settings as smod


DEFAULTS = {
    "delete_flac": False,
    "auto_convert": False,
    "minimize_to_tray": False,
    "start_on_startup": False,
    "monitor_enabled": False,
    "monitor_folder": None,
    "torrent_enabled": False,
    "torrent_download_folder": None,
    "torrent_finished_folder": None,
    "torrent_delete_source": False,
}


def test_load_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(smod, "_SETTINGS_PATH", tmp_path / "settings.json")
    result = smod.load()
    assert result == DEFAULTS


def test_load_corrupt_file_returns_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("not json")
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    result = smod.load()
    assert result == DEFAULTS


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    data = {**DEFAULTS, "delete_flac": True, "monitor_folder": "/music"}
    smod.save(data)
    assert p.exists()
    result = smod.load()
    assert result["delete_flac"] is True
    assert result["monitor_folder"] == "/music"


def test_load_partial_file_fills_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"delete_flac": True}))
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    result = smod.load()
    assert result["delete_flac"] is True
    assert result["auto_convert"] is False  # filled from defaults


def test_save_is_atomic(tmp_path, monkeypatch):
    """save() writes to .tmp then renames — file should never be half-written."""
    p = tmp_path / "settings.json"
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    smod.save(DEFAULTS)
    # No .tmp file should remain after save
    assert not (tmp_path / "settings.json.tmp").exists()
    assert p.exists()
