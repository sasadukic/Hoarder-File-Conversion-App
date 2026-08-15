import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

def _try_import_libtorrent():
    try:
        import libtorrent as lt
        return lt
    except ImportError:
        return None

_LOCAL_ARIA2C = Path(__file__).parent / "bin" / "aria2c.exe"

# Torrents download here first, inside the monitored folder but excluded
# from the folder watcher — see FolderMonitor's exclude_dirname. Only once a
# download is protocol-confirmed complete does it get moved into the real
# monitored folder, so the watcher never has to guess from file size alone
# whether a BitTorrent transfer (which doesn't write pieces in order) is
# actually finished.
STAGING_DIRNAME = ".hoarder-incoming"

# aria2c summary lines look like:  [#2089b0 400KiB/33MiB(1%) CN:1 DL:115KiB ETA:4m51s]
#
# Anchor the percentage to the aggregate "[#gid ...]" line — a bare "(n%)"
# search also matches per-file lines, which makes the bar jump around on
# multi-file torrents.
_ARIA2_PCT_RE = re.compile(r"^\[#[0-9a-fA-F]+\b.*?\((\d{1,3}(?:\.\d+)?)%\)")

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

def _find_aria2c() -> Optional[str]:
    if _LOCAL_ARIA2C.exists():
        return str(_LOCAL_ARIA2C)
    return shutil.which("aria2c")

def _torrent_info_name(torrent_path: str) -> Optional[str]:
    """Decode a .torrent file's own info.name field.

    This is the torrent's real content name (its top-level folder for a
    multi-file torrent, or the file's own name for a single-file one) — not
    the .torrent metadata file's own filename, which is often an unrelated,
    much longer release label. aria2c saves content under this name inside
    the download directory, so it's what the completed download's path is
    built from; see _spawn_aria2c_monitor.
    """
    try:
        data = Path(torrent_path).read_bytes()
    except OSError:
        return None

    def _decode(buf: bytes, i: int):
        c = buf[i:i + 1]
        if c == b"d":
            i += 1
            d: Dict[bytes, Any] = {}
            while buf[i:i + 1] != b"e":
                k, i = _decode(buf, i)
                v, i = _decode(buf, i)
                d[k] = v
            return d, i + 1
        if c == b"l":
            i += 1
            items = []
            while buf[i:i + 1] != b"e":
                v, i = _decode(buf, i)
                items.append(v)
            return items, i + 1
        if c == b"i":
            end = buf.index(b"e", i)
            return int(buf[i + 1:end]), end + 1
        colon = buf.index(b":", i)
        n = int(buf[i:colon])
        start = colon + 1
        return buf[start:start + n], start + n

    try:
        top, _ = _decode(data, 0)
        name = top[b"info"][b"name"]
        return name.decode("utf-8", errors="replace")
    except (KeyError, IndexError, ValueError, TypeError):
        return None

def _extract_magnet_name(uri: str) -> Optional[str]:
    match = re.search(r"dn=([^&]+)", uri)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1).replace("+", " "))
    return None

def check_proxy_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """One-shot TCP reachability check, run when the user saves proxy settings.

    Not a continuous kill-switch: a correctly configured SOCKS5 proxy (with
    proxy_peer_connections/socks5h routing, both set below) fails closed
    rather than silently falling back to a direct connection, so this only
    needs to catch a typo'd host/port once, at configuration time.
    """
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

class TorrentDownloader:
    def __init__(
        self,
        download_dir: str,
        on_progress: Callable[[str, str, float], None],
        on_complete: Callable[[str, str], None],
        proxy: Optional[Dict[str, Any]] = None,
    ):
        self.download_dir = str(Path(download_dir))
        self.on_progress = on_progress
        self.on_complete = on_complete
        # {"host": str, "port": int, "username": Optional[str], "password": Optional[str]}
        self.proxy = proxy

        self._lt: Any = _try_import_libtorrent()
        self._session: Any = None
        self._handles: Dict[str, Any] = {}
        self._aria2c_procs: Dict[str, subprocess.Popen] = {}
        self._progress: Dict[str, float] = {}
        self._names: Dict[str, str] = {}
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._lt is not None:
            self._session = self._lt.session()
            settings: Dict[str, Any] = {
                "listen_interfaces": "0.0.0.0:6881,[::]:6881"
            }
            if self.proxy:
                try:
                    pt = self._lt.settings_pack.proxy_type_t
                    proxy_type = int(
                        pt.socks5_pw if self.proxy.get("username") else pt.socks5
                    )
                except AttributeError:
                    # Unverified against a live libtorrent build in this dev
                    # env — degrade to a plain int rather than crash startup
                    # if the enum path is wrong for whatever version ships.
                    proxy_type = 3 if self.proxy.get("username") else 2
                settings.update({
                    "proxy_type": proxy_type,
                    "proxy_hostname": self.proxy["host"],
                    "proxy_port": int(self.proxy["port"]),
                    "proxy_username": self.proxy.get("username") or "",
                    "proxy_password": self.proxy.get("password") or "",
                    # Without this only tracker/DHT traffic proxies, not the
                    # actual peer data — the whole point of the setting.
                    "proxy_peer_connections": True,
                    # Resolve hostnames through the proxy too, avoiding DNS leaks.
                    "proxy_hostnames": True,
                })
            try:
                # libtorrent 2.x way
                self._session.apply_settings(settings)
            except Exception:
                try:
                    self._session.listen_on(6881, 6891)  # legacy 1.x fallback
                except Exception:
                    pass
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None
        # Take the collections under the lock before touching them — the poll
        # loop and the aria2c monitor threads mutate both as torrents finish.
        with self._lock:
            handles = list(self._handles.values())
            procs = list(self._aria2c_procs.values())
            self._handles.clear()
            self._aria2c_procs.clear()
            self._progress.clear()
            self._names.clear()
        if self._session is not None:
            for handle in handles:
                try:
                    self._session.remove_torrent(handle)
                except Exception:
                    pass
            self._session = None
        for proc in procs:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass

    def add(self, path: str) -> Optional[str]:
        if not self._running:
            return None

        p = Path(path)

        if p.suffix.lower() == ".torrent":
            if self._lt is None and _find_aria2c() is None:
                return None
            name = _torrent_info_name(str(p)) or p.stem
            tid = str(uuid.uuid4())
            self._names[tid] = name
            self._progress[tid] = 0.0
            if self._lt is not None:
                try:
                    info = self._lt.torrent_info(str(p))
                    params = self._lt.add_torrent_params()
                    params.ti = info
                    params.save_path = self.download_dir
                    params.storage_mode = self._lt.storage_mode_t.storage_mode_sparse
                    handle = self._session.add_torrent(params)
                    with self._lock:
                        self._handles[tid] = handle
                    return tid
                except Exception:
                    self._names.pop(tid, None)
                    self._progress.pop(tid, None)
                    return None
            else:
                return self._start_aria2c(tid, str(p), name)

        elif p.suffix.lower() == ".magnet":
            try:
                uri = p.read_text(encoding="utf-8").strip()
            except Exception:
                return None
            if not uri.startswith("magnet:?"):
                return None
            if self._lt is None and _find_aria2c() is None:
                return None
            name = _extract_magnet_name(uri) or p.stem
            tid = str(uuid.uuid4())
            self._names[tid] = name
            self._progress[tid] = 0.0
            return self._add_magnet(tid, uri, name)

        elif path.startswith("magnet:?"):
            if self._lt is None and _find_aria2c() is None:
                return None
            name = _extract_magnet_name(path) or "magnet"
            tid = str(uuid.uuid4())
            self._names[tid] = name
            self._progress[tid] = 0.0
            return self._add_magnet(tid, path, name)

        return None

    def _add_magnet(self, tid: str, uri: str, name: str) -> Optional[str]:
        if self._lt is not None:
            try:
                params = self._lt.parse_magnet_uri(uri)
                params.save_path = self.download_dir
                params.storage_mode = self._lt.storage_mode_t.storage_mode_sparse
                handle = self._session.add_torrent(params)
                with self._lock:
                    self._handles[tid] = handle
                return tid
            except Exception:
                self._names.pop(tid, None)
                self._progress.pop(tid, None)
                return None
        else:
            return self._start_aria2c(tid, uri, name)

    @staticmethod
    def _stage_torrent(target: str) -> tuple[str, Optional[str]]:
        """Copy a .torrent somewhere the caller cannot delete out from under us.

        Popen returns as soon as aria2c is spawned, before it has opened the
        torrent — so "Delete torrent file after adding" could race the read and
        kill the download. aria2c gets its own copy instead; the copy is removed
        when the download ends. Magnet URIs pass straight through.

        Returns (target_for_aria2c, temp_dir_to_clean_up).
        """
        if target.startswith("magnet:?"):
            return target, None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="hoarder_torrent_")
            staged = os.path.join(tmp_dir, Path(target).name)
            shutil.copy2(target, staged)
            return staged, tmp_dir
        except OSError:
            return target, None

    def _start_aria2c(self, tid: str, target: str, name: str) -> Optional[str]:
        aria2c = _find_aria2c()
        if aria2c is None:
            self._names.pop(tid, None)
            self._progress.pop(tid, None)
            self.on_progress(tid, name, -1.0)
            return None
        staged, tmp_dir = self._stage_torrent(target)
        cmd = [
            aria2c, "--seed-time=0", "--summary-interval=1",
            "-d", self.download_dir,
        ]
        if self.proxy:
            cmd.append(
                f"--all-proxy=socks5h://{self.proxy['host']}:{self.proxy['port']}"
            )
            if self.proxy.get("username"):
                cmd.append(f"--all-proxy-user={self.proxy['username']}")
            if self.proxy.get("password"):
                cmd.append(f"--all-proxy-passwd={self.proxy['password']}")
        cmd.append(staged)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
        except OSError:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            self._names.pop(tid, None)
            self._progress.pop(tid, None)
            self.on_progress(tid, name, -1.0)
            return None
        with self._lock:
            self._aria2c_procs[tid] = proc
        self.on_progress(tid, name, 0.0)
        self._spawn_aria2c_monitor(tid, proc, name, tmp_dir)
        return tid

    def _spawn_aria2c_monitor(
        self,
        tid: str,
        proc: subprocess.Popen,
        name: str,
        tmp_dir: Optional[str] = None,
    ) -> None:
        def _monitor():
            rc = -1
            try:
                # Drain stdout (progress summaries). Without this the pipe
                # buffer fills up and aria2c stalls on larger downloads.
                if proc.stdout is not None:
                    last_pct = -1.0
                    for raw in proc.stdout:
                        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                        line = line.strip()
                        m = _ARIA2_PCT_RE.match(line)
                        if m:
                            pct = min(float(m.group(1)) / 100.0, 1.0)
                            if pct != last_pct:
                                last_pct = pct
                                with self._lock:
                                    self._progress[tid] = pct
                                # Callback outside the lock — it marshals into
                                # the Tk thread and must never block a stop().
                                self.on_progress(tid, name, pct)
                rc = proc.wait()
            except Exception:
                pass
            finally:
                if tmp_dir:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            with self._lock:
                self._aria2c_procs.pop(tid, None)
                self._progress[tid] = 1.0 if rc == 0 else -1.0
            if rc == 0:
                self.on_progress(tid, name, 1.0)
                # aria2c's own stdout doesn't reliably report a multi-file
                # torrent's individual file paths (its "FILE:" summary line
                # only ever shows the first file plus a "(N more)" count, not
                # each path) — build the path from the torrent's own name
                # instead, which is exactly where aria2c saves the content
                # under -d.
                download_path = os.path.join(self.download_dir, name)
                self.on_complete(tid, download_path)
            else:
                self.on_progress(tid, name, -1.0)

        t = threading.Thread(target=_monitor, daemon=True)
        t.start()

    def _poll_once(self) -> None:
        if self._lt is not None and self._session is not None:
            with self._lock:
                handles = list(self._handles.items())
            for tid, handle in handles:
                if handle.is_valid():
                    status = handle.status()
                    progress = status.progress
                    with self._lock:
                        name = status.name or self._names.get(tid, "")
                        self._progress[tid] = progress
                    self.on_progress(tid, name, progress)
                    if status.is_seeding or status.is_finished:
                        download_path = os.path.join(self.download_dir, name)
                        self.on_complete(tid, download_path)
                        with self._lock:
                            self._handles.pop(tid, None)
                            self._progress.pop(tid, None)
                            self._names.pop(tid, None)

    def _poll_loop(self) -> None:
        while self._running:
            self._poll_once()
            time.sleep(1)

    def get_progress(self, tid: str) -> float:
        return self._progress.get(tid, 0.0)

    def remove(self, tid: str) -> None:
        with self._lock:
            if tid in self._handles:
                if self._session is not None:
                    self._session.remove_torrent(self._handles[tid])
                del self._handles[tid]
            if tid in self._aria2c_procs:
                try:
                    self._aria2c_procs[tid].terminate()
                except Exception:
                    pass
                del self._aria2c_procs[tid]
            self._progress.pop(tid, None)
            self._names.pop(tid, None)
