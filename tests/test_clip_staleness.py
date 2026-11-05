import json
import os

import pytest

from app import storage
from conftest import make_storyboard
from fake_encoder import (FailingEncoder, add_frame, animate_url, app, clip_files,  # noqa: F401
                          encoder, frame_clip_url, snapshot)


def mp4s(data_dir, board_id, prefix):
    return [f for f in clip_files(data_dir, board_id) if f.startswith(prefix) and f.endswith(".mp4")]


def tape_state(client, board_id):
    return client.get(f"/storyboards/{board_id}/play/clip").status_code


@pytest.fixture
def exported(client, board_id):
    fid = add_frame(client, board_id, section="intro")
    client.post(animate_url(board_id, fid))
    client.post(f"/storyboards/{board_id}/play")
    assert tape_state(client, board_id) == 200
    return board_id, fid


def test_camera_move_change_makes_clip_and_export_stale_and_renames_the_file(client, data_dir, exported):
    board_id, fid = exported
    old = mp4s(data_dir, board_id, fid)
    client.post(f"/storyboards/{board_id}/frames/{fid}/move", data={"camera_move": "tilt-up"})
    assert client.get(frame_clip_url(board_id, fid)).status_code == 404
    assert tape_state(client, board_id) == 404
    page = client.get(animate_url(board_id, fid)).get_data(as_text=True)
    assert "STALE" in page and "<video" not in page
    client.post(animate_url(board_id, fid))
    new = mp4s(data_dir, board_id, fid)
    assert client.get(frame_clip_url(board_id, fid)).status_code == 200
    assert len(new) == 1 and new != old            # fingerprinted name changed, old one cleaned up
    assert tape_state(client, board_id) == 404     # tape still needs its own re-export
    client.post(f"/storyboards/{board_id}/play")
    assert tape_state(client, board_id) == 200
    assert len(mp4s(data_dir, board_id, "tape")) == 1


def test_adding_a_frame_makes_the_export_stale(client, exported):
    board_id, _ = exported
    add_frame(client, board_id, section="verse")
    assert tape_state(client, board_id) == 404
    assert "STALE" in client.get(f"/storyboards/{board_id}/play").get_data(as_text=True)


def test_rename_does_not_invalidate(client, exported):
    board_id, fid = exported
    client.post(f"/storyboards/{board_id}/rename", data={"song_title": "New name"})
    assert tape_state(client, board_id) == 200
    assert client.get(frame_clip_url(board_id, fid)).status_code == 200


def test_erasing_a_frame_trashes_its_clip_and_stales_the_export(client, data_dir, board_id):
    keep = add_frame(client, board_id, section="intro")
    gone = add_frame(client, board_id, section="verse")
    for f in (keep, gone):
        client.post(animate_url(board_id, f))
    client.post(f"/storyboards/{board_id}/play")
    assert client.post(f"/storyboards/{board_id}/frames/{gone}/delete").status_code == 302
    assert mp4s(data_dir, board_id, gone) == [] and f"{gone}.json" not in clip_files(data_dir, board_id)
    trashed = list((data_dir / "_trash" / "frames").iterdir())
    assert len(trashed) == 1
    names = sorted(p.name for p in trashed[0].iterdir())
    assert any(n.startswith(gone) and n.endswith(".mp4") for n in names) and f"{gone}.json" in names
    assert client.get(frame_clip_url(board_id, gone)).status_code == 404
    assert client.get(frame_clip_url(board_id, keep)).status_code == 200
    assert tape_state(client, board_id) == 404
    client.post(f"/storyboards/{board_id}/play")
    assert tape_state(client, board_id) == 200


def test_erasing_a_frame_still_works_if_its_clip_is_locked(client, data_dir, board_id, monkeypatch):
    fid = add_frame(client, board_id)
    client.post(animate_url(board_id, fid))
    real = os.replace

    def locked(src, dst):
        if str(src).endswith(".mp4"):
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(storage.os, "replace", locked)
    assert client.post(f"/storyboards/{board_id}/frames/{fid}/delete").status_code == 302
    assert storage.load_storyboard(data_dir, board_id)["frames"] == []


def test_erasing_the_tape_moves_its_clips_with_it(client, data_dir, exported):
    board_id, fid = exported
    assert client.post(f"/storyboards/{board_id}/delete").status_code == 302
    trashed = list((data_dir / "_trash" / "tapes").iterdir())
    assert len(trashed) == 1
    assert any(p.name.startswith(fid) and p.suffix == ".mp4" for p in (trashed[0] / "clips").iterdir())


def test_rewritten_image_bytes_make_the_clip_stale(client, data_dir, exported):
    board_id, fid = exported
    board = storage.load_storyboard(data_dir, board_id)
    png = data_dir / board_id / board["frames"][0]["filename"]
    png.write_bytes(png.read_bytes() + b"\x00")  # content changed, filename identical
    assert client.get(frame_clip_url(board_id, fid)).status_code == 404
    assert tape_state(client, board_id) == 404


def test_cleanup_tolerates_an_undeletable_old_file(client, data_dir, board_id, monkeypatch):
    fid = add_frame(client, board_id)
    client.post(animate_url(board_id, fid))
    old = mp4s(data_dir, board_id, fid)
    calls = []

    def locked(path, *a, **k):
        calls.append(path)
        raise PermissionError("in use")

    monkeypatch.setattr(storage.os, "remove", locked)
    resp = client.post(animate_url(board_id, fid), data={"camera_move": "pan-left"})
    assert resp.status_code == 302 and calls
    monkeypatch.undo()
    files = mp4s(data_dir, board_id, fid)
    assert set(old) < set(files) and len(files) == 2   # old one left behind, new one added
    assert client.get(frame_clip_url(board_id, fid)).status_code == 200  # the new clip is served
    client.post(animate_url(board_id, fid), data={"camera_move": "zoom-out"})  # a later render retries
    assert len(mp4s(data_dir, board_id, fid)) == 1


def test_failed_encode_leaves_no_tmp_and_no_meta(tmp_path):
    from app import create_app
    app2 = create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock",
                       "CLIP_ENCODER": FailingEncoder()})
    c = app2.test_client()
    board_id = make_storyboard(c)
    fid = add_frame(c, board_id)
    resp = c.post(animate_url(board_id, fid))
    assert resp.status_code == 502 and "Nothing was saved" in resp.get_data(as_text=True)
    resp = c.post(f"/storyboards/{board_id}/play")
    assert resp.status_code == 502
    assert clip_files(tmp_path, board_id) == []
    assert c.get(frame_clip_url(board_id, fid)).status_code == 404


def test_meta_is_the_commit_marker(client, data_dir, board_id):
    """A clip file with no meta (crash between the two writes) is never served."""
    fid = add_frame(client, board_id)
    client.post(animate_url(board_id, fid))
    (data_dir / board_id / "clips" / f"{fid}.json").unlink()
    assert client.get(frame_clip_url(board_id, fid)).status_code == 404


def test_meta_naming_another_file_is_never_served(client, data_dir, board_id):
    fid = add_frame(client, board_id)
    client.post(animate_url(board_id, fid))
    meta_path = data_dir / board_id / "clips" / f"{fid}.json"
    meta = json.loads(meta_path.read_text())
    for evil in ("../storyboard.json", "tape." + "a" * 12 + ".mp4", "x.mp4", None):
        meta["file"] = evil
        meta_path.write_text(json.dumps(meta))
        assert client.get(frame_clip_url(board_id, fid)).status_code == 404
