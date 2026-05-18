import pytest
from gui import detect_mode, parse_drop_paths, MODE_SPLIT, MODE_CONVERT


# --- detect_mode ---

def test_detect_mode_split():
    mode, flacs, cue, err = detect_mode(["/m/album.flac", "/m/album.cue"])
    assert mode == MODE_SPLIT
    assert flacs == ["/m/album.flac"]
    assert cue == "/m/album.cue"
    assert err is None


def test_detect_mode_convert_single():
    mode, flacs, cue, err = detect_mode(["/m/track01.flac"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/track01.flac"]
    assert cue is None
    assert err is None


def test_detect_mode_convert_batch():
    paths = ["/m/t1.flac", "/m/t2.flac", "/m/t3.flac"]
    mode, flacs, cue, err = detect_mode(paths)
    assert mode == MODE_CONVERT
    assert len(flacs) == 3
    assert err is None


def test_detect_mode_cue_without_flac():
    mode, flacs, cue, err = detect_mode(["/m/album.cue"])
    assert mode is None
    assert "FLAC" in err


def test_detect_mode_unsupported_file():
    mode, flacs, cue, err = detect_mode(["/m/track.mp3"])
    assert mode is None
    assert "Unsupported" in err


def test_detect_mode_multiple_cues():
    mode, flacs, cue, err = detect_mode(["/m/a.flac", "/m/a.cue", "/m/b.cue"])
    assert mode is None
    assert "one CUE" in err or "CUE" in err


def test_detect_mode_cue_with_multiple_flacs():
    mode, flacs, cue, err = detect_mode(["/m/a.flac", "/m/b.flac", "/m/album.cue"])
    assert mode is None
    assert "one FLAC" in err or "CUE" in err


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
