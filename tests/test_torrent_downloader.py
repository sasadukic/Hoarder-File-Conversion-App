import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import time

from torrent_downloader import (
    _try_import_libtorrent,
    _find_aria2c,
    TorrentDownloader,
    _LOCAL_ARIA2C,
    _NO_WINDOW,
)


# --- _try_import_libtorrent ---

def test_try_import_libtorrent_no_crash():
    result = _try_import_libtorrent()
    # In this environment libtorrent is not installed
    assert result is None


# --- _find_aria2c ---

def test_find_aria2c_prefers_bundled():
    with patch("torrent_downloader._LOCAL_ARIA2C", new=Path(__file__)):
        assert _find_aria2c() == str(Path(__file__))


def test_find_aria2c_falls_back_to_path():
    with patch("torrent_downloader._LOCAL_ARIA2C", new=Path("/nonexistent/aria2c.exe")):
        with patch("torrent_downloader.shutil.which", return_value="/usr/bin/aria2c"):
            assert _find_aria2c() == "/usr/bin/aria2c"


def test_find_aria2c_not_found():
    with patch("torrent_downloader._LOCAL_ARIA2C", new=Path("/nonexistent/aria2c.exe")):
        with patch("torrent_downloader.shutil.which", return_value=None):
            assert _find_aria2c() is None


# --- TorrentDownloader construction ---

def test_construction():
    td = TorrentDownloader("/downloads", lambda t, n, p: None, lambda t, p: None)
    assert td.download_dir == str(Path("/downloads"))
    assert td._lt is None  # not installed in this env


# --- add() when not running ---

def test_add_when_not_running(tmp_path):
    td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
    assert td.add(str(tmp_path / "file.magnet")) is None


# --- add() with magnet file (aria2c fallback) ---

def test_add_magnet_file_reads_uri(tmp_path):
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Test", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
            td.start()
            tid = td.add(str(magnet_file))
            assert tid is not None

            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "magnet:?xt=urn:btih:123&dn=Test" in cmd
            assert "--seed-time=0" in cmd
            assert "-d" in cmd
            assert str(tmp_path) in cmd
            assert mock_popen.call_args[1].get("creationflags") == _NO_WINDOW

            td.stop()


def test_add_invalid_magnet_file(tmp_path):
    bad_magnet = tmp_path / "bad.magnet"
    bad_magnet.write_text("not a magnet uri", encoding="utf-8")

    td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
    td.start()
    assert td.add(str(bad_magnet)) is None
    td.stop()


# --- add() with .torrent file (aria2c fallback) ---

def test_add_torrent_file_aria2c(tmp_path):
    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("fake torrent data")

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
            td.start()
            tid = td.add(str(torrent_file))
            assert tid is not None

            cmd = mock_popen.call_args[0][0]
            assert str(torrent_file) in cmd
            assert "--seed-time=0" in cmd
            assert mock_popen.call_args[1].get("creationflags") == _NO_WINDOW

            td.stop()


# --- aria2c callback structure ---

def test_aria2c_callbacks_on_exit(tmp_path):
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=MyFile", encoding="utf-8")

    progress_calls = []
    complete_calls = []

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            td = TorrentDownloader(
                str(tmp_path),
                lambda t, n, p: progress_calls.append((t, n, p)),
                lambda t, p: complete_calls.append((t, p)),
            )
            td.start()
            tid = td.add(str(magnet_file))
            assert tid is not None

            # Give monitor thread time to fire
            time.sleep(0.2)

            assert len(complete_calls) == 1
            assert complete_calls[0][0] == tid
            assert "MyFile" in complete_calls[0][1]

            # on_progress should be called with 0.0 (start) and 1.0 (complete)
            assert any(p[2] == 0.0 for p in progress_calls)
            assert any(p[2] == 1.0 for p in progress_calls)

            td.stop()


# --- libtorrent path (mocked) ---

def test_libtorrent_add_torrent_file(tmp_path):
    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_handle = MagicMock()
    mock_handle.is_valid.return_value = True
    mock_status = MagicMock()
    mock_status.progress = 0.5
    mock_status.name = "test"
    mock_status.is_seeding = False
    mock_status.is_finished = False
    mock_handle.status.return_value = mock_status

    mock_lt.session.return_value = mock_session
    mock_session.add_torrent.return_value = mock_handle
    mock_lt.torrent_info.return_value = MagicMock()
    mock_lt.add_torrent_params.return_value = MagicMock()
    mock_lt.storage_mode_t.storage_mode_sparse = 0
    mock_lt.parse_magnet_uri.return_value = MagicMock()

    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("fake torrent data")

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
        td.start()
        tid = td.add(str(torrent_file))
        assert tid is not None
        mock_lt.torrent_info.assert_called_once_with(str(torrent_file))
        td.stop()


def test_libtorrent_add_magnet_uri(tmp_path):
    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_handle = MagicMock()
    mock_handle.is_valid.return_value = True
    mock_status = MagicMock()
    mock_status.progress = 0.0
    mock_status.name = "magnet_name"
    mock_status.is_seeding = False
    mock_status.is_finished = False
    mock_handle.status.return_value = mock_status

    mock_lt.session.return_value = mock_session
    mock_session.add_torrent.return_value = mock_handle
    mock_lt.parse_magnet_uri.return_value = MagicMock()
    mock_lt.storage_mode_t.storage_mode_sparse = 0

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
        td.start()
        tid = td.add("magnet:?xt=urn:btih:123&dn=magnet_name")
        assert tid is not None
        mock_lt.parse_magnet_uri.assert_called_once_with("magnet:?xt=urn:btih:123&dn=magnet_name")
        td.stop()


def test_libtorrent_progress_and_complete_callbacks(tmp_path):
    progress_calls = []
    complete_calls = []

    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_handle = MagicMock()
    mock_handle.is_valid.return_value = True
    mock_status = MagicMock()
    mock_status.progress = 1.0
    mock_status.name = "done"
    mock_status.is_seeding = True
    mock_status.is_finished = True
    mock_handle.status.return_value = mock_status

    mock_lt.session.return_value = mock_session
    mock_session.add_torrent.return_value = mock_handle
    mock_lt.parse_magnet_uri.return_value = MagicMock()
    mock_lt.storage_mode_t.storage_mode_sparse = 0

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(
            str(tmp_path),
            lambda t, n, p: progress_calls.append((t, n, p)),
            lambda t, p: complete_calls.append((t, p)),
        )
        td.start()
        tid = td.add("magnet:?xt=urn:btih:123&dn=done")
        assert tid is not None

        td._poll_once()

        assert len(progress_calls) >= 1
        assert progress_calls[-1] == (tid, "done", 1.0)
        assert len(complete_calls) == 1
        assert complete_calls[0][0] == tid
        assert "done" in complete_calls[0][1]
        td.stop()


def test_remove_libtorrent(tmp_path):
    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_handle = MagicMock()
    mock_handle.is_valid.return_value = True
    mock_status = MagicMock()
    mock_status.progress = 0.5
    mock_status.name = "test"
    mock_status.is_seeding = False
    mock_status.is_finished = False
    mock_handle.status.return_value = mock_status

    mock_lt.session.return_value = mock_session
    mock_session.add_torrent.return_value = mock_handle
    mock_lt.torrent_info.return_value = MagicMock()
    mock_lt.add_torrent_params.return_value = MagicMock()
    mock_lt.storage_mode_t.storage_mode_sparse = 0

    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("fake torrent data")

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
        td.start()
        tid = td.add(str(torrent_file))
        assert tid is not None
        assert tid in td._handles

        td.remove(tid)
        assert tid not in td._handles
        mock_session.remove_torrent.assert_called_once_with(mock_handle)
        td.stop()


# --- get_progress / remove ---

def test_get_progress(tmp_path):
    td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
    assert td.get_progress("nonexistent") == 0.0
    td._progress["abc"] = 0.75
    assert td.get_progress("abc") == 0.75


def test_remove_aria2c(tmp_path):
    mock_proc = MagicMock()

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            # Prevent the aria2c monitor thread from running so the proc stays in _aria2c_procs
            with patch("torrent_downloader.threading.Thread") as mock_thread:
                td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
                td.start()

                magnet_file = tmp_path / "test.magnet"
                magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Test", encoding="utf-8")
                tid = td.add(str(magnet_file))
                assert tid is not None
                assert tid in td._aria2c_procs

                td.remove(tid)
                assert tid not in td._aria2c_procs
                assert tid not in td._progress
                assert td.get_progress(tid) == 0.0
                mock_proc.terminate.assert_called_once()

                td.stop()


# --- start/stop lifecycle ---

def test_start_stop_lifecycle(tmp_path):
    td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
    assert not td._running
    td.start()
    assert td._running
    assert td._poll_thread is not None
    td.stop()
    assert not td._running
    assert td._poll_thread is None


def test_double_start_is_noop(tmp_path):
    td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
    td.start()
    thread1 = td._poll_thread
    td.start()
    assert td._poll_thread is thread1
    td.stop()


# --- aria2c progress parsing ---

def test_aria2c_progress_parsed_from_stdout(tmp_path):
    """Progress summaries on aria2c stdout are parsed into on_progress calls,
    and the FILE: line determines the completion path."""
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=MyFile", encoding="utf-8")

    progress_calls = []
    complete_calls = []

    stdout_lines = [
        b"[#2089b0 400KiB/33MiB(1%) CN:1 DL:115KiB ETA:4m51s]\n",
        b"FILE: /downloads/MyFile.mkv\n",
        b"[#2089b0 16MiB/33MiB(50%) CN:1 DL:1.2MiB ETA:14s]\n",
        b"(OK):download completed.\n",
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            td = TorrentDownloader(
                str(tmp_path),
                lambda t, n, p: progress_calls.append((t, n, p)),
                lambda t, p: complete_calls.append((t, p)),
            )
            td.start()
            tid = td.add(str(magnet_file))
            assert tid is not None
            time.sleep(0.3)

            pcts = [p[2] for p in progress_calls]
            assert 0.01 in pcts
            assert 0.5 in pcts
            assert pcts[-1] == 1.0

            assert len(complete_calls) == 1
            assert complete_calls[0] == (tid, "/downloads/MyFile.mkv")

            td.stop()


def test_aria2c_stdout_merges_stderr(tmp_path):
    """aria2c is spawned with stderr merged into stdout so neither pipe can
    fill up and deadlock the download."""
    import subprocess as sp
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Test", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
            td.start()
            td.add(str(magnet_file))
            assert mock_popen.call_args[1].get("stderr") == sp.STDOUT
            cmd = mock_popen.call_args[0][0]
            assert "--summary-interval=1" in cmd
            td.stop()
