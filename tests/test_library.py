import json

import pytest

import library as libmod


@pytest.fixture(autouse=True)
def temp_library(tmp_path, monkeypatch):
    """Point the library at a throwaway file for every test."""
    monkeypatch.setattr(libmod, "_LIBRARY_PATH", tmp_path / "library.json")
    return tmp_path / "library.json"


def _write(tmp_path, name, content=b"audio-bytes"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


# --- digest ---------------------------------------------------------------

def test_digest_matches_for_identical_content(tmp_path):
    a = _write(tmp_path, "a.flac")
    b = _write(tmp_path, "b.flac")
    assert libmod.digest(a) == libmod.digest(b)


def test_digest_differs_for_different_content(tmp_path):
    a = _write(tmp_path, "a.flac", b"one")
    b = _write(tmp_path, "b.flac", b"two")
    assert libmod.digest(a) != libmod.digest(b)


def test_digest_differs_when_only_size_differs(tmp_path, monkeypatch):
    """Size is folded in, so a truncated copy is not mistaken for the original."""
    monkeypatch.setattr(libmod, "_CHUNK", 4)
    a = _write(tmp_path, "a.flac", b"headtail")
    b = _write(tmp_path, "b.flac", b"head")
    assert libmod.digest(a) != libmod.digest(b)


def test_digest_of_missing_file_is_none(tmp_path):
    assert libmod.digest(str(tmp_path / "gone.flac")) is None


# --- load / save ----------------------------------------------------------

def test_load_missing_file_returns_empty():
    assert libmod.load() == {"done": {}, "stamps": {}}


def test_load_corrupt_file_returns_empty(temp_library):
    temp_library.write_text("not json")
    assert libmod.load() == {"done": {}, "stamps": {}}


def test_load_wrong_shape_returns_empty(temp_library):
    temp_library.write_text(json.dumps(["a", "b"]))
    assert libmod.load() == {"done": {}, "stamps": {}}


def test_save_is_atomic(tmp_path, temp_library):
    libmod.save({"done": {}, "stamps": {}})
    assert temp_library.exists()
    assert not (tmp_path / "library.json.tmp").exists()


def test_save_trims_oldest_entries(monkeypatch, temp_library):
    monkeypatch.setattr(libmod, "_MAX_ENTRIES", 3)
    libmod.save({"done": {str(i): {} for i in range(6)}, "stamps": {}})
    kept = list(libmod.load()["done"])
    assert kept == ["3", "4", "5"]


def test_save_failure_is_swallowed(monkeypatch):
    """A read-only library must not take a finished conversion down with it."""
    monkeypatch.setattr(
        libmod.Path, "write_text",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")),
    )
    libmod.save({"done": {}, "stamps": {}})  # must not raise


# --- mark / is_done -------------------------------------------------------

def test_mark_then_is_done(tmp_path):
    f = _write(tmp_path, "album.flac")
    assert libmod.is_done(f) is False
    libmod.mark([f])
    assert libmod.is_done(f) is True


def test_is_done_matches_a_copy_elsewhere(tmp_path):
    src = _write(tmp_path, "album.flac")
    libmod.mark([src])
    other = tmp_path / "elsewhere"
    other.mkdir()
    copy = other / "renamed.flac"
    copy.write_bytes((tmp_path / "album.flac").read_bytes())
    assert libmod.is_done(str(copy)) is True


def test_is_done_false_after_content_changes(tmp_path):
    f = _write(tmp_path, "album.flac")
    libmod.mark([f])
    (tmp_path / "album.flac").write_bytes(b"a different rip entirely")
    assert libmod.is_done(f) is False


def test_mark_ignores_missing_files(tmp_path):
    libmod.mark([str(tmp_path / "gone.flac")])
    assert libmod.load()["done"] == {}


def test_mark_empty_list_writes_nothing(temp_library):
    libmod.mark([])
    assert not temp_library.exists()


# --- filter_new -----------------------------------------------------------

def test_filter_new_drops_converted_files(tmp_path):
    done = _write(tmp_path, "done.flac", b"one")
    fresh = _write(tmp_path, "fresh.flac", b"two")
    libmod.mark([done])
    assert libmod.filter_new([done, fresh]) == [fresh]


def test_filter_new_drops_duplicates_within_a_batch(tmp_path):
    a = _write(tmp_path, "a.flac", b"same")
    b = _write(tmp_path, "b.flac", b"same")
    assert libmod.filter_new([a, b]) == [a]


def test_filter_new_keeps_unreadable_paths(tmp_path):
    """Let the converter report the failure rather than silently dropping it."""
    ghost = str(tmp_path / "gone.flac")
    assert libmod.filter_new([ghost]) == [ghost]


def test_filter_new_preserves_order(tmp_path):
    files = [_write(tmp_path, f"{i}.flac", str(i).encode()) for i in range(4)]
    assert libmod.filter_new(files) == files


# --- digest caching -------------------------------------------------------

def test_unchanged_files_are_not_rehashed(tmp_path, monkeypatch):
    f = _write(tmp_path, "big.mkv")
    libmod.mark([f])

    calls = []
    real = libmod.digest
    monkeypatch.setattr(
        libmod, "digest", lambda p: (calls.append(p), real(p))[1]
    )
    assert libmod.is_done(f) is True
    assert calls == []  # served from the (path, size, mtime) cache


def test_changed_file_is_rehashed(tmp_path):
    f = _write(tmp_path, "big.mkv", b"first")
    libmod.mark([f])
    import os
    (tmp_path / "big.mkv").write_bytes(b"second cut")
    os.utime(f, (0, 0))  # force a different mtime
    assert libmod.is_done(f) is False
