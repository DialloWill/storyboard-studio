import io

import pytest

from ai_helpers import encoder, fake_video, make_zip, normalizer, upload  # noqa: F401
from fake_encoder import add_frame, animate_url, app, clip_files, snapshot  # noqa: F401
from test_no_external import assert_self_contained

from app import storage

FOREIGN = [{"Origin": "http://evil.example"}, {"Origin": "null"},
           {"Origin": "http://localhost:9999"}, {"Referer": "http://evil.example/x"}]


def import_one(client, board_id, fid, frames=20):
    resp = upload(client, f"/storyboards/{board_id}/frames/{fid}/animate/ai", "clip",
                  io.BytesIO(fake_video(frames)), "a.mp4")
    assert resp.status_code == 302


def trash_files(data_dir):
    root = data_dir / "_trash"
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def frame_of(data_dir, board_id, fid):
    board = storage.load_storyboard(data_dir, board_id)
    return next((f for f in board["frames"] if f["id"] == fid), None)


# ---- remove AI clip ---------------------------------------------------------------------

def test_remove_ai_clip_confirm_then_moves_files_to_trash(client, data_dir, board_id):
    a = add_frame(client, board_id)
    client.post(animate_url(board_id, a), data={})  # a procedural clip too
    import_one(client, board_id, a)
    url = f"/storyboards/{board_id}/frames/{a}/animate/ai/remove"
    before = clip_files(data_dir, board_id)
    page = client.get(url)
    assert page.status_code == 200 and "Remove AI clip" in page.get_data(as_text=True)
    assert clip_files(data_dir, board_id) == before  # GET changes nothing
    assert client.post(url).status_code == 302
    left = clip_files(data_dir, board_id)
    assert not [n for n in left if ".ai." in n]
    assert any(n.endswith(".mp4") for n in left)  # the procedural clip stays
    moved = trash_files(data_dir)
    assert len(moved) == 2 and all("ai-clips/" in n and f"{a}.ai." in n for n in moved)
    assert frame_of(data_dir, board_id, a)["clip_source"] == "procedural"
    assert client.get(url).status_code == 404  # nothing left to remove


def test_remove_ai_clip_unknown_ids(client, board_id):
    for bad in ["nothex", "f" * 32, ("a" * 32) + "\n"]:
        assert client.get(f"/storyboards/{board_id}/frames/{bad}/animate/ai/remove").status_code == 404
        assert client.post(f"/storyboards/{board_id}/frames/{bad}/animate/ai/remove").status_code == 404


def test_erasing_a_frame_moves_its_ai_clip_to_trash(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    assert client.post(f"/storyboards/{board_id}/frames/{a}/delete").status_code == 302
    assert not [n for n in clip_files(data_dir, board_id) if ".ai." in n]
    moved = trash_files(data_dir)
    assert len([n for n in moved if f"{a}.ai." in n]) == 2


def test_erasing_a_tape_moves_its_ai_clips_to_trash(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    assert client.post(f"/storyboards/{board_id}/delete").status_code == 302
    assert not (data_dir / board_id).exists()
    assert len([n for n in trash_files(data_dir) if f"{a}.ai." in n]) == 2


# ---- same-origin guard on every new POST route -----------------------------------------------

def posts(board_id, fid):
    zip_body = make_zip([(f"{fid}.mp4", fake_video())])
    return [
        (f"/storyboards/{board_id}/ai-clips", {"clips_zip": (zip_body, "ai_clips.zip")}),
        (f"/storyboards/{board_id}/frames/{fid}/animate/ai", {"clip": (io.BytesIO(fake_video()), "a.mp4")}),
        (f"/storyboards/{board_id}/frames/{fid}/animate/source", {"source": "procedural"}),
        (f"/storyboards/{board_id}/frames/{fid}/animate/ai/remove", {}),
    ]


@pytest.mark.parametrize("headers", FOREIGN)
def test_cross_origin_posts_to_ai_routes_get_403_and_change_nothing(client, bare_client, data_dir,
                                                                    board_id, encoder, headers):
    fid = add_frame(client, board_id)
    import_one(client, board_id, fid)
    before = snapshot(data_dir)
    calls = len(encoder.calls)
    for url, data in posts(board_id, fid):
        resp = bare_client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 403, url
    assert snapshot(data_dir) == before and len(encoder.calls) == calls


def test_ai_posts_without_origin_or_referer_are_refused(client, bare_client, board_id):
    fid = add_frame(client, board_id)
    for url, data in posts(board_id, fid):
        assert bare_client.post(url, data=data, content_type="multipart/form-data").status_code == 403


def test_same_origin_ai_posts_work(client, board_id):
    fid = add_frame(client, board_id)
    zip_body = make_zip([(f"{fid}.mp4", fake_video())])
    assert upload(client, f"/storyboards/{board_id}/ai-clips", "clips_zip", zip_body).status_code == 200
    assert client.post(f"/storyboards/{board_id}/frames/{fid}/animate/source",
                       data={"source": "procedural"}).status_code == 302


# ---- no external resources / no JavaScript on the new pages ---------------------------------

def test_new_pages_are_self_contained(client, board_id):
    fid = add_frame(client, board_id)
    import_one(client, board_id, fid)
    result = upload(client, f"/storyboards/{board_id}/ai-clips", "clips_zip",
                    make_zip([(f"{fid}.mp4", fake_video()), ("junk.txt", b"x")]))
    bad_zip = upload(client, f"/storyboards/{board_id}/ai-clips", "clips_zip", io.BytesIO(b"nope"))
    pages = [
        client.get(f"/storyboards/{board_id}"),
        client.get(animate_url(board_id, fid)),
        client.get(f"/storyboards/{board_id}/ai-clips"),
        result, bad_zip,
        client.get(f"/storyboards/{board_id}/frames/{fid}/animate/ai/remove"),
        client.get(f"/storyboards/{board_id}/ai-kit.zip" + "x"),  # a 404 page
    ]
    for page in pages:
        assert_self_contained(page.data.decode("utf-8"))
