"""Ids and filenames are matched in full: a trailing newline must not slip past "$"."""

import pytest

from app import storage
from conftest import frame_form

SUFFIXES = ["\n", "\r\n"]
SUFFIX_URL = {"\n": "%0A", "\r\n": "%0D%0A"}
PNG = b"\x89PNG fake"


def listing(root):
    """Every path under root with its size, so any write shows up as a difference."""
    return sorted((str(p.relative_to(root)), p.stat().st_size if p.is_file() else None)
                  for p in root.rglob("*"))


@pytest.fixture
def board_with_frame(client, board_id):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    assert resp.status_code == 302
    board = storage.load_storyboard(client.application.config["DATA_DIR"], board_id)
    return board_id, board["frames"][0]


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_storage_rejects_storyboard_id_with_newline(data_dir, board_id, suffix):
    before = listing(data_dir)
    bad = board_id + suffix
    assert storage.load_storyboard(data_dir, bad) is None
    with pytest.raises(FileNotFoundError):
        storage.add_frame(data_dir, bad, {"section": "intro"}, PNG)
    assert storage.frame_image_path(data_dir, bad, "0" * 32 + ".png") is None
    assert listing(data_dir) == before


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_storage_rejects_frame_id_with_newline(data_dir, board_id, suffix):
    before = listing(data_dir)
    with pytest.raises(ValueError):
        storage.add_frame(data_dir, board_id, {"section": "intro"}, PNG,
                          frame_id=storage.new_id() + suffix)
    assert listing(data_dir) == before


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_storage_rejects_filename_with_newline(data_dir, board_with_frame, suffix):
    board_id, frame = board_with_frame
    assert storage.frame_image_path(data_dir, board_id, frame["filename"]) is not None
    before = listing(data_dir)
    assert storage.frame_image_path(data_dir, board_id, frame["filename"] + suffix) is None
    assert listing(data_dir) == before


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_helpers_reject_newline(suffix):
    assert storage.is_valid_id("a" * 32)
    assert not storage.is_valid_id("a" * 32 + suffix)
    assert storage.is_valid_filename("a" * 32 + ".png")
    assert not storage.is_valid_filename("a" * 32 + ".png" + suffix)


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("path", ["", "/shotlist.csv"])
def test_get_routes_404_for_storyboard_id_with_newline(client, data_dir, board_id, suffix, path):
    before = listing(data_dir)
    resp = client.get(f"/storyboards/{board_id}{SUFFIX_URL[suffix]}{path}")
    assert resp.status_code == 404
    assert listing(data_dir) == before


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_add_frame_route_404_for_storyboard_id_with_newline(client, data_dir, board_id, suffix):
    before = listing(data_dir)
    resp = client.post(f"/storyboards/{board_id}{SUFFIX_URL[suffix]}/frames", data=frame_form())
    assert resp.status_code == 404
    assert listing(data_dir) == before


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("tail", ["", "/download"])
def test_image_routes_404_for_newline_ids_and_filenames(client, data_dir, board_with_frame,
                                                       suffix, tail):
    board_id, frame = board_with_frame
    name = frame["filename"]
    assert client.get(f"/storyboards/{board_id}/frames/{name}{tail}").status_code == 200
    before = listing(data_dir)
    bad_name = f"/storyboards/{board_id}/frames/{name}{SUFFIX_URL[suffix]}{tail}"
    bad_board = f"/storyboards/{board_id}{SUFFIX_URL[suffix]}/frames/{name}{tail}"
    assert client.get(bad_name).status_code == 404
    assert client.get(bad_board).status_code == 404
    assert listing(data_dir) == before
