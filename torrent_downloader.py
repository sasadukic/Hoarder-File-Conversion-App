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

# aria2c records an unfinished transfer's progress in a control file and
# deletes it the moment that transfer is done, so the file's presence is
# aria2c's own authoritative "not finished yet" signal.
ARIA2_CONTROL_SUFFIX = ".aria2"


def control_file_for(path: Path) -> Path:
    """Where aria2c keeps the control file for the download at *path*.

    aria2c appends ".aria2" to the top-level path it is writing. For a
    single-file torrent that is ``file.ext.aria2`` sitting beside the file;
    for a multi-file torrent it is ``Album.aria2`` sitting beside — **not
    inside** — the ``Album`` folder. Looking only inside the folder is what
    let a half-finished album read as complete.
    """
    return path.with_name(path.name + ARIA2_CONTROL_SUFFIX)


def has_incomplete_download(path: Path) -> bool:
    """True if aria2c still considers anything at or under *path* unfinished."""
    if control_file_for(path).exists():
        return True
    if not path.is_dir():
        return False
    # Belt and braces: aria2c also leaves per-file control files for the
    # plain HTTP/FTP sources a torrent's web seeds can fall back to.
    return any(path.rglob("*" + ARIA2_CONTROL_SUFFIX))


# aria2c summary lines look like:  [#2089b0 400KiB/33MiB(1%) CN:1 DL:115KiB ETA:4m51s]
#
# Anchor the percentage to the aggregate "[#gid ...]" line — a bare "(n%)"
# search also matches per-file lines, which makes the bar jump around on
# multi-file torrents.
_ARIA2_PCT_RE = re.compile(r"^\[#[0-9a-fA-F]+\b.*?\((\d{1,3}(?:\.\d+)?)%\)")

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Progress sentinels handed to on_progress. Real progress is 0.0–1.0; these sit
# outside that range so a single callback can carry state as well as a value.
PROGRESS_ERROR = -1.0
PROGRESS_QUEUED = -2.0

# How many torrents may transfer at once before the rest wait their turn.
DEFAULT_MAX_ACTIVE = 5
MIN_MAX_ACTIVE = 1
MAX_MAX_ACTIVE = 20

# Seconds between aria2c control-file saves (its own default is 60).
CONTROL_SAVE_INTERVAL = 5

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

def sweep_stale_staged_torrents(keep: Any = ()) -> int:
    """Delete staged .torrent copies no unfinished transfer refers to.

    _stage_torrent hands aria2c a private copy of every .torrent so the user's
    "delete after adding" can't pull it out from under a running download, and
    the copy is deliberately left behind at shutdown — it is the only thing a
    resume can be started from. Once a resume has happened (or the record is
    gone), the copy is dead weight in %TEMP%, so each restore sweeps whatever
    is no longer referenced.

    Returns the number of temp directories removed.
    """
    keep_dirs = {str(Path(t).parent) for t in keep if isinstance(t, str) and t}
    removed = 0
    try:
        entries = list(Path(tempfile.gettempdir()).glob("hoarder_torrent_*"))
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or str(entry) in keep_dirs:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
    return removed


def clamp_max_active(value: Any) -> int:
    """Coerce a stored/UI concurrency limit into the supported range."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ACTIVE
    return max(MIN_MAX_ACTIVE, min(MAX_MAX_ACTIVE, n))


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
        max_active: int = DEFAULT_MAX_ACTIVE,
    ):
        self.download_dir = str(Path(download_dir))
        self.on_progress = on_progress
        self.on_complete = on_complete
        # {"host": str, "port": int, "username": Optional[str], "password": Optional[str]}
        self.proxy = proxy
        self.max_active = clamp_max_active(max_active)

        self._lt: Any = _try_import_libtorrent()
        self._session: Any = None
        self._handles: Dict[str, Any] = {}
        self._aria2c_procs: Dict[str, subprocess.Popen] = {}
        self._progress: Dict[str, float] = {}
        self._names: Dict[str, str] = {}
        # Torrents admitted but not started: over the concurrency limit, they
        # wait here for a slot. (tid, target, name) — target is a magnet URI or
        # a .torrent path, i.e. exactly what _start_one needs to begin.
        self._waiting: list = []
        # Reserved slots: torrents past the capacity check but not yet landed
        # in _handles/_aria2c_procs.
        self._starting: set = set()
        # What each live torrent was started from, so a session that ends with
        # transfers in flight can resume them on the next launch.
        self._sources: Dict[str, str] = {}
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
            self._waiting.clear()
            self._starting.clear()
            self._sources.clear()
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

    def add(self, path: str, resume: bool = False) -> Optional[str]:
        """Start (or queue) a transfer.

        *resume* marks a transfer picked up from a previous session, whose
        partial data is already sitting in the download dir — see
        _start_aria2c for what that changes.
        """
        if not self._running:
            return None
        resolved = self._resolve(path)
        if resolved is None:
            return None
        target, name = resolved
        tid = str(uuid.uuid4())
        self._names[tid] = name
        self._progress[tid] = 0.0
        return self._admit(tid, target, name, resume)

    def _resolve(self, path: str) -> Optional[tuple]:
        """Turn what the caller handed us into (target, name), or None.

        The target is what actually starts a transfer — a magnet URI, or a
        .torrent path — so a queued or resumed torrent can be started later
        from nothing more than this pair.
        """
        p = Path(path)

        if p.suffix.lower() == ".torrent":
            if self._lt is None and _find_aria2c() is None:
                return None
            return str(p), (_torrent_info_name(str(p)) or p.stem)

        if p.suffix.lower() == ".magnet":
            try:
                uri = p.read_text(encoding="utf-8").strip()
            except Exception:
                return None
            if not uri.startswith("magnet:?"):
                return None
            if self._lt is None and _find_aria2c() is None:
                return None
            return uri, (_extract_magnet_name(uri) or p.stem)

        if path.startswith("magnet:?"):
            if self._lt is None and _find_aria2c() is None:
                return None
            return path, (_extract_magnet_name(path) or "magnet")

        return None

    # ------------------------------------------------------------------
    # Concurrency limit
    # ------------------------------------------------------------------
    def _active_count(self) -> int:
        """Live transfers. Caller holds the lock.

        Counts torrents still being spawned as well as running ones —
        _start_aria2c only lands in _aria2c_procs once Popen returns, and
        without the reservation two concurrent adds could both look at an
        empty slot and take it.
        """
        return len(self._handles) + len(self._aria2c_procs) + len(self._starting)

    def _admit(
        self, tid: str, target: str, name: str, resume: bool = False
    ) -> Optional[str]:
        """Start *tid* now, or park it until a slot frees up."""
        with self._lock:
            if self._active_count() >= self.max_active:
                self._waiting.append((tid, target, name, resume))
                self.on_progress(tid, name, PROGRESS_QUEUED)
                return tid
            self._starting.add(tid)
        return self._start_one(tid, target, name, resume)

    def _pump(self) -> None:
        """Start as many waiting torrents as there are free slots."""
        while True:
            with self._lock:
                if not self._waiting or self._active_count() >= self.max_active:
                    return
                tid, target, name, resume = self._waiting.pop(0)
                self._starting.add(tid)
            self._start_one(tid, target, name, resume)

    def set_max_active(self, value: Any) -> None:
        """Change the limit while running. Raising it starts waiting torrents;
        lowering it only stops new ones from starting — transfers already in
        flight are left alone rather than being killed mid-download."""
        self.max_active = clamp_max_active(value)
        self._pump()

    def snapshot(self) -> list:
        """Everything unfinished, as {tid, target, name} — live first.

        This is what lets a session that ends with transfers in flight pick
        them up next launch: the target is the magnet URI or the staged
        .torrent copy aria2c was actually given, so a resume is just an add.
        """
        with self._lock:
            live_ids = list(self._handles) + list(self._aria2c_procs)
            out = [
                {"tid": tid, "target": self._sources[tid],
                 "name": self._names.get(tid, "")}
                for tid in live_ids if tid in self._sources
            ]
            out += [
                {"tid": tid, "target": target, "name": name}
                for tid, target, name, _resume in self._waiting
            ]
        return out

    def _start_one(
        self, tid: str, target: str, name: str, resume: bool = False
    ) -> Optional[str]:
        """Hand a resolved (target, name) to whichever backend is available."""
        try:
            if self._lt is not None:
                return self._start_libtorrent(tid, target, name)
            return self._start_aria2c(tid, target, name, resume)
        finally:
            with self._lock:
                self._starting.discard(tid)

    def _start_libtorrent(self, tid: str, target: str, name: str) -> Optional[str]:
        try:
            if target.startswith("magnet:?"):
                params = self._lt.parse_magnet_uri(target)
            else:
                params = self._lt.add_torrent_params()
                params.ti = self._lt.torrent_info(target)
            params.save_path = self.download_dir
            params.storage_mode = self._lt.storage_mode_t.storage_mode_sparse
            handle = self._session.add_torrent(params)
            with self._lock:
                self._handles[tid] = handle
                self._sources[tid] = target
            return tid
        except Exception:
            self._names.pop(tid, None)
            self._progress.pop(tid, None)
            return None

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

    def _start_aria2c(
        self, tid: str, target: str, name: str, resume: bool = False
    ) -> Optional[str]:
        aria2c = _find_aria2c()
        if aria2c is None:
            self._names.pop(tid, None)
            self._progress.pop(tid, None)
            self.on_progress(tid, name, -1.0)
            return None
        staged, tmp_dir = self._stage_torrent(target)
        cmd = [
            aria2c, "--seed-time=0", "--summary-interval=1",
            # Pick up where an interrupted transfer left off instead of
            # starting the file again. For BitTorrent aria2c resumes from its
            # own ".aria2" control file in the download dir; --continue covers
            # the plain HTTP/FTP sources a torrent's web seeds can use.
            "--continue=true",
            # Closing Plunder kills aria2c outright, so whatever is in the
            # control file at that instant is all a resume gets. The default
            # 60s between saves can throw away a minute of transfer — and,
            # worse, leaves no control file at all for a torrent that started
            # less than a minute ago, which reads downstream as "finished".
            f"--auto-save-interval={CONTROL_SAVE_INTERVAL}",
            # Keep a magnet's metadata as a .torrent beside the data, so a
            # resume doesn't have to go back to the DHT for it.
            "--bt-save-metadata=true",
            "-d", self.download_dir,
        ]
        if resume:
            # Hash-check what is already on disk and carry on from there.
            # Without this aria2c trusts the control file alone, so a stale
            # one (or none at all, if the process was killed before the first
            # save) means the partial data is discarded and the torrent
            # restarts from zero.
            cmd.append("--check-integrity=true")
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
            # The staged copy, not the caller's original: the original may be
            # deleted right after adding, while the copy is exactly what a
            # resume needs to hand aria2c again.
            self._sources[tid] = staged
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
                # Keep the staged .torrent when the app is shutting down —
                # that copy is the only way to resume this transfer next
                # launch (the user's original may be long deleted). Anything
                # left unreferenced is swept at the next restore.
                if tmp_dir and self._running:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            with self._lock:
                self._aria2c_procs.pop(tid, None)
                if rc == 0 or self._running:
                    self._sources.pop(tid, None)
                self._progress[tid] = 1.0 if rc == 0 else PROGRESS_ERROR
            self._pump()
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
                            self._sources.pop(tid, None)
                        self._pump()

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
            self._waiting[:] = [w for w in self._waiting if w[0] != tid]
            self._starting.discard(tid)
            self._progress.pop(tid, None)
            self._names.pop(tid, None)
            self._sources.pop(tid, None)
        self._pump()
