import pytest
from pathlib import Path
from gui import (
    detect_mode,
    parse_drop_paths,
    expand_drops,
    format_torrent_name,
    MODE_SPLIT,
    MODE_CONVERT,
    MODE_VIDEO,
    MODE_MIXED,
)


# --- detect_mode ---

def test_detect_mode_split():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.flac", "/m/album.cue"])
    assert mode == MODE_SPLIT
    assert flacs == ["/m/album.flac"]
    assert cue == "/m/album.cue"
    assert videos == []
    assert err is None


def test_detect_mode_convert_single():
    mode, flacs, cue, videos, err = detect_mode(["/m/track01.flac"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/track01.flac"]
    assert cue is None
    assert videos == []
    assert err is None


def test_detect_mode_convert_batch():
    paths = ["/m/t1.flac", "/m/t2.flac", "/m/t3.flac"]
    mode, flacs, cue, videos, err = detect_mode(paths)
    assert mode == MODE_CONVERT
    assert len(flacs) == 3
    assert videos == []
    assert err is None


def test_detect_mode_cue_without_flac():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.cue"])
    assert mode is None
    assert err is not None  # requires an audio file alongside the CUE


# --- New audio format support ---

def test_detect_mode_convert_ape():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.ape"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/album.ape"]
    assert err is None


def test_detect_mode_split_ape_and_cue():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.ape", "/m/album.cue"])
    assert mode == MODE_SPLIT
    assert flacs == ["/m/album.ape"]
    assert cue == "/m/album.cue"
    assert err is None


def test_detect_mode_convert_wma():
    mode, flacs, cue, videos, err = detect_mode(["/m/track.wma"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/track.wma"]
    assert err is None


def test_detect_mode_convert_m4a():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.m4a"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/album.m4a"]
    assert err is None


def test_detect_mode_convert_aiff():
    mode, flacs, cue, videos, err = detect_mode(["/m/track.aiff"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/track.aiff"]
    assert err is None


def test_detect_mode_convert_dsf():
    mode, flacs, cue, videos, err = detect_mode(["/m/dsd.dsf"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/dsd.dsf"]
    assert err is None


def test_detect_mode_mixed_formats_batch():
    """Multiple different audio formats in one drop → batch convert, no CUE."""
    paths = ["/m/a.flac", "/m/b.ape", "/m/c.wma"]
    mode, flacs, cue, videos, err = detect_mode(paths)
    assert mode == MODE_CONVERT
    assert sorted(flacs) == ["/m/a.flac", "/m/b.ape", "/m/c.wma"]
    assert cue is None
    assert err is None


def test_expand_drops_includes_new_audio_formats(tmp_path):
    (tmp_path / "album.ape").touch()
    (tmp_path / "track.wma").touch()
    (tmp_path / "track.aiff").touch()
    (tmp_path / "dsd.dsf").touch()
    result = expand_drops([str(tmp_path)])
    names = {Path(r).name for r in result}
    assert "album.ape" in names
    assert "track.wma" in names
    assert "track.aiff" in names
    assert "dsd.dsf" in names


def test_detect_mode_unsupported_file():
    mode, flacs, cue, videos, err = detect_mode(["/m/track.mp3"])
    assert mode is None
    assert "Unsupported" in err


def test_detect_mode_multiple_cues():
    mode, flacs, cue, videos, err = detect_mode(["/m/a.flac", "/m/a.cue", "/m/b.cue"])
    assert mode is None
    assert "one CUE" in err or "CUE" in err


def test_detect_mode_cue_with_multiple_flacs():
    # CUE is ignored when multiple FLACs are present — just convert the FLACs
    mode, flacs, cue, videos, err = detect_mode(["/m/a.flac", "/m/b.flac", "/m/album.cue"])
    assert mode == MODE_CONVERT
    assert sorted(flacs) == ["/m/a.flac", "/m/b.flac"]
    assert cue is None
    assert videos == []
    assert err is None


def test_detect_mode_video_only():
    mode, flacs, cue, videos, err = detect_mode(["/m/movie.mkv"])
    assert mode == MODE_VIDEO
    assert flacs == []
    assert cue is None
    assert videos == ["/m/movie.mkv"]
    assert err is None


def test_detect_mode_video_only_mp4():
    mode, flacs, cue, videos, err = detect_mode(["/m/clip.mp4", "/m/clip2.avi"])
    assert mode == MODE_VIDEO
    assert sorted(videos) == ["/m/clip.mp4", "/m/clip2.avi"]
    assert err is None


def test_detect_mode_mixed_audio_and_video():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.flac", "/m/movie.mkv"])
    assert mode == MODE_MIXED
    assert flacs == ["/m/album.flac"]
    assert cue is None
    assert videos == ["/m/movie.mkv"]
    assert err is None


def test_detect_mode_mixed_split_and_video():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.flac", "/m/album.cue", "/m/movie.mkv"])
    assert mode == MODE_MIXED
    assert flacs == ["/m/album.flac"]
    assert cue == "/m/album.cue"
    assert videos == ["/m/movie.mkv"]
    assert err is None


def test_expand_drops_includes_video_extensions(tmp_path):
    (tmp_path / "movie.mp4").touch()
    (tmp_path / "clip.mkv").touch()
    (tmp_path / "audio.flac").touch()
    (tmp_path / "cover.jpg").touch()  # ignored
    result = expand_drops([str(tmp_path)])
    assert str(tmp_path / "movie.mp4") in result
    assert str(tmp_path / "clip.mkv") in result
    assert str(tmp_path / "audio.flac") in result
    assert not any("cover.jpg" in r for r in result)


def test_format_torrent_name_strips_dots_dashes_and_truncates():
    result = format_torrent_name("AB.CD - EF.GH IJ.KL MN.OP QR")
    assert result == "ABCD  EFGH IJKL MNOP"
    assert len(result) == 20
    assert "." not in result
    assert "-" not in result


# --- parse_drop_paths ---

def test_parse_drop_paths_simple():
    assert parse_drop_paths("/path/to/file.flac") == ["/path/to/file.flac"]


def test_parse_drop_paths_multiple():
    result = parse_drop_paths("/path/a.flac /path/b.flac")
    assert result == ["/path/a.flac", "/path/b.flac"]


def test_parse_drop_paths_braces():
    result = parse_drop_paths("{/path/with spaces/file.flac}")
    assert result == ["/path/with spaces/file.flac"]


def test_parse_drop_paths_mixed():
    result = parse_drop_paths("{/path/with spaces/file.flac} /path/b.cue")
    assert result == ["/path/with spaces/file.flac", "/path/b.cue"]


# --- expand_drops ---

def test_expand_drops_plain_files_unchanged():
    result = expand_drops(["/m/a.flac", "/m/b.cue"])
    assert result == ["/m/a.flac", "/m/b.cue"]


def test_expand_drops_folder_expands(tmp_path):
    (tmp_path / "track01.flac").touch()
    (tmp_path / "track02.flac").touch()
    (tmp_path / "album.cue").touch()
    (tmp_path / "cover.jpg").touch()  # should be ignored
    result = expand_drops([str(tmp_path)])
    assert sorted(result) == sorted([
        str(tmp_path / "track01.flac"),
        str(tmp_path / "track02.flac"),
        str(tmp_path / "album.cue"),
    ])


def test_expand_drops_mixed_files_and_folder(tmp_path):
    (tmp_path / "extra.flac").touch()
    result = expand_drops(["/m/a.flac", str(tmp_path)])
    assert "/m/a.flac" in result
    assert str(tmp_path / "extra.flac") in result


def test_expand_drops_empty_folder(tmp_path):
    result = expand_drops([str(tmp_path)])
    assert result == []


def test_expand_drops_recurses_into_subdirectories(tmp_path):
    """Dropping a parent/discography folder finds files in all sub-albums."""
    album1 = tmp_path / "1997 - Album One"; album1.mkdir()
    album2 = tmp_path / "1999 - Album Two"; album2.mkdir()
    (album1 / "01 Track.m4a").touch()
    (album1 / "02 Track.m4a").touch()
    (album2 / "01 Song.flac").touch()
    (album2 / "album.cue").touch()
    (tmp_path / "cover.jpg").touch()  # should be ignored

    result = expand_drops([str(tmp_path)])
    result_names = {Path(r).name for r in result}

    assert "01 Track.m4a" in result_names
    assert "02 Track.m4a" in result_names
    assert "01 Song.flac" in result_names
    assert "album.cue" in result_names
    assert "cover.jpg" not in result_names


# --- _pair_cues_flacs ---

def _pair(cues, flacs):
    """Helper: call App._pair_cues_flacs with Path objects."""
    from gui import App
    return App._pair_cues_flacs([Path(c) for c in cues], [Path(f) for f in flacs])


def test_pair_stem_match_single():
    pairs = _pair(["/m/album.cue"], ["/m/album.flac"])
    assert len(pairs) == 1
    flac, cue = pairs[0]
    assert flac.name == "album.flac"
    assert cue.name == "album.cue"


def test_pair_stem_match_two_discs():
    pairs = _pair(
        ["/m/cd1.cue", "/m/cd2.cue"],
        ["/m/cd1.flac", "/m/cd2.flac"],
    )
    assert len(pairs) == 2
    by_stem = {cue.stem: flac.stem for flac, cue in pairs}
    assert by_stem == {"cd1": "cd1", "cd2": "cd2"}


def test_pair_file_directive_fallback(tmp_path):
    # CUE references "disc1.flac" but cue file is named "Album (CD1).cue"
    cue_content = 'FILE "disc1.flac" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
    cue_path = tmp_path / "Album (CD1).cue"
    cue_path.write_text(cue_content, encoding="utf-8")
    flac_path = tmp_path / "disc1.flac"
    flac_path.touch()

    pairs = _pair([str(cue_path)], [str(flac_path)])
    assert len(pairs) == 1
    flac, cue = pairs[0]
    assert flac.name == "disc1.flac"
    assert cue.name == "Album (CD1).cue"


def test_pair_no_match_returns_empty():
    pairs = _pair(["/m/album.cue"], ["/m/completely_different.flac"])
    # Stem mismatch and no real FILE directive (paths are fake) → empty
    assert pairs == []


def test_pair_each_flac_used_once():
    # Two CUEs both stem-matching the same FLAC: only first pair wins
    pairs = _pair(
        ["/m/track.cue", "/m/track_alt.cue"],
        ["/m/track.flac"],
    )
    # Only the first cue ("track.cue") stem-matches "track.flac"
    assert len(pairs) == 1
    _, cue = pairs[0]
    assert cue.name == "track.cue"


# --- split_torrent_paths ---

from gui import split_torrent_paths


def test_split_torrent_paths_separates_torrents():
    torrents, others = split_torrent_paths(
        ["/m/movie.torrent", "/m/album.flac", "/m/link.magnet"]
    )
    assert torrents == ["/m/movie.torrent", "/m/link.magnet"]
    assert others == ["/m/album.flac"]


def test_split_torrent_paths_magnet_uri():
    torrents, others = split_torrent_paths(["magnet:?xt=urn:btih:abc&dn=X"])
    assert torrents == ["magnet:?xt=urn:btih:abc&dn=X"]
    assert others == []


def test_split_torrent_paths_no_torrents():
    torrents, others = split_torrent_paths(["/m/a.flac", "/m/a.cue"])
    assert torrents == []
    assert others == ["/m/a.flac", "/m/a.cue"]


# --- self-produced output suppression ---
#
# Exercises App's real methods against a stand-in holding just the state they
# touch, so no Tk root (and no display) is needed.

import threading

from gui import App


class _IgnoreHost:
    """Minimal stand-in carrying only what the ignore-set methods use."""

    # staticmethod() re-wraps it — a bare assignment would rebind it as an
    # instance method and pass self as the path.
    _ignore_key = staticmethod(App._ignore_key)
    _ignore_output = App._ignore_output
    _claim_ignored = App._claim_ignored
    _on_monitor_files = App._on_monitor_files
    _enqueue_new = App._enqueue_new

    def __init__(self):
        self._ignore_paths = set()
        self._ignore_lock = threading.Lock()
        self.enqueued = []

    def _enqueue_conversion(self, paths):
        self.enqueued.append(paths)

    def after(self, _delay, fn, paths):
        fn(paths)


@pytest.fixture(autouse=True)
def temp_library(tmp_path, monkeypatch):
    """Keep the conversion library out of the repo during tests."""
    import library as libmod
    monkeypatch.setattr(libmod, "_LIBRARY_PATH", tmp_path / "library.json")


def test_registered_output_is_skipped_once():
    host = _IgnoreHost()
    host._ignore_output(str(Path.cwd() / "movie.mp4"))

    # The transcode's own output must not re-enter the queue...
    host._on_monitor_files([str(Path.cwd() / "movie.mp4")])
    assert host.enqueued == []

    # ...but the same name arriving again later is a genuine new file.
    host._on_monitor_files([str(Path.cwd() / "movie.mp4")])
    assert host.enqueued == [[str(Path.cwd() / "movie.mp4")]]


def test_unregistered_files_still_convert():
    host = _IgnoreHost()
    host._on_monitor_files(["/m/album.flac", "/m/album.cue"])
    assert host.enqueued == [["/m/album.flac", "/m/album.cue"]]


def test_ignore_survives_path_spelling():
    """Watchdog and ffmpeg can spell the same file differently."""
    host = _IgnoreHost()
    host._ignore_output(str(Path.cwd() / "sub" / ".." / "movie.mp4"))
    assert host._claim_ignored(str(Path.cwd() / "movie.mp4")) is True


def test_ignored_path_does_not_suppress_its_siblings():
    host = _IgnoreHost()
    host._ignore_output(str(Path.cwd() / "a.mp4"))
    host._on_monitor_files([str(Path.cwd() / "a.mp4"), str(Path.cwd() / "b.mp4")])
    assert host.enqueued == [[str(Path.cwd() / "b.mp4")]]


def test_watcher_skips_files_already_in_the_library(tmp_path):
    """A file converted in an earlier run must not be queued again."""
    import library as libmod
    f = tmp_path / "album.flac"
    f.write_bytes(b"already done")
    libmod.mark([str(f)])

    host = _IgnoreHost()
    host._on_monitor_files([str(f)])
    assert host.enqueued == []


# --- startup scan vs. the library ---


class _ScanHost:
    """Stand-in for the startup scan: real methods, no Tk."""

    _scan_existing_files = App._scan_existing_files
    _enqueue_media_tree = App._enqueue_media_tree
    _enqueue_new = App._enqueue_new
    _enqueue_pair = App._enqueue_pair
    _pair_cues_flacs = staticmethod(App._pair_cues_flacs)

    def __init__(self):
        self.enqueued = []

    def _enqueue_conversion(self, paths):
        self.enqueued.append(paths)

    def after(self, _delay, fn, *args):
        fn(*args)


def test_startup_scan_skips_previously_converted_files(tmp_path):
    import library as libmod
    old = tmp_path / "already.flac"
    old.write_bytes(b"converted last run")
    fresh = tmp_path / "new.flac"
    fresh.write_bytes(b"never seen")
    libmod.mark([str(old)])

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == [[str(fresh)]]


def test_startup_scan_skips_its_own_transcodes(tmp_path):
    """The .mp4 a previous run produced must not be transcoded again."""
    import library as libmod
    out = tmp_path / "movie.mp4"
    out.write_bytes(b"h265 output from last run")
    libmod.mark([str(out)])

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == []


def test_startup_scan_still_queues_a_cue_pair(tmp_path):
    audio = tmp_path / "album.flac"
    audio.write_bytes(b"disc one")
    cue = tmp_path / "album.cue"
    cue.write_text('FILE "album.flac" WAVE\n  TRACK 01 AUDIO\n')

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == [[str(audio), str(cue)]]


def test_startup_scan_skips_a_converted_cue_pair(tmp_path):
    import library as libmod
    audio = tmp_path / "album.flac"
    audio.write_bytes(b"disc one")
    cue = tmp_path / "album.cue"
    cue.write_text('FILE "album.flac" WAVE\n  TRACK 01 AUDIO\n')
    libmod.mark([str(audio)])

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == []


def test_startup_scan_skips_torrent_staging_folder(tmp_path):
    """A download still in progress must not be picked up by the startup scan."""
    from torrent_downloader import STAGING_DIRNAME
    staging = tmp_path / STAGING_DIRNAME
    staging.mkdir()
    (staging / "still-downloading.mkv").write_bytes(b"partial")

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == []


def test_startup_scan_skips_zero_byte_video(tmp_path):
    """A stray 0-byte placeholder (e.g. an aria2/torrent artifact) must not
    be queued — ffprobe fails on it with no usable error message."""
    (tmp_path / "placeholder.mkv").write_bytes(b"")
    real = tmp_path / "movie.mp4"
    real.write_bytes(b"h265 data")

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == [[str(real)]]


def test_startup_scan_skips_zero_byte_audio(tmp_path):
    (tmp_path / "placeholder.flac").write_bytes(b"")
    real = tmp_path / "track.flac"
    real.write_bytes(b"fLaC" + b"\x00" * 100)

    host = _ScanHost()
    host._scan_existing_files(str(tmp_path))
    assert host.enqueued == [[str(real)]]


# --- torrent completion: move out of staging, then convert ---

import types
import shutil as _shutil
import gui as gui_mod
from gui import App as _App


class _TorrentCompleteHost:
    """Stand-in for _on_torrent_complete_gui: real methods, no Tk."""

    _on_torrent_complete_gui = _App._on_torrent_complete_gui
    _move_into_monitor_folder = staticmethod(_App._move_into_monitor_folder)
    _enqueue_media_tree = _App._enqueue_media_tree
    _enqueue_new = _App._enqueue_new
    _enqueue_pair = _App._enqueue_pair
    _pair_cues_flacs = staticmethod(_App._pair_cues_flacs)
    _remove_torrent_progress = _App._remove_torrent_progress

    def __init__(self, monitor_folder):
        self._monitor_folder_var = types.SimpleNamespace(get=lambda: monitor_folder)
        self._torrent_progress_widgets = {}
        self.enqueued = []
        self.errors = []

    def _play_torrent_downloaded(self):
        pass

    def _save_session(self):
        pass

    def _enqueue_conversion(self, paths):
        self.enqueued.append(paths)

    def _set_info(self, text, color):
        self.errors.append(text)

    def after(self, _delay, fn, *args):
        fn(*args)


def test_torrent_complete_moves_single_file_watcher_handles_the_rest(tmp_path):
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    staging = monitor / ".hoarder-incoming"
    staging.mkdir()
    src = staging / "movie.mkv"
    src.write_bytes(b"finished download")

    host = _TorrentCompleteHost(str(monitor))
    host._on_torrent_complete_gui("abcdef12", str(src))

    assert not src.exists()
    assert (monitor / "movie.mkv").read_bytes() == b"finished download"
    # Single files are picked up by the real folder watcher once moved in —
    # this function doesn't explicitly enqueue them itself.
    assert host.enqueued == []


def test_torrent_complete_moves_and_enqueues_multi_file_directory(tmp_path):
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    staging = monitor / ".hoarder-incoming"
    album = staging / "Album"
    album.mkdir(parents=True)
    (album / "01.flac").write_bytes(b"track one")
    (album / "02.flac").write_bytes(b"track two")

    host = _TorrentCompleteHost(str(monitor))
    host._on_torrent_complete_gui("abcdef12", str(album))

    assert not album.exists()
    dest = monitor / "Album"
    assert sorted(p.name for p in dest.iterdir()) == ["01.flac", "02.flac"]
    # Directory moves don't fire a per-file watchdog event, so this needs
    # the explicit nudge.
    assert host.enqueued == [[str(dest / "01.flac"), str(dest / "02.flac")]]


def test_torrent_complete_missing_source_is_a_noop(tmp_path):
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    host = _TorrentCompleteHost(str(monitor))
    host._on_torrent_complete_gui("tid", str(tmp_path / "gone.mkv"))
    assert host.enqueued == []
    assert host.errors == []


def test_torrent_complete_no_monitor_folder_is_a_noop(tmp_path):
    host = _TorrentCompleteHost("")
    host._on_torrent_complete_gui("tid", str(tmp_path / "whatever.mkv"))
    assert host.enqueued == []


def test_torrent_complete_move_failure_shows_error(tmp_path, monkeypatch):
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"data")

    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(_shutil, "move", _boom)
    monkeypatch.setattr("gui.shutil.move", _boom)

    host = _TorrentCompleteHost(str(monitor))
    host._on_torrent_complete_gui("tid", str(src))
    assert host.enqueued == []
    assert any("disk full" in e for e in host.errors)


def test_move_into_monitor_folder_disambiguates_colliding_file(tmp_path):
    dest_parent = tmp_path / "monitor"
    dest_parent.mkdir()
    (dest_parent / "movie.mkv").write_bytes(b"already here")
    src = tmp_path / "staging" / "movie.mkv"
    src.parent.mkdir()
    src.write_bytes(b"newly downloaded")

    result = _App._move_into_monitor_folder(src, dest_parent, "abcd1234")

    assert (dest_parent / "movie.mkv").read_bytes() == b"already here"
    assert result.name == "movie_abcd1234.mkv"
    assert result.read_bytes() == b"newly downloaded"


def test_move_into_monitor_folder_merges_colliding_directory(tmp_path):
    dest_parent = tmp_path / "monitor"
    dest = dest_parent / "Album"
    dest.mkdir(parents=True)
    (dest / "01.flac").write_bytes(b"old track one")

    src = tmp_path / "staging" / "Album"
    src.mkdir(parents=True)
    (src / "01.flac").write_bytes(b"new track one, name collides")
    (src / "02.flac").write_bytes(b"new track two")

    result = _App._move_into_monitor_folder(src, dest_parent, "abcd1234")

    assert result == dest
    assert not src.exists()
    assert (dest / "01.flac").read_bytes() == b"old track one"
    assert (dest / "01_abcd1234.flac").read_bytes() == b"new track one, name collides"
    assert (dest / "02.flac").read_bytes() == b"new track two"


# --- flagging finished output with " Done" ---

class _FlagDoneHost:
    _flag_encoded_done = App._flag_encoded_done

    def __init__(self, monitor_folder=""):
        self._monitor_folder_var = _MutableVar(monitor_folder)
        self.ignored = []

    def _ignore_output(self, path):
        self.ignored.append(path)


def test_flag_done_renames_the_shared_source_folder(tmp_path):
    """A dedicated album/movie folder gets one rename covering every file."""
    album = tmp_path / "Monitor" / "Some Album"
    album.mkdir(parents=True)
    (album / "01.mp3").write_bytes(b"one")
    (album / "02.mp3").write_bytes(b"two")

    host = _FlagDoneHost(monitor_folder=str(tmp_path / "Monitor"))
    outputs = host._flag_encoded_done(
        album, [str(album / "01.mp3"), str(album / "02.mp3")], moved=False,
    )

    renamed = tmp_path / "Monitor" / "Some Album Done"
    assert renamed.is_dir()
    assert not album.exists()
    assert set(outputs) == {str(renamed / "01.mp3"), str(renamed / "02.mp3")}


def test_flag_done_flags_files_individually_at_the_monitor_root(tmp_path):
    """Loose files sitting directly in the monitored folder share it with
    unrelated batches, so there is no single folder to rename."""
    monitor = tmp_path / "Monitor"
    monitor.mkdir()
    (monitor / "track.mp3").write_bytes(b"one")

    host = _FlagDoneHost(monitor_folder=str(monitor))
    outputs = host._flag_encoded_done(monitor, [str(monitor / "track.mp3")], moved=False)

    assert outputs == [str(monitor / "track Done.mp3")]
    assert (monitor / "track Done.mp3").exists()
    assert not (monitor / "track.mp3").exists()


def test_flag_done_flags_files_individually_when_moved_elsewhere(tmp_path):
    """A move-to-folder destination is shared by every batch that uses it,
    same reasoning as the monitor root — even though the source folder was
    its own dedicated album folder."""
    album = tmp_path / "Monitor" / "Some Album"
    album.mkdir(parents=True)
    dest = tmp_path / "Library"
    dest.mkdir()
    (dest / "song.mp3").write_bytes(b"moved already")

    host = _FlagDoneHost(monitor_folder=str(tmp_path / "Monitor"))
    outputs = host._flag_encoded_done(album, [str(dest / "song.mp3")], moved=True)

    assert outputs == [str(dest / "song Done.mp3")]
    assert album.exists()  # untouched — only the moved file was flagged


def test_flag_done_registers_video_outputs_before_renaming(tmp_path):
    """A renamed video is still a video by extension, so the watcher would
    otherwise treat the rename as a newly arrived source file."""
    monitor = tmp_path / "Monitor"
    monitor.mkdir()
    (monitor / "movie.mp4").write_bytes(b"video")

    host = _FlagDoneHost(monitor_folder=str(monitor))
    outputs = host._flag_encoded_done(
        monitor, [str(monitor / "movie.mp4")], moved=False, is_video=True,
    )

    assert outputs == [str(monitor / "movie Done.mp4")]
    assert host.ignored == [str(monitor / "movie Done.mp4")]


def test_flag_done_does_not_double_flag_an_already_flagged_folder(tmp_path):
    album = tmp_path / "Monitor" / "Some Album Done"
    album.mkdir(parents=True)
    (album / "01.mp3").write_bytes(b"one")

    host = _FlagDoneHost(monitor_folder=str(tmp_path / "Monitor"))
    outputs = host._flag_encoded_done(album, [str(album / "01.mp3")], moved=False)

    # Folder rename is skipped (already flagged); falls back to per-file,
    # which flags the file since *it* isn't flagged yet.
    assert album.is_dir()
    assert outputs == [str(album / "01 Done.mp3")]


def test_flag_done_does_not_double_flag_an_already_flagged_file(tmp_path):
    monitor = tmp_path / "Monitor"
    monitor.mkdir()
    (monitor / "track Done.mp3").write_bytes(b"one")

    host = _FlagDoneHost(monitor_folder=str(monitor))
    outputs = host._flag_encoded_done(
        monitor, [str(monitor / "track Done.mp3")], moved=False,
    )

    assert outputs == [str(monitor / "track Done.mp3")]


def test_flag_done_is_a_noop_with_no_outputs(tmp_path):
    host = _FlagDoneHost(monitor_folder=str(tmp_path))
    assert host._flag_encoded_done(tmp_path, [], moved=False) == []
    assert host.ignored == []


# --- CUE-mode output paths must be computed before the CUE file is deleted ---
#
# _run_conversion used to call _audio_outputs(flacs, cue) *after*
# delete_companion_files(flacs, cue) when "delete source after conversion"
# was enabled. _audio_outputs re-parses the CUE file to name each split
# track, but delete_companion_files had already unlinked that same file —
# so the re-parse raised FileNotFoundError, which the generic
# `except Exception` in _run_conversion caught, aborting before the
# move-to-folder / library-mark / done steps ever ran. Net effect: CUE-split
# audio never moved to move_music_folder when delete_flac was on, even
# though the split itself succeeded and video (which never re-reads a CUE
# file) was unaffected. Fixed by computing outputs right after the split
# succeeds, before the companion-file cleanup runs.

def test_audio_outputs_reads_cue_before_it_is_deleted(tmp_path):
    from converter import delete_companion_files
    from gui import App

    flac = tmp_path / "album.flac"
    flac.write_bytes(b"fake flac data")
    cue = tmp_path / "album.cue"
    cue.write_text(
        'FILE "album.flac" WAVE\n'
        "  TRACK 01 AUDIO\n"
        '    TITLE "First Song"\n'
        "    INDEX 01 00:00:00\n"
        "  TRACK 02 AUDIO\n"
        '    TITLE "Second Song"\n'
        "    INDEX 01 03:00:00\n",
        encoding="utf-8",
    )

    # Computed while the CUE file still exists (the fixed ordering) —
    # succeeds and returns the real split-track paths.
    outputs = App._audio_outputs([str(flac)], str(cue))
    assert outputs == [
        str(tmp_path / "01 - First Song.mp3"),
        str(tmp_path / "02 - Second Song.mp3"),
    ]

    delete_companion_files([str(flac)], str(cue))
    assert not cue.exists()

    # Computed after deletion (the old, buggy ordering) — raises, which is
    # exactly what used to abort _run_conversion before it could move the
    # split tracks to move_music_folder.
    with pytest.raises(FileNotFoundError):
        App._audio_outputs([str(flac)], str(cue))


# --- encoding-box rows appear at enqueue time, not conversion start ---
#
# Previously, rows for a batch only appeared once that batch actually
# started converting, and _run_conversion cleared the whole box first — so
# queuing several folders at once (e.g. every disc of a multi-folder
# torrent) revealed them one folder at a time instead of showing the full
# pending list right away.

class _EnqueueHost:
    """Stand-in for _enqueue_conversion: real method, no Tk, no real queue
    processing (that path spawns threads/ffmpeg — out of scope here)."""

    _enqueue_conversion = App._enqueue_conversion
    _already_queued = App._already_queued
    _ignore_key = staticmethod(App._ignore_key)

    def __init__(self):
        self._conversion_queue = []
        self._active_batch = None
        self.added_rows = []
        self.queue_processed = False
        self.sessions_saved = 0

    def after(self, _delay, fn, *args):
        fn(*args)

    def _add_encoding_progress(self, task_id, name):
        self.added_rows.append(task_id)

    def _save_session(self):
        self.sessions_saved += 1

    def _process_next_queue_item(self):
        self.queue_processed = True


def test_enqueue_conversion_adds_rows_for_the_whole_batch_immediately(tmp_path):
    f1 = tmp_path / "01.flac"
    f2 = tmp_path / "02.flac"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")

    host = _EnqueueHost()
    host._enqueue_conversion([str(f1), str(f2)])

    assert host.added_rows == [str(f1), str(f2)]
    assert host._conversion_queue == [[str(f1), str(f2)]]
    assert host.queue_processed is True


def test_enqueue_conversion_adds_rows_for_video_batches_too(tmp_path):
    v = tmp_path / "movie.mkv"
    v.write_bytes(b"x")
    host = _EnqueueHost()
    host._enqueue_conversion([str(v)])
    assert host.added_rows == [str(v)]


def test_enqueue_conversion_accumulates_rows_across_multiple_batches(tmp_path):
    """Simulates a multi-folder torrent: each disc enqueues separately, but
    all of their rows should be visible together, not one disc at a time."""
    disc1 = tmp_path / "disc1"
    disc2 = tmp_path / "disc2"
    disc1.mkdir()
    disc2.mkdir()
    a = disc1 / "01.flac"
    b = disc2 / "01.flac"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    host = _EnqueueHost()
    host._enqueue_conversion([str(a)])
    host._enqueue_conversion([str(b)])

    assert host.added_rows == [str(a), str(b)]
    assert host._conversion_queue == [[str(a)], [str(b)]]


def test_enqueue_conversion_rejects_invalid_batch_without_adding_rows(tmp_path):
    bogus = tmp_path / "notes.txt"
    bogus.write_bytes(b"not media")
    host = _EnqueueHost()
    host._enqueue_conversion([str(bogus)])
    assert host.added_rows == []
    assert host._conversion_queue == []
    assert host.queue_processed is False


# --- _load_files (direct drop/browse, 0-1 CUE) also adds encoding rows ---
#
# _enqueue_conversion (multi-disc batches) always added rows before
# conversion started. But a direct drop or browse with 0 or 1 CUE skips
# _enqueue_conversion entirely and calls _load_files -> _start_conversion
# straight away, so it never added any rows — conversion ran with nothing
# visible in the encoding box until the final "Done" sound.

class _LoadFilesHost:
    """Stand-in for _load_files: real method, no Tk, no real conversion
    (that path spawns threads/ffmpeg — out of scope here)."""

    _load_files = App._load_files

    def __init__(self):
        self.added_rows = []
        self.info_messages = []
        self.conversion_started = False

    def _add_encoding_progress(self, task_id, name):
        self.added_rows.append(task_id)

    def _set_info(self, text, color=None):
        self.info_messages.append(text)

    def _start_conversion(self):
        self.conversion_started = True


def test_load_files_adds_rows_for_direct_drop(tmp_path):
    f1 = tmp_path / "01.flac"
    f2 = tmp_path / "02.flac"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")

    host = _LoadFilesHost()
    host._load_files([str(f1), str(f2)])

    assert host.added_rows == [str(f1), str(f2)]
    assert host.conversion_started is True


def test_load_files_adds_rows_for_video_drop(tmp_path):
    v = tmp_path / "movie.mkv"
    v.write_bytes(b"x")

    host = _LoadFilesHost()
    host._load_files([str(v)])

    assert host.added_rows == [str(v)]


def test_load_files_adds_no_rows_and_does_not_start_on_invalid_selection(tmp_path):
    bogus = tmp_path / "notes.txt"
    bogus.write_bytes(b"not media")

    host = _LoadFilesHost()
    host._load_files([str(bogus)])

    assert host.added_rows == []
    assert host.conversion_started is False
    assert host.info_messages == ["Unsupported file type"]


# --- staged-download recovery (orphaned aria2c child finished after
# Hoarder itself was closed/killed mid-download) ---

class _RecoveryHost:
    """Stand-in for _recover_staged_downloads: real methods, no Tk."""

    _recover_staged_downloads = _App._recover_staged_downloads
    _has_incomplete_download = staticmethod(_App._has_incomplete_download)
    _move_into_monitor_folder = staticmethod(_App._move_into_monitor_folder)

    def __init__(self, unfinished=()):
        self.infos = []
        self._unfinished = set(unfinished)

    def _unfinished_download_names(self):
        return self._unfinished

    def _set_info(self, text, color):
        self.infos.append(text)


def test_recover_moves_complete_file_with_no_aria2_marker(tmp_path):
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    staging.mkdir(parents=True)
    (staging / "movie.mkv").write_bytes(b"fully downloaded")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert (monitor / "movie.mkv").read_bytes() == b"fully downloaded"
    assert not (staging / "movie.mkv").exists()
    assert host.infos == ["Recovered 1 interrupted download"]


def test_recover_leaves_file_with_aria2_marker_in_place(tmp_path):
    """A lingering .aria2 control file means aria2c itself doesn't
    consider the download finished — must not be swept in."""
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    staging.mkdir(parents=True)
    (staging / "movie.mkv").write_bytes(b"still downloading")
    (staging / "movie.mkv.aria2").write_bytes(b"aria2 control data")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert (staging / "movie.mkv").exists()
    assert not (monitor / "movie.mkv").exists()
    assert host.infos == []


def test_recover_moves_complete_directory_tree(tmp_path):
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    album = staging / "Album"
    (album / "disc1").mkdir(parents=True)
    (album / "disc1" / "01.flac").write_bytes(b"track")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert (monitor / "Album" / "disc1" / "01.flac").read_bytes() == b"track"
    assert not album.exists()
    assert host.infos == ["Recovered 1 interrupted download"]


def test_recover_leaves_directory_with_any_incomplete_file(tmp_path):
    """One unfinished file anywhere in the tree holds the whole thing back."""
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    album = staging / "Album"
    (album / "disc1").mkdir(parents=True)
    (album / "disc1" / "01.flac").write_bytes(b"done")
    (album / "disc1" / "02.flac").write_bytes(b"partial")
    (album / "disc1" / "02.flac.aria2").write_bytes(b"still going")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert album.exists()
    assert not (monitor / "Album").exists()
    assert host.infos == []


def test_recover_leaves_multi_file_torrent_with_sibling_control_file(tmp_path):
    """aria2c parks a multi-file torrent's control file *beside* the folder,
    not inside it — checking only inside made a half-finished album look
    complete, so it was swept into the monitored folder and encoded instead
    of being resumed."""
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    album = staging / "Album"
    album.mkdir(parents=True)
    (album / "01.flac").write_bytes(b"half a track")
    (staging / "Album.aria2").write_bytes(b"aria2 control data")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert album.exists()
    assert not (monitor / "Album").exists()
    assert host.infos == []


def test_recover_leaves_anything_the_session_still_calls_unfinished(tmp_path):
    """A transfer killed before aria2c's first control-file save has no marker
    at all. The saved session is what remembers it."""
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    album = staging / "Album"
    album.mkdir(parents=True)
    (album / "01.flac").write_bytes(b"a few pieces")

    host = _RecoveryHost(unfinished={"Album"})
    host._recover_staged_downloads(str(monitor))

    assert album.exists()
    assert not (monitor / "Album").exists()
    assert host.infos == []


def test_recover_ignores_aria2_bookkeeping_files(tmp_path):
    """Neither a control file nor the .torrent aria2c saves for a magnet is
    content — moving either into the monitored folder would have the watcher
    re-add the torrent."""
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    staging.mkdir(parents=True)
    (staging / "orphan.aria2").write_bytes(b"control")
    (staging / "abc123.torrent").write_bytes(b"metadata")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert (staging / "orphan.aria2").exists()
    assert (staging / "abc123.torrent").exists()
    assert host.infos == []


def test_recover_no_staging_folder_is_a_noop(tmp_path):
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))
    assert host.infos == []


def test_recover_reports_combined_count(tmp_path):
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    staging.mkdir(parents=True)
    (staging / "a.mkv").write_bytes(b"one")
    (staging / "b.flac").write_bytes(b"two")

    host = _RecoveryHost()
    host._recover_staged_downloads(str(monitor))

    assert host.infos == ["Recovered 2 interrupted downloads"]


def test_recover_returns_the_number_moved(tmp_path):
    """The periodic sweep needs this to decide whether a rescan is worth it."""
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    staging.mkdir(parents=True)
    (staging / "a.mkv").write_bytes(b"one")
    (staging / "b.flac").write_bytes(b"two")

    host = _RecoveryHost()
    assert host._recover_staged_downloads(str(monitor)) == 2


def test_recover_returns_zero_when_nothing_is_ready(tmp_path):
    monitor = tmp_path / "monitor"
    staging = monitor / ".hoarder-incoming"
    staging.mkdir(parents=True)
    (staging / "a.mkv").write_bytes(b"partial")
    (staging / "a.mkv.aria2").write_bytes(b"still going")

    host = _RecoveryHost()
    assert host._recover_staged_downloads(str(monitor)) == 0


# --- periodic staging sweep (a completion that never fired on_complete —
# e.g. because of an error mid-callback — used to sit stuck until the app
# was restarted; now the monitor rechecks staging on a timer) ---

class _SweepHost:
    _schedule_staging_sweep = _App._schedule_staging_sweep
    _sweep_stuck_staging = _App._sweep_stuck_staging
    _STAGING_SWEEP_MS = _App._STAGING_SWEEP_MS

    def __init__(self, folder="/monitor", monitor_running=True, recovered=0):
        self._monitor_folder_var = _MutableVar(folder)
        self._monitor = object() if monitor_running else None
        self._staging_sweep_after_id = None
        self._recovered = recovered
        self.recover_calls = []
        self.scan_calls = []
        self.after_calls = []

    def after(self, ms, fn):
        self.after_calls.append((ms, fn))
        return f"id-{len(self.after_calls)}"

    def _recover_staged_downloads(self, folder):
        self.recover_calls.append(folder)
        return self._recovered

    def _scan_existing_files(self, folder):
        self.scan_calls.append(folder)


def test_schedule_staging_sweep_books_a_timer():
    host = _SweepHost()
    host._schedule_staging_sweep()
    assert host.after_calls == [(host._STAGING_SWEEP_MS, host._sweep_stuck_staging)]
    assert host._staging_sweep_after_id == "id-1"


def test_sweep_rescans_when_something_was_stuck_in_staging():
    host = _SweepHost(recovered=1)
    host._sweep_stuck_staging()
    assert host.recover_calls == ["/monitor"]
    assert host.scan_calls == ["/monitor"]
    assert len(host.after_calls) == 1  # reschedules itself


def test_sweep_does_not_rescan_the_library_when_staging_was_already_clear():
    host = _SweepHost(recovered=0)
    host._sweep_stuck_staging()
    assert host.recover_calls == ["/monitor"]
    assert host.scan_calls == []
    assert len(host.after_calls) == 1  # still reschedules — the next check


def test_sweep_stops_once_the_monitor_has_been_turned_off():
    host = _SweepHost(monitor_running=False)
    host._sweep_stuck_staging()
    assert host.recover_calls == []
    assert host.after_calls == []
    assert host._staging_sweep_after_id is None


def test_sweep_stops_once_the_monitor_folder_is_cleared():
    host = _SweepHost(folder="")
    host._sweep_stuck_staging()
    assert host.recover_calls == []
    assert host.after_calls == []


# --- _parse_port ---

def test_parse_port_valid():
    assert _App._parse_port("1080") == 1080


def test_parse_port_non_numeric():
    assert _App._parse_port("not a port") is None


def test_parse_port_out_of_range():
    assert _App._parse_port("99999") is None
    assert _App._parse_port("0") is None


# --- _save_settings persists every setting.py default ---
#
# Regression guard for exactly the bug that slipped through once already:
# a new tk.Variable was wired up in the Setup tab and added to settings.py's
# _DEFAULTS, but _save_settings itself was never updated to write it out —
# so the setting looked configurable in the UI but silently never persisted.

def _var(value):
    return types.SimpleNamespace(get=lambda: value)


class _SaveSettingsHost:
    _save_settings = _App._save_settings
    _parse_port = staticmethod(_App._parse_port)

    def __init__(self):
        self._delete_var = _var(False)
        self._auto_convert_var = _var(False)
        self._tray_var = _var(False)
        self._startup_var = _var(False)
        self._sounds_var = _var(True)
        self._monitor_var = _var(False)
        self._monitor_folder_var = _var("")
        self._torrent_var = _var(False)
        self._torrent_delete_var = _var(False)
        self._move_music_var = _var(False)
        self._move_music_folder_var = _var("")
        self._move_video_var = _var(False)
        self._move_video_folder_var = _var("")
        self._proxy_var = _var(False)
        self._proxy_host_var = _var("")
        self._proxy_port_var = _var("")
        self._proxy_username_var = _var("")
        self._proxy_password_var = _var("")
        self._torrent_ext_asked = False
        self._sound_volume = 100
        self._max_downloads = 5


def test_save_settings_writes_every_default_key(monkeypatch):
    import settings as smod
    captured = {}
    monkeypatch.setattr(smod, "save", lambda data: captured.update(data))

    host = _SaveSettingsHost()
    host._save_settings()

    assert set(captured.keys()) == set(smod._DEFAULTS.keys())


# --- .torrent file association prompt/toggle ---
#
# The registry-touching methods themselves (_register_torrent_ext_handler
# etc.) aren't unit tested here, matching this codebase's existing choice
# not to test the analogous magnet-handler registry calls — both mutate
# real HKEY_CURRENT_USER state, which isn't something to do from a test
# run. What's covered instead is the decision logic around them: whether
# the toggle rolls back the checkbox on failure, and whether the startup
# prompt correctly skips when it's already been asked or already set up.

class _MutableVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


# --- Windows startup registration (HKCU Run value, no subprocess) ---

class _FakeRegistry:
    """Enough of winreg to exercise the startup code off Windows.

    The real thing is unavailable here and conftest's stub raises on every
    read, so neither can show that the right value lands under the right key.
    """

    HKEY_CURRENT_USER = 0
    KEY_ALL_ACCESS = 0xF003F
    REG_SZ = 1

    def __init__(self, initial=None, create_raises=None):
        self.values = dict(initial or {})
        self.create_raises = create_raises

    class _Key:
        def __init__(self, reg, path):
            self.reg, self.path = reg, path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def CreateKey(self, hive, path):
        if self.create_raises:
            raise self.create_raises
        return self._Key(self, path)

    def OpenKey(self, hive, path, reserved=0, access=0):
        if path not in {k[0] for k in self.values}:
            raise FileNotFoundError(path)
        return self._Key(self, path)

    def SetValueEx(self, key, name, reserved, typ, value):
        self.values[(key.path, name)] = value

    def QueryValueEx(self, key, name):
        try:
            return self.values[(key.path, name)], self.REG_SZ
        except KeyError:
            raise FileNotFoundError(name)

    def DeleteValue(self, key, name):
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        del self.values[(key.path, name)]


_RUN_KEY = _App._STARTUP_RUN_KEY


class _StartupHost:
    _on_startup_toggle = _App._on_startup_toggle
    _enable_startup = _App._enable_startup
    _disable_startup = _App._disable_startup
    _clear_legacy_startup = _App._clear_legacy_startup
    _registered_startup_command = _App._registered_startup_command
    _check_stale_startup_entry = _App._check_stale_startup_entry
    _startup_command = classmethod(_App._startup_command.__func__)
    _startup_target = staticmethod(_App._startup_target)
    _STARTUP_RUN_KEY = _App._STARTUP_RUN_KEY
    _STARTUP_VALUE = _App._STARTUP_VALUE
    _LEGACY_STARTUP_VALUE = _App._LEGACY_STARTUP_VALUE
    _LEGACY_LNK_NAMES = _App._LEGACY_LNK_NAMES

    def __init__(self, enabled=True, startup_folder=None):
        self._startup_var = _MutableVar(enabled)
        self._sound_volume = 100
        self.status_calls = []
        self._folder = startup_folder

    def _startup_folder(self):
        return self._folder if self._folder is not None else Path("/nonexistent")

    def _play_checkbox(self):
        pass

    def _set_status(self, text, color=None):
        self.status_calls.append(text)


@pytest.fixture
def fake_reg(monkeypatch):
    reg = _FakeRegistry()
    monkeypatch.setattr(gui_mod, "winreg", reg)
    return reg


def test_enabling_startup_writes_a_run_value(fake_reg):
    host = _StartupHost()
    host._enable_startup()
    assert fake_reg.values[(_RUN_KEY, "Plunder")] == host._startup_command()


def test_the_startup_command_asks_for_the_tray(fake_reg):
    assert _StartupHost._startup_command().endswith("--tray")


def test_a_dev_run_names_the_script_host_explicitly(fake_reg):
    """Run values go through CreateProcess, which cannot start a .vbs on its
    own the way a shortcut's file association could."""
    cmd = _StartupHost._startup_command()
    assert cmd.startswith("wscript.exe ")
    assert cmd.split('"')[1].endswith("run.vbs")


def test_disabling_startup_removes_the_run_value(fake_reg):
    host = _StartupHost()
    host._enable_startup()
    host._disable_startup()
    assert (_RUN_KEY, "Plunder") not in fake_reg.values


def test_disabling_startup_when_it_was_never_on_is_not_an_error(fake_reg):
    _StartupHost()._disable_startup()   # must not raise


def test_disabling_startup_also_clears_the_pre_rename_value(fake_reg):
    """Otherwise the app keeps starting itself under its old name."""
    fake_reg.values[(_RUN_KEY, "Hoarder")] = r'"C:\old\Hoarder.exe" --tray'
    host = _StartupHost()
    host._disable_startup()
    assert (_RUN_KEY, "Hoarder") not in fake_reg.values


def test_disabling_startup_deletes_the_old_startup_folder_shortcuts(tmp_path, fake_reg):
    lnk = tmp_path / "Plunder.lnk"
    old = tmp_path / "Hoarder.lnk"
    lnk.write_bytes(b"shortcut")
    old.write_bytes(b"shortcut")

    _StartupHost(startup_folder=tmp_path)._disable_startup()

    assert not lnk.exists()
    assert not old.exists()


def test_a_stale_run_value_is_repointed_at_this_build(fake_reg):
    """The command is a snapshot of sys.executable from when the box was
    ticked; rebuilding elsewhere leaves Windows launching nothing."""
    fake_reg.values[(_RUN_KEY, "Plunder")] = r'"C:\somewhere\else\Plunder.exe" --tray'
    host = _StartupHost(enabled=True)
    host._check_stale_startup_entry()
    assert fake_reg.values[(_RUN_KEY, "Plunder")] == host._startup_command()


def test_a_current_run_value_is_left_alone(fake_reg):
    host = _StartupHost(enabled=True)
    host._enable_startup()
    before = dict(fake_reg.values)
    host._check_stale_startup_entry()
    assert fake_reg.values == before


def test_nothing_is_registered_when_the_setting_is_off(fake_reg):
    _StartupHost(enabled=False)._check_stale_startup_entry()
    assert fake_reg.values == {}


def test_a_refused_registry_write_reverts_the_checkbox(fake_reg, monkeypatch):
    """What the PowerShell version did instead was raise out of __init__."""
    monkeypatch.setattr(
        gui_mod, "winreg",
        _FakeRegistry(create_raises=PermissionError("[WinError 5] Access is denied")),
    )
    host = _StartupHost(enabled=True)
    host._on_startup_toggle()
    assert host._startup_var.get() is False
    assert any("Windows Startup error" in s for s in host.status_calls)


def test_the_startup_check_never_spawns_a_process(fake_reg, monkeypatch):
    """A blocked spawn is what crashed the app at launch — there is now
    nothing here for Windows to refuse."""
    import subprocess

    def _boom(*a, **k):
        raise AssertionError("startup registration must not spawn a process")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    host = _StartupHost(enabled=True)
    host._check_stale_startup_entry()
    host._disable_startup()


def test_the_gui_module_spawns_no_processes_at_all():
    """The two startup helpers were the only subprocess users in gui.py.

    Keeping it at zero is the point: an unsigned executable that launches
    PowerShell is a textbook malware signature, and a refused spawn is what
    crashed the app at startup. Conversions go through converter.py, torrent
    transfers through torrent_downloader.py — neither belongs here.
    """
    import ast

    source = Path(gui_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    spawns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name.split(".")[-1] in {"run", "Popen", "call", "check_output",
                                       "system", "startfile", "execv", "spawnv"}:
                if "subprocess" in name or name.startswith("os."):
                    spawns.append(name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", None) or ""
            names = [a.name for a in node.names]
            if mod == "subprocess" or "subprocess" in names:
                spawns.append(f"import {mod or names}")
    assert spawns == []


class _TorrentAssocHost:
    _on_torrent_ext_handler_toggle = _App._on_torrent_ext_handler_toggle
    _maybe_prompt_torrent_association = _App._maybe_prompt_torrent_association

    def __init__(self, register_raises=None, already_registered=False):
        self._torrent_ext_var = _MutableVar(False)
        self._torrent_ext_asked = False
        self._sound_volume = 100
        self._register_raises = register_raises
        self._already_registered = already_registered
        self.status_calls = []
        self.save_calls = 0
        self.register_calls = 0
        self.unregister_calls = 0
        self.prompt_shown = False

    def _play_checkbox(self):
        pass

    def _set_status(self, text, color=None):
        self.status_calls.append(text)

    def _save_settings(self):
        self.save_calls += 1

    def _register_torrent_ext_handler(self):
        self.register_calls += 1
        if self._register_raises:
            raise self._register_raises

    def _unregister_torrent_ext_handler(self):
        self.unregister_calls += 1

    def _is_torrent_ext_handler_registered(self):
        return self._already_registered

    def _show_torrent_association_prompt(self):
        self.prompt_shown = True


def test_torrent_ext_toggle_on_registers_and_marks_asked():
    host = _TorrentAssocHost()
    host._torrent_ext_var.set(True)
    host._on_torrent_ext_handler_toggle()
    assert host.register_calls == 1
    assert host.unregister_calls == 0
    assert host._torrent_ext_asked is True
    assert host.save_calls == 1


def test_torrent_ext_toggle_off_unregisters():
    host = _TorrentAssocHost()
    host._torrent_ext_var.set(False)
    host._on_torrent_ext_handler_toggle()
    assert host.unregister_calls == 1
    assert host.register_calls == 0


def test_torrent_ext_toggle_register_error_reverts_checkbox():
    host = _TorrentAssocHost(register_raises=OSError("permission denied"))
    host._torrent_ext_var.set(True)
    host._on_torrent_ext_handler_toggle()
    assert host._torrent_ext_var.get() is False
    assert any("error" in msg.lower() for msg in host.status_calls)
    # Still marked asked/saved — a failed attempt shouldn't nag again.
    assert host._torrent_ext_asked is True


def test_maybe_prompt_skips_if_already_asked():
    host = _TorrentAssocHost(already_registered=False)
    host._torrent_ext_asked = True
    host._maybe_prompt_torrent_association()
    assert host.prompt_shown is False


def test_maybe_prompt_skips_if_already_registered():
    host = _TorrentAssocHost(already_registered=True)
    host._torrent_ext_asked = False
    host._maybe_prompt_torrent_association()
    assert host.prompt_shown is False


import sys

# --- stale magnet/.torrent handler repair ---
#
# Same split as above: the registry writes stay untested, the decision of
# *whether* to rewrite is what's covered. The host stubs the two registry
# reads (_registered_command, _is_*_registered) so no HKCU state is touched.

def test_command_target_parses_quoted_exe():
    cmd = '"C:\\Program Files\\Plunder\\Plunder.exe" --magnet "%1"'
    assert _App._command_target(cmd) == Path("C:\\Program Files\\Plunder\\Plunder.exe")


def test_command_target_parses_unquoted_exe():
    assert _App._command_target('C:\\tools\\p.exe --magnet "%1"') == Path("C:\\tools\\p.exe")


def test_command_target_handles_missing_command():
    assert _App._command_target(None) is None
    assert _App._command_target("") is None


class _StaleHandlerHost:
    _check_stale_handlers = _App._check_stale_handlers
    _command_target = staticmethod(_App._command_target)
    _MAGNET_CMD_KEY = _App._MAGNET_CMD_KEY
    _TORRENT_PROGID = _App._TORRENT_PROGID

    def __init__(self, recorded, current, registered=True):
        self._recorded = recorded
        self._current = current
        self._registered = registered
        self.magnet_registrations = 0
        self.torrent_registrations = 0

    def _registered_command(self, subkey):
        return self._recorded

    def _is_magnet_handler_registered(self):
        return self._registered

    def _is_torrent_ext_handler_registered(self):
        return False

    def _magnet_handler_exe_cmd(self):
        return self._current

    def _torrent_ext_handler_exe_cmd(self):
        return self._current

    def _register_magnet_handler(self):
        self.magnet_registrations += 1

    def _register_torrent_ext_handler(self):
        self.torrent_registrations += 1


_GONE = '"C:\\nope\\gone\\Hoarder.exe" --magnet "%1"'
_HERE = '"C:\\Program Files\\Plunder\\Plunder.exe" --magnet "%1"'


def test_stale_handler_rewritten_when_recorded_exe_is_gone():
    host = _StaleHandlerHost(recorded=_GONE, current=_HERE)
    host._check_stale_handlers()
    assert host.magnet_registrations == 1


def test_matching_handler_is_left_alone():
    host = _StaleHandlerHost(recorded=_HERE, current=_HERE)
    host._check_stale_handlers()
    assert host.magnet_registrations == 0


def test_unregistered_handler_is_not_resurrected():
    host = _StaleHandlerHost(recorded=_GONE, current=_HERE, registered=False)
    host._check_stale_handlers()
    assert host.magnet_registrations == 0


def test_dev_run_does_not_steal_a_working_registration(monkeypatch, tmp_path):
    """A live installed exe keeps the association when python main.py runs."""
    installed = tmp_path / "Plunder.exe"
    installed.write_text("")
    monkeypatch.delattr(sys, "frozen", raising=False)
    host = _StaleHandlerHost(
        recorded=f'"{installed}" --magnet "%1"',
        current='"C:\\Python\\python.exe" "main.py" --magnet "%1"',
    )
    host._check_stale_handlers()
    assert host.magnet_registrations == 0


def test_frozen_build_reclaims_a_live_but_different_registration(monkeypatch, tmp_path):
    other = tmp_path / "OldBuild.exe"
    other.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    host = _StaleHandlerHost(recorded=f'"{other}" --magnet "%1"', current=_HERE)
    host._check_stale_handlers()
    assert host.magnet_registrations == 1


# --- active-downloads slider ---

from gui import dl_count_to_fraction, dl_fraction_to_count, DL_SLIDER_STEPS


def test_slider_has_one_stop_per_allowed_value():
    """20 values means 19 gaps — every drag position lands on a whole
    number of downloads, with nothing in between to stop on."""
    assert DL_SLIDER_STEPS == 19
    stops = {dl_fraction_to_count(i / DL_SLIDER_STEPS) for i in range(DL_SLIDER_STEPS + 1)}
    assert stops == set(range(1, 21))


def test_count_fraction_round_trip():
    for n in range(1, 21):
        assert dl_fraction_to_count(dl_count_to_fraction(n)) == n


def test_slider_ends_map_to_the_limits():
    assert dl_fraction_to_count(0.0) == 1
    assert dl_fraction_to_count(1.0) == 20
    assert dl_count_to_fraction(1) == 0.0
    assert dl_count_to_fraction(20) == 1.0


def test_default_of_five_sits_where_it_should():
    assert dl_fraction_to_count(dl_count_to_fraction(5)) == 5
    assert 0.2 < dl_count_to_fraction(5) < 0.25


def test_out_of_range_values_are_clamped_not_dropped():
    assert dl_count_to_fraction(0) == dl_count_to_fraction(1)
    assert dl_count_to_fraction(500) == dl_count_to_fraction(20)


# --- queue de-duplication ---
#
# The startup folder scan and a resumed session can both offer the same file.
# Encoding it twice would race two ffmpeg runs onto one output path, and the
# library cannot catch it — it only records what has already finished.

class _DedupeHost:
    _enqueue_conversion = _App._enqueue_conversion
    _already_queued = _App._already_queued
    _ignore_key = staticmethod(_App._ignore_key)

    def __init__(self):
        self._conversion_queue = []
        self._active_batch = None
        self.added_rows = []

    def after(self, _delay, fn, *args):
        fn(*args)

    def _add_encoding_progress(self, task_id, name):
        self.added_rows.append(task_id)

    def _save_session(self):
        pass

    def _process_next_queue_item(self):
        pass


def test_the_same_batch_offered_twice_is_queued_once(tmp_path):
    f = tmp_path / "01.flac"
    f.write_bytes(b"a")
    host = _DedupeHost()
    host._enqueue_conversion([str(f)])
    host._enqueue_conversion([str(f)])
    assert host._conversion_queue == [[str(f)]]
    assert host.added_rows == [str(f)]


def test_a_batch_overlapping_the_one_in_flight_is_skipped(tmp_path):
    f = tmp_path / "01.flac"
    f.write_bytes(b"a")
    host = _DedupeHost()
    host._active_batch = [str(f)]        # popped off the queue, mid-encode
    host._enqueue_conversion([str(f)])
    assert host._conversion_queue == []


def test_enqueue_reports_whether_it_took_the_batch(tmp_path):
    f = tmp_path / "01.flac"
    f.write_bytes(b"a")
    host = _DedupeHost()
    assert host._enqueue_conversion([str(f)]) is True
    assert host._enqueue_conversion([str(f)]) is False       # duplicate
    assert host._enqueue_conversion([str(tmp_path / "x.txt")]) is False  # rejected


def test_different_files_still_queue_normally(tmp_path):
    f1, f2 = tmp_path / "01.flac", tmp_path / "02.flac"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")
    host = _DedupeHost()
    host._enqueue_conversion([str(f1)])
    host._enqueue_conversion([str(f2)])
    assert host._conversion_queue == [[str(f1)], [str(f2)]]


def test_dedupe_ignores_path_spelling(tmp_path):
    """The watcher and a session record can spell the same file differently."""
    f = tmp_path / "01.flac"
    f.write_bytes(b"a")
    host = _DedupeHost()
    host._enqueue_conversion([str(f)])
    host._enqueue_conversion([str(tmp_path / "." / "01.flac")])
    assert host._conversion_queue == [[str(f)]]


# --- resuming unfinished work ---

class _ResumeHost:
    _restore_session = _App._restore_session
    _resume_downloads = _App._resume_downloads
    _resume_encodes = _App._resume_encodes
    _discard_partial_outputs = _App._discard_partial_outputs
    _encode_snapshot = _App._encode_snapshot
    _audio_outputs = staticmethod(_App._audio_outputs)
    _video_outputs = staticmethod(_App._video_outputs)

    def __init__(self, downloader=None):
        self._torrent_downloader = downloader
        self._conversion_queue = []
        self._active_batch = None
        self._is_converting = False
        self._unresumed_downloads = []
        self.enqueued = []
        self.infos = []
        self.swept = 0

    def _sweep_staged_torrents(self):
        self.swept += 1

    def _enqueue_conversion(self, paths):
        self.enqueued.append(list(paths))
        self._conversion_queue.append(list(paths))
        return True

    def _save_session(self):
        pass

    def _set_info(self, text, color=None):
        self.infos.append(text)


class _FakeDownloader:
    def __init__(self, accept=True):
        self.added = []
        self.resume_flags = []
        self._accept = accept

    def add(self, target, resume=False):
        self.added.append(target)
        self.resume_flags.append(resume)
        return "tid" if self._accept else None


def test_magnet_downloads_are_resumed():
    dl = _FakeDownloader()
    host = _ResumeHost(dl)
    n = host._resume_downloads([
        {"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"},
        {"tid": "b", "target": "magnet:?xt=urn:btih:2", "name": "Two"},
    ])
    assert n == 2
    assert dl.added == ["magnet:?xt=urn:btih:1", "magnet:?xt=urn:btih:2"]


def test_a_torrent_whose_staged_copy_is_gone_is_skipped(tmp_path):
    """%TEMP% may have been swept since — there is nothing left to resume from."""
    live = tmp_path / "still-here.torrent"
    live.write_bytes(b"d4:infod4:name5:Movieee")
    dl = _FakeDownloader()
    host = _ResumeHost(dl)
    n = host._resume_downloads([
        {"tid": "a", "target": str(tmp_path / "swept-away.torrent"), "name": "Gone"},
        {"tid": "b", "target": str(live), "name": "Here"},
    ])
    assert n == 1
    assert dl.added == [str(live)]


def test_resumed_downloads_are_flagged_as_resumes():
    """aria2c only hash-checks the partial data already in staging when it is
    told this is a resume; without that a stale or missing control file means
    the transfer starts again from zero."""
    dl = _FakeDownloader()
    host = _ResumeHost(dl)
    host._resume_downloads([
        {"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"},
    ])
    assert dl.resume_flags == [True]


def test_downloads_are_not_resumed_without_a_downloader():
    host = _ResumeHost(downloader=None)
    assert host._resume_downloads([
        {"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"},
    ]) == 0


def test_records_a_restore_cannot_act_on_are_carried_forward():
    """Starting once with torrents disabled must not erase the record of a
    part-finished download — its data is still sitting in staging."""
    records = [{"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"}]
    host = _ResumeHost(downloader=None)
    host._resume_downloads(records)
    assert host._unresumed_downloads == records


def test_a_resumed_record_is_not_also_carried_forward():
    """It is live in the downloader now, so the snapshot covers it — keeping
    it here as well would write the same transfer out twice."""
    host = _ResumeHost(_FakeDownloader())
    host._resume_downloads([
        {"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"},
    ])
    assert host._unresumed_downloads == []


def test_a_torrent_whose_staged_copy_is_gone_is_dropped_for_good(tmp_path):
    """There is nothing left to start it from, ever. Keeping the record would
    pin its staging folder in place forever, so an orphaned aria2c that did
    finish it could never be recovered either."""
    host = _ResumeHost(_FakeDownloader())
    host._resume_downloads([
        {"tid": "a", "target": str(tmp_path / "swept.torrent"), "name": "Gone"},
    ])
    assert host._unresumed_downloads == []


def test_a_download_the_backend_rejects_is_not_counted():
    dl = _FakeDownloader(accept=False)
    host = _ResumeHost(dl)
    assert host._resume_downloads([
        {"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"},
    ]) == 0


def test_interrupted_encodes_are_requeued(tmp_path):
    f1, f2 = tmp_path / "01.flac", tmp_path / "02.flac"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")
    host = _ResumeHost()
    n = host._resume_encodes([{"paths": [str(f1)]}, {"paths": [str(f2)]}])
    assert n == 2
    assert host.enqueued == [[str(f1)], [str(f2)]]


def test_encode_records_for_deleted_files_are_dropped(tmp_path):
    """Delete-after-conversion may already have removed the sources."""
    host = _ResumeHost()
    assert host._resume_encodes([{"paths": [str(tmp_path / "gone.flac")]}]) == 0
    assert host.enqueued == []


def test_the_interrupted_batch_loses_its_half_written_output(tmp_path):
    """A truncated .mp3 is indistinguishable from a finished one by name, so
    the rerun must not find one waiting."""
    src = tmp_path / "01.flac"
    src.write_bytes(b"a")
    partial = tmp_path / "01.mp3"
    partial.write_bytes(b"half an encode")

    host = _ResumeHost()
    host._resume_encodes([{"paths": [str(src)]}])
    assert not partial.exists()
    assert src.exists()          # the source is what the rerun needs


def test_queued_but_never_started_batches_keep_their_files(tmp_path):
    """Only the first record was mid-encode; the rest never ran, so an mp3
    sitting beside them is somebody else's finished work."""
    started, queued = tmp_path / "01.flac", tmp_path / "02.flac"
    started.write_bytes(b"a")
    queued.write_bytes(b"b")
    (tmp_path / "01.mp3").write_bytes(b"partial")
    untouched = tmp_path / "02.mp3"
    untouched.write_bytes(b"finished earlier")

    host = _ResumeHost()
    host._resume_encodes([{"paths": [str(started)]}, {"paths": [str(queued)]}])
    assert untouched.read_bytes() == b"finished earlier"


def test_encode_snapshot_puts_the_batch_in_flight_first(tmp_path):
    host = _ResumeHost()
    host._active_batch = ["/a/01.flac"]
    host._conversion_queue = [["/b/02.flac"], ["/c/03.flac"]]
    assert host._encode_snapshot() == [
        {"paths": ["/a/01.flac"]},
        {"paths": ["/b/02.flac"]},
        {"paths": ["/c/03.flac"]},
    ]


def test_encode_snapshot_is_empty_when_idle():
    assert _ResumeHost()._encode_snapshot() == []


def test_restore_reports_what_it_picked_up(tmp_path, monkeypatch):
    import session as sess
    f = tmp_path / "01.flac"
    f.write_bytes(b"a")
    monkeypatch.setattr(sess, "load", lambda: {
        "downloads": [{"tid": "a", "target": "magnet:?xt=urn:btih:1", "name": "One"}],
        "encodes": [{"paths": [str(f)]}],
    })
    host = _ResumeHost(_FakeDownloader())
    host._restore_session()
    assert host.infos == ["Resumed 1 download and 1 encode"]


def test_restore_says_nothing_when_there_was_nothing_to_resume(monkeypatch):
    import session as sess
    monkeypatch.setattr(sess, "load", lambda: {"downloads": [], "encodes": []})
    host = _ResumeHost(_FakeDownloader())
    host._restore_session()
    assert host.infos == []


def test_maybe_prompt_shows_when_neither_asked_nor_registered():
    host = _TorrentAssocHost(already_registered=False)
    host._torrent_ext_asked = False
    host._maybe_prompt_torrent_association()
    assert host.prompt_shown is True


# --- progress bar geometry ---

from gui import PixelBar, BAR_W


def test_bar_fill_spans_the_track_between_the_borders():
    assert PixelBar._fill_px(0.0, BAR_W) == 0
    assert PixelBar._fill_px(1.0, BAR_W) == BAR_W - 2
    assert PixelBar._fill_px(0.5, BAR_W) == (BAR_W - 2) // 2


def test_bar_fill_clamps_out_of_range_values():
    assert PixelBar._fill_px(-0.5, BAR_W) == 0
    assert PixelBar._fill_px(4.0, BAR_W) == BAR_W - 2


def test_bar_fill_is_monotonic():
    widths = [PixelBar._fill_px(i / 100, BAR_W) for i in range(101)]
    assert widths == sorted(widths)


# --- slider snapping ---
#
# _value_from_event only reads _bar_w and _steps off the widget, so it can be
# exercised on a stand-in rather than a real Tk canvas.

from gui import PixelSlider


class _Track:
    def __init__(self, steps):
        self._bar_w = BAR_W
        self._steps = steps


def _at(steps, x):
    return PixelSlider._value_from_event(_Track(steps), types.SimpleNamespace(x=x))


def test_a_drag_lands_on_a_whole_number_of_downloads():
    """Anywhere the user lets go, the value is one of the 20 allowed."""
    for x in range(0, BAR_W + 20, 3):
        assert dl_fraction_to_count(_at(DL_SLIDER_STEPS, x)) in range(1, 21)


def test_dragging_past_either_end_clamps():
    assert _at(DL_SLIDER_STEPS, -50) == 0.0
    assert _at(DL_SLIDER_STEPS, BAR_W + 50) == 1.0


def test_the_track_covers_every_value_from_one_to_twenty():
    seen = {dl_fraction_to_count(_at(DL_SLIDER_STEPS, x)) for x in range(BAR_W + 1)}
    assert seen == set(range(1, 21))


def test_the_volume_slider_keeps_its_ten_percent_detents():
    assert _at(10, 1) == 0.0
    assert _at(10, BAR_W - 1) == 1.0
    assert all(round(_at(10, x) * 10, 6).is_integer() for x in range(BAR_W))


# --- conversion outputs (what gets recorded in the library) ---

def test_conversion_outputs_for_plain_audio(tmp_path):
    src = str(tmp_path / "track.flac")
    outputs = App._conversion_outputs([src], None, [])
    assert outputs == [str(tmp_path / "track.mp3")]


def test_conversion_outputs_include_video_transcodes(tmp_path):
    vid = str(tmp_path / "movie.mkv")
    assert App._conversion_outputs([], None, [vid]) == [str(tmp_path / "movie.mp4")]


def test_conversion_outputs_for_mp4_source_avoids_overwrite(tmp_path):
    vid = str(tmp_path / "movie.mp4")
    assert App._conversion_outputs([], None, [vid]) == [
        str(tmp_path / "movie.hevc.mp4")
    ]
