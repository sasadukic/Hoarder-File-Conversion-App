import pytest
from cue_parser import _cue_time_to_seconds, _sanitize_filename, parse_cue
import tempfile, os


def test_cue_time_basic():
    assert _cue_time_to_seconds("00:00:00") == pytest.approx(0.0)


def test_cue_time_minutes():
    assert _cue_time_to_seconds("01:23:00") == pytest.approx(83.0)


def test_cue_time_frames():
    # 75 frames = 1 second
    assert _cue_time_to_seconds("00:00:75") == pytest.approx(1.0)


def test_cue_time_frames_partial():
    assert _cue_time_to_seconds("00:01:37") == pytest.approx(1 + 37 / 75.0)


def test_cue_time_invalid():
    with pytest.raises(ValueError):
        _cue_time_to_seconds("01:23")


def test_sanitize_filename_removes_invalid_chars():
    assert _sanitize_filename('Song: Part/Two') == 'Song  Part Two'


def test_sanitize_filename_strips_whitespace():
    assert _sanitize_filename('  Hello  ') == 'Hello'


def test_sanitize_filename_all_invalid():
    assert _sanitize_filename('/\\:*?"<>|') == ''


def test_parse_cue_two_tracks():
    cue_content = '''\
PERFORMER "Artist"
TITLE "Album"
FILE "album.flac" WAVE
  TRACK 01 AUDIO
    TITLE "First Song"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second Song"
    INDEX 01 03:15:00
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cue',
                                     delete=False, encoding='utf-8') as f:
        f.write(cue_content)
        path = f.name
    try:
        tracks = parse_cue(path)
        assert len(tracks) == 2
        assert tracks[0].number == 1
        assert tracks[0].title == "First Song"
        assert tracks[0].start == pytest.approx(0.0)
        assert tracks[0].end == pytest.approx(195.0)  # 3*60+15
        assert tracks[1].number == 2
        assert tracks[1].title == "Second Song"
        assert tracks[1].start == pytest.approx(195.0)
        assert tracks[1].end is None
    finally:
        os.unlink(path)


def test_parse_cue_missing_title_uses_fallback():
    cue_content = '''\
FILE "album.flac" WAVE
  TRACK 01 AUDIO
    INDEX 01 00:00:00
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cue',
                                     delete=False, encoding='utf-8') as f:
        f.write(cue_content)
        path = f.name
    try:
        tracks = parse_cue(path)
        assert tracks[0].title == "Track 01"
    finally:
        os.unlink(path)


def test_parse_cue_empty_raises():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cue',
                                     delete=False, encoding='utf-8') as f:
        f.write("PERFORMER \"Nobody\"\n")
        path = f.name
    try:
        with pytest.raises(ValueError, match="No tracks found"):
            parse_cue(path)
    finally:
        os.unlink(path)
