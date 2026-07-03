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
