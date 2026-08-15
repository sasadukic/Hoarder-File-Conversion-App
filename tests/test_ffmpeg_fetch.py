import io
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import ffmpeg_fetch


# --- cache_dir / cached_ffmpeg / cached_ffprobe / is_cached ---

def test_cache_dir_uses_localappdata(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/someone/AppData/Local")
    assert ffmpeg_fetch.cache_dir() == Path("C:/Users/someone/AppData/Local/Hoarder/bin")


def test_cache_dir_falls_back_to_home_without_localappdata(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with patch("ffmpeg_fetch.Path.home", return_value=Path("/home/someone")):
        assert ffmpeg_fetch.cache_dir() == Path("/home/someone/Hoarder/bin")


def test_cached_paths_are_inside_cache_dir(tmp_path):
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        assert ffmpeg_fetch.cached_ffmpeg() == tmp_path / "ffmpeg.exe"
        assert ffmpeg_fetch.cached_ffprobe() == tmp_path / "ffprobe.exe"


def test_is_cached_false_when_missing(tmp_path):
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        assert ffmpeg_fetch.is_cached() is False


def test_is_cached_false_when_only_one_present(tmp_path):
    (tmp_path / "ffmpeg.exe").write_bytes(b"fake")
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        assert ffmpeg_fetch.is_cached() is False


def test_is_cached_true_when_both_present(tmp_path):
    (tmp_path / "ffmpeg.exe").write_bytes(b"fake")
    (tmp_path / "ffprobe.exe").write_bytes(b"fake")
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        assert ffmpeg_fetch.is_cached() is True


# --- download ---

def _fake_zip_bytes(ffmpeg_content=b"fake ffmpeg", ffprobe_content=b"fake ffprobe") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", ffmpeg_content)
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffprobe.exe", ffprobe_content)
        zf.writestr("ffmpeg-7.1-essentials_build/README.txt", b"hi")
    return buf.getvalue()


class _FakeResponse:
    """Minimal stand-in for the object urlopen()'s context manager yields."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_extracts_ffmpeg_and_ffprobe_into_cache_dir(tmp_path):
    zip_bytes = _fake_zip_bytes(b"real ffmpeg bytes", b"real ffprobe bytes")
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        with patch("ffmpeg_fetch.urllib.request.urlopen", return_value=_FakeResponse(zip_bytes)):
            ffmpeg_fetch.download()

    assert (tmp_path / "ffmpeg.exe").read_bytes() == b"real ffmpeg bytes"
    assert (tmp_path / "ffprobe.exe").read_bytes() == b"real ffprobe bytes"
    # no leftover .tmp files from the atomic-extract step
    assert list(tmp_path.glob("*.tmp")) == []


def test_download_reports_progress(tmp_path):
    zip_bytes = _fake_zip_bytes(b"x" * 500_000, b"y" * 10)
    progress: list = []
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        with patch("ffmpeg_fetch.urllib.request.urlopen", return_value=_FakeResponse(zip_bytes)):
            ffmpeg_fetch.download(on_progress=progress.append)

    assert progress, "expected at least one progress callback"
    assert progress[-1] == pytest.approx(1.0, abs=0.01)
    assert progress == sorted(progress)


def test_download_raises_on_missing_binaries_in_archive(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("some_other_build/bin/ffplay.exe", b"not what we want")
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        with patch("ffmpeg_fetch.urllib.request.urlopen", return_value=_FakeResponse(buf.getvalue())):
            with pytest.raises(RuntimeError):
                ffmpeg_fetch.download()
    # nothing should have been written on failure
    assert not (tmp_path / "ffmpeg.exe").exists()


def test_download_propagates_network_errors(tmp_path):
    with patch("ffmpeg_fetch.cache_dir", return_value=tmp_path):
        with patch("ffmpeg_fetch.urllib.request.urlopen", side_effect=OSError("network down")):
            with pytest.raises(OSError):
                ffmpeg_fetch.download()
