import json

import pytest

from app import clips, storage
from app.clips import render
from conftest import make_storyboard
from fake_encoder import (FailingEncoder, FakeEncoder, UnavailableEncoder, add_frame,  # noqa: F401
                          animate_url, app, clip_files, encoder, frame_clip_url, snapshot)


@pytest.fixture
def two(client, board_id):
    a = add_frame(client, board_id, section="intro", scene="first")
    b = add_frame(client, board_id, section="verse", scene="second")
    return board_id, a, b


def board_json(data_dir, board_id):
    return (data_dir / board_id / "storyboard.json").read_bytes()


def test_post_creates_clip_and_redirects_then_get_serves_it(client, data_dir, two, encoder):
    board_id, fid, _ = two
    resp = client.post(animate_url(board_id, fid), data={})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(animate_url(board_id, fid))
    files = clip_files(data_dir, board_id)
    assert f"{fid}.json" in files
    mp4 = [f for f in files if f.endswith(".mp4")]
    assert len(mp4) == 1 and mp4[0].startswith(fid + ".") and not any(f.endswith(".tmp") for f in files)
    meta = json.loads((data_dir / board_id / "clips" / f"{fid}.json").read_text())
    assert meta["file"] == mp4[0] and meta["fps"] == 15 and (meta["width"], meta["height"]) == (640, 360)
    clip = client.get(frame_clip_url(board_id, fid))
    assert clip.status_code == 200
    assert clip.mimetype == "video/mp4"
    page = client.get(animate_url(board_id, fid)).get_data(as_text=True)
    assert "<video controls" in page and frame_clip_url(board_id, fid) in page


def test_get_never_creates_anything(client, data_dir, two):
    board_id, fid, _ = two
    before = snapshot(data_dir)
    assert client.get(animate_url(board_id, fid)).status_code == 200
    assert client.get(frame_clip_url(board_id, fid)).status_code == 404
    assert client.get(f"/storyboards/{board_id}/play").status_code == 200
    assert client.get(f"/storyboards/{board_id}/play/clip").status_code == 404
    assert client.get(f"/storyboards/{board_id}").status_code == 200
    assert snapshot(data_dir) == before


def test_range_request_returns_206(client, two):
    board_id, fid, _ = two
    client.post(animate_url(board_id, fid))
    resp = client.get(frame_clip_url(board_id, fid), headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert len(resp.data) == 100
    assert resp.headers["Content-Range"].startswith("bytes 0-99/")


@pytest.mark.parametrize("path", [
    "/storyboards/{b}/frames/{bad}/animate",
    "/storyboards/{b}/frames/{bad}/animate/clip",
])
@pytest.mark.parametrize("bad", ["nothex", "0" * 32, "../../etc", ("a" * 32) + "\n"])
def test_bad_frame_ids_get_the_friendly_404(client, board_id, path, bad):
    resp = client.get(path.format(b=board_id, bad=bad))
    assert resp.status_code == 404
    assert "Nothing here" in resp.get_data(as_text=True)


@pytest.mark.parametrize("bad", ["nothex", "0" * 32, ("a" * 32) + "\n"])
def test_bad_board_ids_get_the_friendly_404(client, bad):
    for method, path in [("get", f"/storyboards/{bad}/play"), ("get", f"/storyboards/{bad}/play/clip"),
                         ("post", f"/storyboards/{bad}/play"),
                         ("post", f"/storyboards/{bad}/frames/{'0' * 32}/animate"),
                         ("post", f"/storyboards/{bad}/frames/{'0' * 32}/move")]:
        resp = getattr(client, method)(path)
        assert resp.status_code == 404, path
        assert "Nothing here" in resp.get_data(as_text=True)


def test_frame_from_another_tape_is_not_found(client, two):
    board_id, fid, _ = two
    other = make_storyboard(client, "Other")
    assert client.post(animate_url(other, fid)).status_code == 404
    assert client.get(frame_clip_url(other, fid)).status_code == 404


def test_invalid_camera_move_is_a_friendly_400_everywhere(client, data_dir, two, encoder):
    board_id, fid, _ = two
    before = snapshot(data_dir)
    for url in (animate_url(board_id, fid), f"/storyboards/{board_id}/frames/{fid}/move"):
        resp = client.post(url, data={"camera_move": "barrel-roll"})
        assert resp.status_code == 400
        assert "camera move" in resp.get_data(as_text=True).lower()
    resp = client.post(f"/storyboards/{board_id}/frames/{fid}/move", data={"camera_move": ""})
    assert resp.status_code == 400
    assert snapshot(data_dir) == before and encoder.calls == []
    from conftest import frame_form
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(camera_move="barrel-roll"))
    assert resp.status_code == 400
    assert "Unknown camera move" in resp.get_data(as_text=True)
    assert snapshot(data_dir) == before


def test_camera_move_is_stored_only_when_explicitly_picked(client, data_dir, board_id):
    plain = add_frame(client, board_id)
    picked = add_frame(client, board_id, camera_move="pan-left")
    board = storage.load_storyboard(data_dir, board_id)
    by_id = {f["id"]: f for f in board["frames"]}
    assert "camera_move" not in by_id[plain]
    assert by_id[picked]["camera_move"] == "pan-left"


def test_animate_with_keep_current_never_touches_storyboard_json(client, data_dir, two):
    board_id, fid, _ = two
    before = board_json(data_dir, board_id)
    client.post(animate_url(board_id, fid), data={"camera_move": ""})
    assert board_json(data_dir, board_id) == before


def test_animate_with_explicit_move_saves_it_and_move_route_saves_without_rendering(
        client, data_dir, two, encoder):
    board_id, fid, other = two
    client.post(animate_url(board_id, fid), data={"camera_move": "tilt-down"})
    frames = {f["id"]: f for f in storage.load_storyboard(data_dir, board_id)["frames"]}
    assert frames[fid]["camera_move"] == "tilt-down"
    assert "camera_move" not in frames[other]
    renders = len(encoder.calls)
    resp = client.post(f"/storyboards/{board_id}/frames/{other}/move", data={"camera_move": "zoom-out"})
    assert resp.status_code == 302
    assert len(encoder.calls) == renders
    frames = {f["id"]: f for f in storage.load_storyboard(data_dir, board_id)["frames"]}
    assert frames[other]["camera_move"] == "zoom-out"


def test_animating_a_fresh_clip_is_a_no_op(client, two, encoder):
    board_id, fid, _ = two
    client.post(animate_url(board_id, fid))
    client.post(animate_url(board_id, fid))
    assert len(encoder.calls) == 1


def test_legacy_frame_without_move_or_fx_animates_with_defaults(client, data_dir, board_id, encoder):
    fid = add_frame(client, board_id)
    path = data_dir / board_id / "storyboard.json"
    board = json.loads(path.read_text())
    board["frames"][0].pop("fx", None)
    board["frames"][0].pop("direction", None)
    path.write_text(json.dumps(board))
    assert client.post(animate_url(board_id, fid)).status_code == 302
    assert len(encoder.calls) == 1


def test_missing_png_is_a_friendly_error_and_nothing_is_saved(client, data_dir, two, encoder):
    board_id, fid, _ = two
    board = storage.load_storyboard(data_dir, board_id)
    (data_dir / board_id / board["frames"][0]["filename"]).unlink()
    before = snapshot(data_dir)
    resp = client.post(animate_url(board_id, fid), data={"camera_move": "pan-right"})
    assert resp.status_code == 409
    assert "missing" in resp.get_data(as_text=True).lower()
    resp = client.post(f"/storyboards/{board_id}/play")
    assert resp.status_code == 409
    assert snapshot(data_dir) == before and encoder.calls == []
    assert client.get(f"/storyboards/{board_id}").status_code == 200  # page still renders


def test_missing_encoder_is_a_friendly_503_and_nothing_is_saved(tmp_path, two):
    from app import create_app
    app2 = create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock",
                       "CLIP_ENCODER": UnavailableEncoder()})
    c = app2.test_client()
    board_id, fid, _ = two  # created with the first app on the same data dir (tmp_path)
    before = snapshot(tmp_path)
    resp = c.post(animate_url(board_id, fid), data={"camera_move": "pan-left"})
    assert resp.status_code == 503 and "Video encoder not found" in resp.get_data(as_text=True)
    assert c.post(f"/storyboards/{board_id}/play").status_code == 503
    assert snapshot(tmp_path) == before  # not even the explicit move was saved


def test_empty_tape_is_friendly(client, data_dir, board_id, encoder):
    page = client.get(f"/storyboards/{board_id}/play")
    assert page.status_code == 200 and "Tape is blank" in page.get_data(as_text=True)
    before = snapshot(data_dir)
    resp = client.post(f"/storyboards/{board_id}/play")
    assert resp.status_code == 400 and "no frames" in resp.get_data(as_text=True)
    assert snapshot(data_dir) == before and encoder.calls == []


def test_tape_export_uses_sorted_frames_order(client, data_dir, board_id, monkeypatch):
    # Created out of storyboard order on purpose: outro first, then intro, then hook.
    ids = {name: add_frame(client, board_id, section=name, scene=name)
           for name in ("outro", "intro", "hook")}
    seen = {}

    def capture(items):
        seen["items"] = list(items)
        return iter(())

    monkeypatch.setattr(render, "tape_sequence", capture)
    assert client.post(f"/storyboards/{board_id}/play").status_code == 302
    board = storage.load_storyboard(data_dir, board_id)
    from app import fx
    expected = [fx.seed_from_frame_id(f["id"]) for f in storage.sorted_frames(board)]
    assert [item[3] for item in seen["items"]] == expected
    assert [f["section"] for f in storage.sorted_frames(board)] == ["intro", "hook", "outro"]
    assert client.get(f"/storyboards/{board_id}/play/clip").status_code == 200
    assert "<video controls" in client.get(f"/storyboards/{board_id}/play").get_data(as_text=True)


def test_tape_export_frame_count_and_encoder_settings(tmp_path):
    from app import create_app
    enc = FakeEncoder(consume=True)
    app2 = create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock", "CLIP_ENCODER": enc})
    c = app2.test_client()
    board_id = make_storyboard(c)
    add_frame(c, board_id, section="intro")
    add_frame(c, board_id, section="verse")
    assert c.post(f"/storyboards/{board_id}/play").status_code == 302
    assert enc.frame_counts == [2 * 45 + 4]
    assert enc.calls[0][1:] == (15, (640, 360))
    assert enc.shapes == {((360, 640, 3), "uint8")}


def test_too_many_frames_is_a_friendly_400(client, data_dir, board_id, monkeypatch):
    from app.clips import settings
    add_frame(client, board_id)
    add_frame(client, board_id)
    monkeypatch.setattr(settings, "MAX_EXPORT_FRAMES", 1)
    resp = client.post(f"/storyboards/{board_id}/play")
    assert resp.status_code == 400 and "up to 1 frames" in resp.get_data(as_text=True)


def test_tape_erase_blocked_by_an_open_video_is_friendly(client, data_dir, board_id, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(storage, "trash_storyboard", locked)
    resp = client.post(f"/storyboards/{board_id}/delete")
    assert resp.status_code == 409 and "Close the video tab" in resp.get_data(as_text=True)
    assert (data_dir / board_id / "storyboard.json").is_file()


def test_storyboard_page_shows_controls_without_scripts(client, two):
    board_id, fid, _ = two
    html = client.get(f"/storyboards/{board_id}").get_data(as_text=True)
    assert "Play tape" in html and "Animate" in html and 'name="camera_move"' in html
    assert "<script" not in html.lower()
