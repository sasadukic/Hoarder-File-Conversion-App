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


# --- torrent completion: move out of staging, then convert ---

import types
import shutil as _shutil
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

    def __init__(self):
        self._conversion_queue = []
        self.added_rows = []
        self.queue_processed = False

    def after(self, _delay, fn, *args):
        fn(*args)

    def _add_encoding_progress(self, task_id, name):
        self.added_rows.append(task_id)

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


# --- staged-download recovery (orphaned aria2c child finished after
# Hoarder itself was closed/killed mid-download) ---

class _RecoveryHost:
    """Stand-in for _recover_staged_downloads: real methods, no Tk."""

    _recover_staged_downloads = _App._recover_staged_downloads
    _has_incomplete_download = staticmethod(_App._has_incomplete_download)
    _move_into_monitor_folder = staticmethod(_App._move_into_monitor_folder)

    def __init__(self):
        self.infos = []

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


def test_save_settings_writes_every_default_key(monkeypatch):
    import settings as smod
    captured = {}
    monkeypatch.setattr(smod, "save", lambda data: captured.update(data))

    host = _SaveSettingsHost()
    host._save_settings()

    assert set(captured.keys()) == set(smod._DEFAULTS.keys())


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
