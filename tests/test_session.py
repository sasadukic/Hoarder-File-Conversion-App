import json
import pytest
from pathlib import Path

import session as sess


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    p = tmp_path / "session.json"
    monkeypatch.setattr(sess, "_STATE_PATH", p)
    return p


def test_load_missing_file_is_empty(state_file):
    assert sess.load() == {"downloads": [], "encodes": []}


def test_load_corrupt_file_is_empty(state_file):
    state_file.write_text("not json at all")
    assert sess.load() == {"downloads": [], "encodes": []}


def test_load_non_dict_json_is_empty(state_file):
    state_file.write_text("[1, 2, 3]")
    assert sess.load() == {"downloads": [], "encodes": []}


def test_round_trip(state_file):
    downloads = [{"tid": "t1", "target": "magnet:?xt=urn:btih:1", "name": "One"}]
    encodes = [{"paths": ["/a/01.flac", "/a/02.flac"]}]
    sess.save(downloads, encodes)

    loaded = sess.load()
    assert loaded["downloads"] == downloads
    assert loaded["encodes"] == encodes


def test_save_is_atomic_and_leaves_no_temp_file(state_file):
    sess.save([{"tid": "t", "target": "magnet:?x", "name": "n"}], [])
    assert state_file.exists()
    assert not state_file.with_suffix(".json.tmp").exists()


def test_downloads_without_a_target_are_dropped(state_file):
    """A record with nothing to re-add is not a resumable download."""
    state_file.write_text(json.dumps({
        "downloads": [
            {"tid": "keep", "target": "magnet:?xt=urn:btih:1", "name": "Keep"},
            {"tid": "no-target", "name": "Nope"},
            {"tid": "empty-target", "target": "", "name": "Nope"},
            "not even a dict",
        ],
        "encodes": [],
    }))
    assert [d["tid"] for d in sess.load()["downloads"]] == ["keep"]


def test_download_records_tolerate_missing_names(state_file):
    state_file.write_text(json.dumps({
        "downloads": [{"target": "magnet:?xt=urn:btih:1"}], "encodes": [],
    }))
    rec = sess.load()["downloads"][0]
    assert rec == {"tid": "", "target": "magnet:?xt=urn:btih:1", "name": ""}


def test_encodes_without_usable_paths_are_dropped(state_file):
    state_file.write_text(json.dumps({
        "downloads": [],
        "encodes": [
            {"paths": ["/a/01.flac"]},
            {"paths": []},
            {"paths": "not a list"},
            {"nothing": True},
        ],
    }))
    assert sess.load()["encodes"] == [{"paths": ["/a/01.flac"]}]


def test_clear_empties_both_lists(state_file):
    sess.save([{"tid": "t", "target": "magnet:?x", "name": "n"}],
              [{"paths": ["/a/01.flac"]}])
    sess.clear()
    assert sess.load() == {"downloads": [], "encodes": []}


def test_save_survives_an_unwritable_location(tmp_path, monkeypatch):
    """A session that cannot be written costs a resume, never a crash."""
    monkeypatch.setattr(sess, "_STATE_PATH", tmp_path / "no-such-dir" / "session.json")
    sess.save([{"tid": "t", "target": "magnet:?x", "name": "n"}], [])  # must not raise
