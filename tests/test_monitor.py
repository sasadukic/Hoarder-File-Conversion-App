import time
import threading
from pathlib import Path
import pytest
from monitor import FolderMonitor


def wait_for(condition_fn, timeout=5.0, interval=0.05):
    """Poll until condition_fn() is True or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition_fn():
            return True
        time.sleep(interval)
    return False


def test_detects_new_flac(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) == 1), "callback not fired"
        assert received[0] == [str(flac)]
    finally:
        m.stop()


def test_pairs_cue_with_flac(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        cue = tmp_path / "album.cue"
        cue.write_text("TITLE \"Album\"")
        flac = tmp_path / "album.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) == 1), "callback not fired"
        assert str(flac) in received[0]
        assert str(cue) in received[0]


    finally:
        m.stop()


def test_ignores_non_flac_files(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        (tmp_path / "notes.txt").write_text("hello")
        time.sleep(0.8)
        assert len(received) == 0
    finally:
        m.stop()


def test_no_duplicate_trigger(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) >= 1)
        time.sleep(0.8)
        assert len(received) == 1, "duplicate callback fired"
    finally:
        m.stop()


def test_detects_flac_in_subfolder(tmp_path):
    received = []
    sub = tmp_path / "sub"
    sub.mkdir()
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        flac = sub / "deep.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) == 1), "subfolder callback not fired"
        assert received[0] == [str(flac)]
    finally:
        m.stop()


def test_stop_is_idempotent(tmp_path):
    m = FolderMonitor(str(tmp_path), lambda paths: None)
    m.start()
    m.stop()
    m.stop()  # should not raise
