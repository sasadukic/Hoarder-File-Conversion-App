import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import os
import json
import tempfile

from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs, delete_companion_files
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


# --- probe_video ---

from converter import probe_video

def test_probe_video_returns_codec_duration_size():
    fake_output = json.dumps({
        "streams": [
            {"codec_type": "audio", "codec_name": "aac"},
            {"codec_type": "video", "codec_name": "h264"},
        ],
        "format": {
            "duration": "120.5",
            "size": "50000000",
        }
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_output

    with patch("converter.subprocess.run", return_value=mock_result):
        info = probe_video("/m/video.mp4")

    assert info["codec"] == "h264"
    assert info["duration"] == pytest.approx(120.5)
    assert info["size"] == 50_000_000

def test_probe_video_hevc_codec():
    fake_output = json.dumps({
        "streams": [{"codec_type": "video", "codec_name": "hevc"}],
        "format": {"duration": "60.0", "size": "20000000"},
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_output

    with patch("converter.subprocess.run", return_value=mock_result):
        info = probe_video("/m/video.mp4")

    assert info["codec"] == "hevc"

def test_probe_video_raises_on_ffprobe_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "no such file"

    with patch("converter.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="ffprobe failed"):
            probe_video("/m/missing.mp4")


# --- transcode_videos ---

from converter import transcode_videos

def _make_probe(codec="h264", duration=120.0, size=50_000_000):
    return {"codec": codec, "duration": duration, "size": size}

def test_transcode_skips_hevc_mp4(tmp_path):
    """Already H.265 MP4 must be skipped — ffmpeg never called."""
    video = tmp_path / "already.mp4"
    video.touch()
    progress_calls = []

    with patch("converter.probe_video", return_value=_make_probe(codec="hevc")):
        with patch("converter.subprocess.run") as mock_run:
            transcode_videos(
                [str(video)],
                lambda cur, total: progress_calls.append((cur, total)),
                delete_source=False,
                encoder="libx265",
            )

    mock_run.assert_not_called()
    assert progress_calls == [(1, 1)]

def test_transcode_skips_when_predicted_larger(tmp_path):
    """Sample output is larger than source — skip full transcode."""
    video = tmp_path / "big.mkv"
    video.write_bytes(b"x" * 10_000_000)  # 10 MB source

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        if "-t" in cmd:
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"x" * 12_000_000)  # > source
        return mock_ok

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=10_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run) as mock_run:
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=False,
                encoder="libx265",
            )

    full_transcode_calls = [c for c in mock_run.call_args_list if "-t" not in c[0][0]]
    assert len(full_transcode_calls) == 0

def test_transcode_runs_full_when_sample_passes(tmp_path):
    """Sample output is smaller — full transcode runs, output file is created."""
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"x" * 50_000_000)  # 50 MB source
    out_path = tmp_path / "movie.mp4"

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        out = Path(cmd[-1])
        out.write_bytes(b"x" * 1_000_000)   # small sample = will pass
        return mock_ok

    def fake_full(cmd, duration, on_pct, error_prefix):
        Path(cmd[-1]).write_bytes(b"x" * 20_000_000)

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=False,
                encoder="libx265",
                _run_full_fn=fake_full,
            )

    assert out_path.exists()

def test_transcode_deletes_source_when_flag_set(tmp_path):
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"x" * 50_000_000)

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"x" * 1_000_000)
        return mock_ok

    def fake_full(cmd, duration, on_pct, error_prefix):
        Path(cmd[-1]).write_bytes(b"x" * 20_000_000)

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=True,
                encoder="libx265",
                _run_full_fn=fake_full,
            )

    assert not video.exists()

def test_transcode_mp4_source_gets_hevc_suffix(tmp_path):
    """MP4 source → output is <stem>.hevc.mp4 to avoid collision."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 50_000_000)
    expected_out = tmp_path / "clip.hevc.mp4"

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"x" * 1_000_000)
        return mock_ok

    def fake_full(cmd, duration, on_pct, error_prefix):
        Path(cmd[-1]).write_bytes(b"x" * 20_000_000)

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=False,
                encoder="libx265",
                _run_full_fn=fake_full,
            )

    assert expected_out.exists()


def test_transcode_progress_called_after_work(tmp_path):
    """Progress callback must be called AFTER both sample and full ffmpeg work."""
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"x" * 50_000_000)

    mock_ok = MagicMock()
    mock_ok.returncode = 0
    call_order = []

    def fake_run(cmd, **kwargs):
        out = Path(cmd[-1])
        call_order.append("ffmpeg_sample")
        out.write_bytes(b"x" * 1_000_000)
        return mock_ok

    def fake_full(cmd, duration, on_pct, error_prefix):
        call_order.append("ffmpeg_full")
        Path(cmd[-1]).write_bytes(b"x" * 20_000_000)

    def on_progress(cur, total):
        call_order.append("progress")

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)], on_progress, encoder="libx265",
                _run_full_fn=fake_full,
            )

    # sample ffmpeg → full ffmpeg → progress; never progress first
    assert call_order == ["ffmpeg_sample", "ffmpeg_full", "progress"]


# --- encoder detection ---

from converter import _detect_hevc_encoder

def test_detect_hevc_encoder_prefers_nvenc():
    mock_ok = MagicMock()
    mock_ok.returncode = 0
    with patch("converter.subprocess.run", return_value=mock_ok):
        assert _detect_hevc_encoder() == "hevc_nvenc"

def test_detect_hevc_encoder_falls_back_to_libx265():
    mock_fail = MagicMock()
    mock_fail.returncode = 1
    with patch("converter.subprocess.run", return_value=mock_fail):
        assert _detect_hevc_encoder() == "libx265"


# --- _run_ffmpeg_progress ---

from converter import _run_ffmpeg_progress


def _make_mock_proc(stdout_lines, stderr_lines=None, returncode=0):
    """Build a mock Popen process with iterable stdout/stderr."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.stderr = iter(stderr_lines or [])
    mock_proc.wait.return_value = None
    return mock_proc


def test_run_ffmpeg_progress_injects_progress_flags():
    """Must inject -progress pipe:1 -nostats before the output argument."""
    captured_cmds = []

    def fake_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        return _make_mock_proc([])

    with patch("converter.subprocess.Popen", side_effect=fake_popen):
        _run_ffmpeg_progress(
            ["ffmpeg", "-i", "in.mp4", "out.mp4"],
            60.0,
            lambda pct: None,
            "err",
        )

    cmd = captured_cmds[0]
    assert "-progress" in cmd
    assert "pipe:1" in cmd
    assert "-nostats" in cmd
    assert cmd[-1] == "out.mp4"


def test_run_ffmpeg_progress_calls_on_pct():
    """on_pct should be called with fractions parsed from out_time_us lines."""
    stdout_lines = [
        "frame=10\n",
        "out_time_us=30000000\n",   # 30 / 120 = 0.25
        "out_time_us=60000000\n",   # 60 / 120 = 0.5
        "progress=end\n",
    ]
    pct_calls = []

    with patch("converter.subprocess.Popen", return_value=_make_mock_proc(stdout_lines)):
        _run_ffmpeg_progress(
            ["ffmpeg", "-i", "in.mp4", "out.mp4"],
            120.0,
            lambda pct: pct_calls.append(pct),
            "test error",
        )

    assert len(pct_calls) == 2
    assert pct_calls[0] == pytest.approx(0.25)
    assert pct_calls[1] == pytest.approx(0.5)


def test_run_ffmpeg_progress_raises_on_failure():
    """Non-zero returncode must raise RuntimeError with the given prefix."""
    mock_proc = _make_mock_proc([], ["ffmpeg error details\n"], returncode=1)

    with patch("converter.subprocess.Popen", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="test error"):
            _run_ffmpeg_progress(
                ["ffmpeg", "-i", "in.mp4", "out.mp4"],
                60.0,
                lambda pct: None,
                "test error",
            )


# --- delete_companion_files ---

def test_delete_companion_files_removes_cue_and_log(tmp_path):
    flac = tmp_path / "album.flac"
    cue  = tmp_path / "album.cue"
    log  = tmp_path / "album.log"
    m3u  = tmp_path / "album.m3u"
    txt  = tmp_path / "album.txt"
    flac.touch(); cue.touch(); log.touch(); m3u.touch(); txt.touch()

    delete_companion_files([str(flac)], cue_path=str(cue))

    assert not cue.exists()
    assert not log.exists()
    assert not m3u.exists()
    assert not txt.exists()
    assert flac.exists()  # only companions removed, not the audio file itself


def test_delete_companion_files_no_cue_path(tmp_path):
    flac       = tmp_path / "track.flac"
    track_log  = tmp_path / "track.log"    # same stem — deleted by stem match
    track_m3u  = tmp_path / "track.m3u"   # same stem — deleted
    track_txt  = tmp_path / "track.txt"   # same stem — deleted
    disc_cue   = tmp_path / "disc.cue"    # .cue files never swept — preserved
    disc_log   = tmp_path / "disc.log"    # orphaned (no disc.flac) — deleted
    disc_m3u   = tmp_path / "disc.m3u"   # orphaned — deleted
    disc_txt   = tmp_path / "disc.txt"   # orphaned — deleted
    for f in (flac, track_log, track_m3u, track_txt, disc_cue, disc_log, disc_m3u, disc_txt):
        f.touch()

    delete_companion_files([str(flac)])  # no explicit cue_path

    assert not track_log.exists()   # same-stem log removed
    assert not track_m3u.exists()   # same-stem m3u removed
    assert not track_txt.exists()   # same-stem txt removed
    assert disc_cue.exists()        # .cue not swept
    assert not disc_log.exists()    # orphaned log removed
    assert not disc_m3u.exists()    # orphaned m3u removed
    assert not disc_txt.exists()    # orphaned txt removed


def test_delete_companion_files_missing_files_ok(tmp_path):
    flac = tmp_path / "track.flac"
    flac.touch()
    # Should not raise even if there are no .cue / .log files
    delete_companion_files([str(flac)], cue_path=str(tmp_path / "nope.cue"))


def test_delete_companion_files_multiple_dirs(tmp_path):
    d1 = tmp_path / "dir1"; d1.mkdir()
    d2 = tmp_path / "dir2"; d2.mkdir()
    for d in (d1, d2):
        (d / "track.flac").touch()
        (d / "track.cue").touch()
        (d / "track.log").touch()   # same stem — deleted
        (d / "track.m3u").touch()   # same stem — deleted
        (d / "track.txt").touch()   # same stem — deleted
        (d / "other.log").touch()   # orphaned (no other.flac) — deleted
        (d / "other.m3u").touch()   # orphaned — deleted
        (d / "other.txt").touch()   # orphaned — deleted

    # Only d1's CUE is passed explicitly; d2's CUE should be left untouched
    delete_companion_files(
        [str(d1 / "track.flac"), str(d2 / "track.flac")],
        cue_path=str(d1 / "track.cue"),
    )

    assert not (d1 / "track.cue").exists()   # explicit cue_path deleted
    assert (d2 / "track.cue").exists()       # d2's CUE not touched
    assert not (d1 / "track.log").exists()
    assert not (d2 / "track.log").exists()
    assert not (d1 / "track.m3u").exists()
    assert not (d2 / "track.m3u").exists()
    assert not (d1 / "track.txt").exists()
    assert not (d2 / "track.txt").exists()
    assert not (d1 / "other.log").exists()
    assert not (d2 / "other.log").exists()
    assert not (d1 / "other.m3u").exists()
    assert not (d2 / "other.m3u").exists()
    assert not (d1 / "other.txt").exists()
    assert not (d2 / "other.txt").exists()


def test_delete_companion_files_preserves_sibling_disc_log(tmp_path):
    """Disc 2's .log must survive disc 1's cleanup while disc 2's .flac still exists."""
    disc2_flac = tmp_path / "Album - Disc 2.flac"   # still on disk — not yet processed
    disc2_log  = tmp_path / "Album - Disc 2.log"
    album_log  = tmp_path / "Album.log"              # orphaned — no Album.flac

    disc2_flac.touch(); disc2_log.touch(); album_log.touch()

    # Simulate state after delete_flacs ran for disc 1 (disc 1 FLAC already gone)
    delete_companion_files(
        [str(tmp_path / "Album - Disc 1.flac")],       # disc 1 FLAC path (already deleted)
        cue_path=str(tmp_path / "Album - Disc 1.cue"), # disc 1 CUE (already gone — no-op)
    )

    assert disc2_flac.exists()      # disc 2 FLAC untouched
    assert disc2_log.exists()       # disc 2 LOG preserved (its .flac still exists)
    assert not album_log.exists()   # orphaned album-level log cleaned up


def test_delete_companion_files_removes_m3u_and_txt(tmp_path):
    """Album-level .m3u and .txt are deleted alongside .log."""
    flac       = tmp_path / "Album.flac"
    album_m3u  = tmp_path / "Album.m3u"   # same stem as FLAC — deleted
    album_txt  = tmp_path / "Album.txt"   # same stem as FLAC — deleted
    loose_m3u  = tmp_path / "playlist.m3u"  # orphaned — deleted
    loose_txt  = tmp_path / "notes.txt"     # orphaned — deleted
    keep_cue   = tmp_path / "Album.cue"    # .cue never swept — preserved
    for f in (flac, album_m3u, album_txt, loose_m3u, loose_txt, keep_cue):
        f.touch()

    delete_companion_files([str(flac)])

    assert not album_m3u.exists()
    assert not album_txt.exists()
    assert not loose_m3u.exists()
    assert not loose_txt.exists()
    assert keep_cue.exists()
    assert flac.exists()


def test_delete_companion_files_preserves_m3u_txt_while_sibling_audio_exists(tmp_path):
    """m3u/txt with a matching sibling audio file are NOT deleted."""
    disc2_flac = tmp_path / "Album - Disc 2.flac"
    disc2_m3u  = tmp_path / "Album - Disc 2.m3u"
    disc2_txt  = tmp_path / "Album - Disc 2.txt"
    disc2_flac.touch(); disc2_m3u.touch(); disc2_txt.touch()

    delete_companion_files(
        [str(tmp_path / "Album - Disc 1.flac")],
    )

    assert disc2_flac.exists()
    assert disc2_m3u.exists()   # preserved — disc 2 FLAC still on disk
    assert disc2_txt.exists()   # preserved


# --- copy_to_finished ---

def test_copy_to_finished_creates_folder_and_copies(tmp_path):
    from converter import copy_to_finished
    src = tmp_path / "output.mp3"
    src.write_text("music")
    finished = tmp_path / "done"
    result = copy_to_finished([str(src)], str(finished))
    assert result is None
    assert (finished / "output.mp3").exists()
    assert (finished / "output.mp3").read_text() == "music"

def test_copy_to_finished_missing_file_skips_silently(tmp_path):
    from converter import copy_to_finished
    finished = tmp_path / "done"
    result = copy_to_finished([str(tmp_path / "missing.mp3")], str(finished))
    assert result is None

def test_copy_to_finished_multiple_files(tmp_path):
    from converter import copy_to_finished
    f1 = tmp_path / "a.mp3"
    f2 = tmp_path / "b.mp3"
    f1.write_text("a")
    f2.write_text("b")
    finished = tmp_path / "done"
    result = copy_to_finished([str(f1), str(f2)], str(finished))
    assert result is None
    assert (finished / "a.mp3").exists()
    assert (finished / "b.mp3").exists()
