import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import os
import tempfile

from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs
from cue_parser import Track


# --- check_ffmpeg ---

def test_check_ffmpeg_bundled_exists():
    # Simulate bundled bin/ffmpeg.exe present — should return True without touching PATH
    with patch("converter._LOCAL_FFMPEG", new=Path(__file__)):  # __file__ always exists
        assert check_ffmpeg() is True


def test_check_ffmpeg_system_path_found():
    # No bundled exe, but found on system PATH
    with patch("converter._LOCAL_FFMPEG", new=Path("/nonexistent/ffmpeg.exe")):
        with patch("converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True


def test_check_ffmpeg_not_found():
    # No bundled exe and not on PATH
    with patch("converter._LOCAL_FFMPEG", new=Path("/nonexistent/ffmpeg.exe")):
        with patch("converter.shutil.which", return_value=None):
            assert check_ffmpeg() is False


# --- split_and_convert ---

def test_split_and_convert_calls_ffmpeg_per_track():
    tracks = [
        Track(number=1, title="Intro", start=0.0, end=60.0),
        Track(number=2, title="Main", start=60.0, end=None),
    ]
    progress_calls = []
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("converter.subprocess.run", return_value=mock_result) as mock_run:
        split_and_convert(
            "/music/album.flac",
            tracks,
            lambda cur, total: progress_calls.append((cur, total)),
        )

    assert mock_run.call_count == 2
    assert progress_calls == [(1, 2), (2, 2)]

    # Track 1: has -to
    cmd1 = mock_run.call_args_list[0][0][0]
    assert "-ss" in cmd1
    assert "-to" in cmd1
    assert "01 - Intro.mp3" in cmd1[-1]

    # Track 2: no -to (last track)
    cmd2 = mock_run.call_args_list[1][0][0]
    assert "-ss" in cmd2
    assert "-to" not in cmd2
    assert "02 - Main.mp3" in cmd2[-1]


def test_split_and_convert_raises_on_ffmpeg_failure():
    tracks = [Track(number=1, title="Song", start=0.0, end=None)]
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "some error"

    with patch("converter.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Error on track 1"):
            split_and_convert("/music/album.flac", tracks, lambda c, t: None)


# --- convert_files ---

def test_convert_files_calls_ffmpeg_per_file():
    progress_calls = []
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("converter.subprocess.run", return_value=mock_result) as mock_run:
        convert_files(
            ["/music/track01.flac", "/music/track02.flac"],
            lambda cur, total: progress_calls.append((cur, total)),
        )

    assert mock_run.call_count == 2
    assert progress_calls == [(1, 2), (2, 2)]

    cmd1 = mock_run.call_args_list[0][0][0]
    assert cmd1[-1].endswith("track01.mp3")

    cmd2 = mock_run.call_args_list[1][0][0]
    assert cmd2[-1].endswith("track02.mp3")


def test_convert_files_raises_on_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "bad codec"

    with patch("converter.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Error on file 1"):
            convert_files(["/music/track01.flac"], lambda c, t: None)


# --- delete_flacs ---

def test_delete_flacs_success():
    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
        path = f.name
    try:
        warning = delete_flacs([path])
        assert warning is None
        assert not Path(path).exists()
    finally:
        if Path(path).exists():
            os.unlink(path)


def test_delete_flacs_missing_file_returns_warning():
    warning = delete_flacs(["/nonexistent/file.flac"])
    assert warning is not None
    assert "file.flac" in warning
