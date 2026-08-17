import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import time

import torrent_downloader
from torrent_downloader import (
    _try_import_libtorrent,
    _find_aria2c,
    _torrent_info_name,
    TorrentDownloader,
    _LOCAL_ARIA2C,
    _NO_WINDOW,
    check_proxy_reachable,
    clamp_max_active,
    DEFAULT_MAX_ACTIVE,
    PROGRESS_QUEUED,
    CONTROL_SAVE_INTERVAL,
    control_file_for,
    has_incomplete_download,
    sweep_stale_staged_torrents,
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
            # aria2c is handed a staged copy, not the original (see below)
            assert cmd[-1].endswith("test.torrent")
            assert cmd[-1] != str(torrent_file)
            assert "--seed-time=0" in cmd
            assert mock_popen.call_args[1].get("creationflags") == _NO_WINDOW

            td.stop()


# --- SOCKS5 proxy (aria2c) ---

def test_aria2c_no_proxy_flags_by_default(tmp_path):
    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("fake torrent data")
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
            td.start()
            td.add(str(torrent_file))
            cmd = mock_popen.call_args[0][0]
            assert not any(c.startswith("--all-proxy") for c in cmd)
            td.stop()


def test_aria2c_proxy_flags_with_credentials(tmp_path):
    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("fake torrent data")
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    proxy = {"host": "1.2.3.4", "port": 1080, "username": "u", "password": "p"}

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: None, lambda t, p: None, proxy=proxy,
            )
            td.start()
            td.add(str(torrent_file))
            cmd = mock_popen.call_args[0][0]
            assert "--all-proxy=socks5h://1.2.3.4:1080" in cmd
            assert "--all-proxy-user=u" in cmd
            assert "--all-proxy-passwd=p" in cmd
            assert cmd[-1].endswith("test.torrent")  # staged path stays last
            td.stop()


def test_aria2c_proxy_omits_credential_flags_when_none(tmp_path):
    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("fake torrent data")
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    proxy = {"host": "1.2.3.4", "port": 1080, "username": None, "password": None}

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: None, lambda t, p: None, proxy=proxy,
            )
            td.start()
            td.add(str(torrent_file))
            cmd = mock_popen.call_args[0][0]
            assert "--all-proxy=socks5h://1.2.3.4:1080" in cmd
            assert not any(c.startswith("--all-proxy-user") for c in cmd)
            assert not any(c.startswith("--all-proxy-passwd") for c in cmd)
            td.stop()


# --- check_proxy_reachable ---

def test_check_proxy_reachable_true_when_listening():
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert check_proxy_reachable("127.0.0.1", port, timeout=1.0) is True
    finally:
        srv.close()


def test_check_proxy_reachable_false_when_closed():
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # port now closed
    assert check_proxy_reachable("127.0.0.1", port, timeout=0.5) is False


def test_torrent_file_is_staged_so_deleting_the_original_is_safe(tmp_path):
    """'Delete torrent file after adding' must not race aria2c's read of it.

    Popen returns before aria2c has opened the torrent, so the downloader
    copies it aside and points aria2c at the copy.
    """
    torrent_file = tmp_path / "movie.torrent"
    torrent_file.write_bytes(b"d8:announce...e")

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            # The monitor thread's own cleanup is exercised separately below;
            # stub it out here so it can't race this test's assertions.
            with patch.object(TorrentDownloader, "_spawn_aria2c_monitor"):
                td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
                td.start()
                td.add(str(torrent_file))

                staged = Path(torrent_downloader.subprocess.Popen.call_args[0][0][-1])
                assert staged.read_bytes() == b"d8:announce...e"

                # The user's copy can now go without touching the download.
                torrent_file.unlink()
                assert staged.exists()

                td.stop()


def test_magnet_uri_is_not_staged(tmp_path):
    """There is no file to protect — the URI goes to aria2c untouched."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
            td.start()
            td.add("magnet:?xt=urn:btih:abc&dn=Thing")
            assert mock_popen.call_args[0][0][-1] == "magnet:?xt=urn:btih:abc&dn=Thing"
            td.stop()


def test_staged_copy_is_cleaned_up_when_the_download_ends(tmp_path):
    import threading

    torrent_file = tmp_path / "movie.torrent"
    torrent_file.write_bytes(b"data")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = iter([])
    mock_proc.wait.return_value = 0

    done = threading.Event()

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: None,
                lambda t, p: done.set(),  # on_complete fires after cleanup
            )
            td.start()
            td.add(str(torrent_file))
            staged = Path(mock_popen.call_args[0][0][-1])
            assert done.wait(timeout=5), "monitor thread never completed"
            assert not staged.parent.exists()
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


# --- SOCKS5 proxy (libtorrent) ---

def test_libtorrent_no_proxy_settings_by_default(tmp_path):
    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_lt.session.return_value = mock_session

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
        td.start()
        applied = mock_session.apply_settings.call_args[0][0]
        assert "proxy_hostname" not in applied
        td.stop()


def test_libtorrent_proxy_settings_applied(tmp_path):
    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_lt.session.return_value = mock_session
    mock_lt.settings_pack.proxy_type_t.socks5 = 2
    mock_lt.settings_pack.proxy_type_t.socks5_pw = 3
    proxy = {"host": "1.2.3.4", "port": 1080, "username": "u", "password": "p"}

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(
            str(tmp_path), lambda t, n, p: None, lambda t, p: None, proxy=proxy,
        )
        td.start()
        applied = mock_session.apply_settings.call_args[0][0]
        assert applied["proxy_hostname"] == "1.2.3.4"
        assert applied["proxy_port"] == 1080
        assert applied["proxy_username"] == "u"
        assert applied["proxy_password"] == "p"
        assert applied["proxy_type"] == 3  # socks5_pw, since credentials given
        assert applied["proxy_peer_connections"] is True
        assert applied["proxy_hostnames"] is True
        td.stop()


def test_libtorrent_proxy_type_without_credentials(tmp_path):
    mock_lt = MagicMock()
    mock_session = MagicMock()
    mock_lt.session.return_value = mock_session
    mock_lt.settings_pack.proxy_type_t.socks5 = 2
    mock_lt.settings_pack.proxy_type_t.socks5_pw = 3
    proxy = {"host": "1.2.3.4", "port": 1080, "username": None, "password": None}

    with patch("torrent_downloader._try_import_libtorrent", return_value=mock_lt):
        td = TorrentDownloader(
            str(tmp_path), lambda t, n, p: None, lambda t, p: None, proxy=proxy,
        )
        td.start()
        applied = mock_session.apply_settings.call_args[0][0]
        assert applied["proxy_type"] == 2  # plain socks5, no credentials
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
    and the completion path is built from the torrent's own name under the
    download directory (see test_aria2c_completion_path_uses_torrent_name for
    why it's not scraped from aria2c's stdout)."""
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=MyFile", encoding="utf-8")

    progress_calls = []
    complete_calls = []

    stdout_lines = [
        b"[#2089b0 400KiB/33MiB(1%) CN:1 DL:115KiB ETA:4m51s]\n",
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
            assert complete_calls[0] == (tid, str(Path(tmp_path) / "MyFile"))

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


def test_aria2c_completion_path_uses_torrent_name(tmp_path):
    """A multi-file torrent's completion path is built from the torrent's own
    name, not scraped from aria2c's stdout.

    aria2c's "FILE:" summary line only ever names the first file plus a
    "(N more)" count for a multi-file torrent — e.g.
    "FILE: ./Album/01.flac (1more)" — never a full per-file listing, despite
    looking like it repeats one line per file. Confirmed against the real
    bundled aria2c.exe: relying on it to reconstruct a multi-file download's
    path silently produced a bogus, nonexistent path and the completed
    download was never picked up. The torrent's own name (from
    _torrent_info_name for a .torrent file, or dn= for a magnet) is the only
    reliable source for this.
    """
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Album", encoding="utf-8")

    complete_calls = []

    stdout_lines = [
        b"[#2089b0 1MiB/33MiB(3%) CN:1 DL:115KiB ETA:4m51s]\n",
        b"FILE: ./Album/01.flac (1more)\n",
        b"[#2089b0 33MiB/33MiB(100%) CN:1 DL:1MiB]\n",
        b"FILE: ./Album/01.flac (1more)\n",
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: None,
                lambda t, p: complete_calls.append((t, p)),
            )
            td.start()
            tid = td.add(str(magnet_file))
            time.sleep(0.3)

            assert len(complete_calls) == 1
            assert complete_calls[0][0] == tid
            assert complete_calls[0][1] == str(Path(tmp_path) / "Album")
            td.stop()


def test_aria2c_progress_ignores_non_summary_lines(tmp_path):
    """Only the aggregate '[#gid ...]' line drives progress — per-file and
    incidental percentages must not move the bar."""
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Album", encoding="utf-8")

    progress_calls = []

    stdout_lines = [
        b"[#2089b0 1MiB/33MiB(3%) CN:1 DL:115KiB ETA:4m51s]\n",
        b"FILE: ./Album/01.flac (99%) (1more)\n",
        b"Exception: seeding finished (100%)\n",
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: progress_calls.append(p),
                lambda t, p: None,
            )
            td.start()
            td.add(str(magnet_file))
            time.sleep(0.3)

            # 0.0 on spawn, 0.03 from the summary line, 1.0 on completion.
            assert progress_calls == [0.0, 0.03, 1.0]
            td.stop()


# --- _torrent_info_name ---

def _write_minimal_torrent(path: Path, name: str) -> None:
    """A minimal but valid bencode dict with just an info.name field."""
    encoded_name = name.encode("utf-8")
    body = f"d4:infod4:name{len(encoded_name)}:".encode("utf-8") + encoded_name + b"6:lengthi1eeee"
    path.write_bytes(body)


def test_torrent_info_name_decodes_the_real_name(tmp_path):
    torrent = tmp_path / "totally unrelated release label.torrent"
    _write_minimal_torrent(torrent, "Actual Album Name")
    assert _torrent_info_name(str(torrent)) == "Actual Album Name"


def test_torrent_info_name_handles_non_ascii(tmp_path):
    torrent = tmp_path / "release.torrent"
    _write_minimal_torrent(torrent, "Jóga")
    assert _torrent_info_name(str(torrent)) == "Jóga"


def test_torrent_info_name_none_for_malformed_file(tmp_path):
    torrent = tmp_path / "bad.torrent"
    torrent.write_text("not bencode data")
    assert _torrent_info_name(str(torrent)) is None


def test_torrent_info_name_none_for_missing_file(tmp_path):
    assert _torrent_info_name(str(tmp_path / "gone.torrent")) is None


# --- concurrency limit ---

def test_clamp_max_active_bounds_and_defaults():
    assert clamp_max_active(1) == 1
    assert clamp_max_active(20) == 20
    assert clamp_max_active(0) == 1        # below the floor
    assert clamp_max_active(999) == 20     # above the ceiling
    assert clamp_max_active(None) == DEFAULT_MAX_ACTIVE
    assert clamp_max_active("nonsense") == DEFAULT_MAX_ACTIVE
    assert clamp_max_active("7") == 7      # settings.json can hold a string


class _Concurrency:
    """aria2c downloads that never finish on their own, so the only thing
    that frees a slot is the test asking for one."""

    def __init__(self, tmp_path, max_active):
        self.progress = []
        self.popen = patch(
            "torrent_downloader.subprocess.Popen", return_value=MagicMock(),
        )
        self.find = patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c")
        self.monitor = patch.object(TorrentDownloader, "_spawn_aria2c_monitor")
        self.tmp_path = tmp_path
        self.max_active = max_active

    def __enter__(self):
        self.find.start()
        self.mock_popen = self.popen.start()
        self.monitor.start()
        self.td = TorrentDownloader(
            str(self.tmp_path),
            lambda t, n, p: self.progress.append((t, n, p)),
            lambda t, p: None,
            max_active=self.max_active,
        )
        self.td.start()
        return self

    def __exit__(self, *exc):
        self.td.stop()
        self.monitor.stop()
        self.popen.stop()
        self.find.stop()

    def add(self, i):
        return self.td.add(f"magnet:?xt=urn:btih:{i}&dn=T{i}")

    @property
    def started(self):
        return self.mock_popen.call_count

    @property
    def queued(self):
        return [t for t, _n, p in self.progress if p == PROGRESS_QUEUED]


def test_only_max_active_torrents_start_at_once(tmp_path):
    with _Concurrency(tmp_path, max_active=2) as c:
        tids = [c.add(i) for i in range(5)]
        assert all(t is not None for t in tids)   # all accepted…
        assert c.started == 2                     # …but only two transferring
        assert c.queued == tids[2:]


def test_finishing_one_starts_the_next_in_line(tmp_path):
    with _Concurrency(tmp_path, max_active=2) as c:
        tids = [c.add(i) for i in range(4)]
        assert c.started == 2
        c.td.remove(tids[0])
        assert c.started == 3
        c.td.remove(tids[1])
        assert c.started == 4


def test_raising_the_limit_starts_waiting_torrents(tmp_path):
    with _Concurrency(tmp_path, max_active=1) as c:
        for i in range(4):
            c.add(i)
        assert c.started == 1
        c.td.set_max_active(4)
        assert c.started == 4


def test_lowering_the_limit_leaves_running_transfers_alone(tmp_path):
    """Killing a download to satisfy a smaller limit would throw away work —
    the new limit applies to what starts next."""
    with _Concurrency(tmp_path, max_active=4) as c:
        for i in range(4):
            c.add(i)
        assert c.started == 4
        c.td.set_max_active(1)
        assert c.started == 4
        assert len(c.td._aria2c_procs) == 4


def test_a_waiting_torrent_can_be_removed_before_it_starts(tmp_path):
    with _Concurrency(tmp_path, max_active=1) as c:
        first, second, third = (c.add(i) for i in range(3))
        c.td.remove(third)          # still waiting: nothing to terminate
        c.td.remove(first)          # frees the only slot
        assert c.started == 2       # second promoted, third gone for good


def test_snapshot_covers_running_and_waiting_torrents(tmp_path):
    with _Concurrency(tmp_path, max_active=1) as c:
        running = c.add(0)
        waiting = c.add(1)
        snap = c.td.snapshot()
        by_tid = {s["tid"]: s for s in snap}
        assert set(by_tid) == {running, waiting}
        assert by_tid[running]["target"] == "magnet:?xt=urn:btih:0&dn=T0"
        assert by_tid[waiting]["target"] == "magnet:?xt=urn:btih:1&dn=T1"
        assert by_tid[waiting]["name"] == "T1"


def test_snapshot_points_at_the_staged_copy_for_torrent_files(tmp_path):
    """The user's own .torrent may be deleted right after adding, so the
    resume target has to be the copy the downloader made."""
    torrent_file = tmp_path / "movie.torrent"
    torrent_file.write_bytes(b"d4:infod4:name5:Movieee")

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=MagicMock()):
            with patch.object(TorrentDownloader, "_spawn_aria2c_monitor"):
                td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
                td.start()
                tid = td.add(str(torrent_file))
                target = td.snapshot()[0]["target"]
                assert target != str(torrent_file)
                assert Path(target).name == "movie.torrent"
                torrent_file.unlink()
                assert Path(target).is_file()   # the resume source survives
                td.stop()


def test_snapshot_is_empty_once_nothing_is_left(tmp_path):
    with _Concurrency(tmp_path, max_active=2) as c:
        tid = c.add(0)
        c.td.remove(tid)
        assert c.td.snapshot() == []


def test_aria2c_is_told_to_continue_an_interrupted_transfer(tmp_path):
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
            assert "--continue=true" in mock_popen.call_args[0][0]
            td.stop()


def test_aria2c_saves_its_control_file_often(tmp_path):
    """Closing Plunder kills aria2c outright, so a resume only gets what the
    last save wrote. aria2c's own 60s default would throw away a minute of
    transfer — and leave a just-started torrent with no control file at all."""
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
            cmd = mock_popen.call_args[0][0]
            assert f"--auto-save-interval={CONTROL_SAVE_INTERVAL}" in cmd
            assert CONTROL_SAVE_INTERVAL < 60
            td.stop()


def test_a_resume_asks_aria2c_to_hash_check_what_is_already_there(tmp_path):
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Test", encoding="utf-8")
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc) as mock_popen:
            td = TorrentDownloader(str(tmp_path), lambda t, n, p: None, lambda t, p: None)
            td.start()
            td.add(str(magnet_file), resume=True)
            assert "--check-integrity=true" in mock_popen.call_args[0][0]
            td.stop()


def test_a_fresh_add_does_not_pay_for_a_hash_check(tmp_path):
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
            assert "--check-integrity=true" not in mock_popen.call_args[0][0]
            td.stop()


def test_a_queued_torrent_keeps_its_resume_flag_until_it_starts(tmp_path):
    """A resume that waits its turn behind the concurrency limit must still be
    a resume when a slot finally frees up."""
    magnet_file = tmp_path / "test.magnet"
    magnet_file.write_text("magnet:?xt=urn:btih:123&dn=Test", encoding="utf-8")
    spawned = []

    def _make_proc(cmd, *a, **k):
        p = MagicMock()
        p.stdout = iter([])
        p.wait.return_value = 0
        spawned.append(cmd)
        return p

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", side_effect=_make_proc):
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: None, lambda t, p: None,
                max_active=1,
            )
            td.start()
            td._starting.add("hold")       # occupy the only slot
            td.add(str(magnet_file), resume=True)
            assert spawned == []           # parked, not started
            td._starting.discard("hold")
            td._pump()
            assert len(spawned) == 1
            assert "--check-integrity=true" in spawned[0]
            td.stop()


# --- aria2 control files ---

def test_control_file_sits_beside_a_single_file_download(tmp_path):
    assert control_file_for(tmp_path / "movie.mkv") == tmp_path / "movie.mkv.aria2"


def test_control_file_sits_beside_a_multi_file_folder_not_inside_it(tmp_path):
    """The whole bug: aria2c names the control file after the top-level path,
    so a multi-file torrent's marker is a sibling of its folder."""
    assert control_file_for(tmp_path / "Album") == tmp_path / "Album.aria2"


def test_a_folder_with_a_sibling_control_file_is_unfinished(tmp_path):
    album = tmp_path / "Album"
    (album / "disc1").mkdir(parents=True)
    (album / "disc1" / "01.flac").write_bytes(b"part of a track")
    (tmp_path / "Album.aria2").write_bytes(b"control")
    assert has_incomplete_download(album) is True


def test_a_folder_with_a_control_file_inside_is_also_unfinished(tmp_path):
    """Web-seed fallbacks leave per-file markers within the tree."""
    album = tmp_path / "Album"
    album.mkdir()
    (album / "01.flac.aria2").write_bytes(b"control")
    assert has_incomplete_download(album) is True


def test_a_folder_with_no_control_file_anywhere_is_finished(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    (album / "01.flac").write_bytes(b"a whole track")
    assert has_incomplete_download(album) is False


def test_a_file_with_its_control_file_is_unfinished(tmp_path):
    movie = tmp_path / "movie.mkv"
    movie.write_bytes(b"half")
    (tmp_path / "movie.mkv.aria2").write_bytes(b"control")
    assert has_incomplete_download(movie) is True


def test_a_file_with_no_control_file_is_finished(tmp_path):
    movie = tmp_path / "movie.mkv"
    movie.write_bytes(b"all of it")
    assert has_incomplete_download(movie) is False


# --- staged .torrent sweep ---

def test_sweep_removes_staged_copies_nothing_refers_to(tmp_path):
    kept = tmp_path / "hoarder_torrent_keep"
    dropped = tmp_path / "hoarder_torrent_drop"
    kept.mkdir()
    dropped.mkdir()
    (kept / "a.torrent").write_bytes(b"d")
    (dropped / "b.torrent").write_bytes(b"d")

    with patch("torrent_downloader.tempfile.gettempdir", return_value=str(tmp_path)):
        removed = sweep_stale_staged_torrents([str(kept / "a.torrent")])

    assert removed == 1
    assert kept.exists()
    assert not dropped.exists()


def test_sweep_leaves_unrelated_temp_directories_alone(tmp_path):
    other = tmp_path / "something_else"
    other.mkdir()
    with patch("torrent_downloader.tempfile.gettempdir", return_value=str(tmp_path)):
        assert sweep_stale_staged_torrents([]) == 0
    assert other.exists()


def test_sweep_ignores_magnet_targets(tmp_path):
    """A magnet has no staged copy to keep, so it must not accidentally
    protect some unrelated directory."""
    stale = tmp_path / "hoarder_torrent_old"
    stale.mkdir()
    with patch("torrent_downloader.tempfile.gettempdir", return_value=str(tmp_path)):
        assert sweep_stale_staged_torrents(["magnet:?xt=urn:btih:1"]) == 1
    assert not stale.exists()


def test_add_torrent_file_uses_info_name_not_filename(tmp_path):
    """The completion path must come from the torrent's own name, not the
    .torrent metadata file's (often unrelated, much longer) filename."""
    torrent_file = tmp_path / "(Group) [CD] Totally Unrelated Release Label [tracker-123].torrent"
    _write_minimal_torrent(torrent_file, "Real Album Name")

    complete_calls = []
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.wait.return_value = 0

    with patch("torrent_downloader._find_aria2c", return_value="/fake/aria2c"):
        with patch("torrent_downloader.subprocess.Popen", return_value=mock_proc):
            td = TorrentDownloader(
                str(tmp_path), lambda t, n, p: None,
                lambda t, p: complete_calls.append((t, p)),
            )
            td.start()
            td.add(str(torrent_file))
            time.sleep(0.3)

            assert len(complete_calls) == 1
            assert complete_calls[0][1] == str(Path(tmp_path) / "Real Album Name")
            td.stop()
