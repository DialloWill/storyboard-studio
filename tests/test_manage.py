import csv
import datetime as dt
import io
import json
import os

import pytest
from conftest import frame_form

from app import storage

BAD_IDS = ["0" * 32, "../etc", "A" * 32, "x"]


def add(client, board_id, **kw):
    r = client.post(f"/storyboards/{board_id}/frames", data=frame_form(**kw))
    assert r.status_code == 302


def board_json(data_dir, board_id):
    return json.loads((data_dir / board_id / "storyboard.json").read_text("utf-8"))


def frames_of(data_dir, board_id):
    return storage.sorted_frames(board_json(data_dir, board_id))


# ---- rename ---------------------------------------------------------------

def test_rename_success(client, data_dir, board_id):
    r = client.post(f"/storyboards/{board_id}/rename", data={"song_title": "  New Name  "})
    assert r.status_code == 302
    assert board_json(data_dir, board_id)["song_title"] == "New Name"
    assert b"New Name" in client.get("/").data


@pytest.mark.parametrize("title", ["", "   \t "])
def test_rename_empty_or_whitespace(client, data_dir, board_id, title):
    r = client.post(f"/storyboards/{board_id}/rename", data={"song_title": title})
    assert r.status_code == 400
    assert b"required" in r.data
    assert board_json(data_dir, board_id)["song_title"] == "Neon Nights"


def test_rename_over_length(client, data_dir, board_id):
    r = client.post(f"/storyboards/{board_id}/rename", data={"song_title": "x" * 101})
    assert r.status_code == 400
    assert b"100 characters" in r.data
    ok = client.post(f"/storyboards/{board_id}/rename", data={"song_title": "x" * 100})
    assert ok.status_code == 302


def test_rename_escapes_html(client, board_id):
    evil = "<script>alert(1)</script>"
    client.post(f"/storyboards/{board_id}/rename", data={"song_title": evil})
    for page in (client.get("/"), client.get(f"/storyboards/{board_id}"),
                 client.get(f"/storyboards/{board_id}/rename")):
        assert evil.encode() not in page.data
        assert b"&lt;script&gt;" in page.data


@pytest.mark.parametrize("bad", BAD_IDS)
def test_rename_invalid_uuid(client, bad):
    assert client.post(f"/storyboards/{bad}/rename", data={"song_title": "x"}).status_code == 404


def test_rename_nonexistent(client):
    r = client.post(f"/storyboards/{'a' * 32}/rename", data={"song_title": "x"})
    assert r.status_code == 404
    assert b"Traceback" not in r.data


def test_rename_get_does_not_change(client, data_dir, board_id):
    assert client.get(f"/storyboards/{board_id}/rename").status_code == 200
    assert board_json(data_dir, board_id)["song_title"] == "Neon Nights"


# ---- tape delete ----------------------------------------------------------

def test_tape_delete_moves_to_trash(client, data_dir, board_id):
    add(client, board_id)
    r = client.post(f"/storyboards/{board_id}/delete")
    assert r.status_code == 302
    assert not (data_dir / board_id).exists()
    trashed = list((data_dir / "_trash" / "tapes").iterdir())
    assert len(trashed) == 1 and trashed[0].name.endswith("_" + board_id)
    assert (trashed[0] / "storyboard.json").is_file()
    assert len(list(trashed[0].glob("*.png"))) == 1
    assert board_id.encode() not in client.get("/").data
    assert client.get(f"/storyboards/{board_id}").status_code == 404


def test_tape_delete_repeat_is_404(client, board_id):
    assert client.post(f"/storyboards/{board_id}/delete").status_code == 302
    r = client.post(f"/storyboards/{board_id}/delete")
    assert r.status_code == 404 and b"Traceback" not in r.data


@pytest.mark.parametrize("bad", BAD_IDS)
def test_tape_delete_invalid_uuid(client, data_dir, bad):
    assert client.post(f"/storyboards/{bad}/delete").status_code == 404
    assert not (data_dir / "_trash").exists()


def test_tape_delete_get_does_not_delete(client, data_dir, board_id):
    r = client.get(f"/storyboards/{board_id}/delete")
    assert r.status_code == 200 and b"Yes, erase" in r.data
    assert (data_dir / board_id / "storyboard.json").is_file()
    assert not (data_dir / "_trash").exists()


def test_repeated_deletes_never_collide(data_dir, monkeypatch):
    class Frozen:
        @staticmethod
        def now(tz=None):
            return dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(storage, "datetime", Frozen)
    a = storage._trash_target(data_dir, "tapes", "x")
    a.mkdir()
    b = storage._trash_target(data_dir, "tapes", "x")
    assert a != b


def test_trash_is_inside_data_and_not_listed(client, data_dir, board_id):
    client.post(f"/storyboards/{board_id}/delete")
    assert (data_dir / "_trash").resolve().is_relative_to(data_dir.resolve())
    assert storage.list_storyboards(data_dir) == []


def test_gitignore_covers_data():
    root = os.path.dirname(os.path.dirname(__file__))
    lines = open(os.path.join(root, ".gitignore"), encoding="utf-8").read().split()
    assert "data/" in lines


# ---- frame delete ---------------------------------------------------------

def test_frame_delete_moves_image_and_entry(client, data_dir, board_id):
    add(client, board_id, scene="one")
    add(client, board_id, scene="two")
    f1 = frames_of(data_dir, board_id)[0]
    r = client.post(f"/storyboards/{board_id}/frames/{f1['id']}/delete")
    assert r.status_code == 302
    assert not (data_dir / board_id / f1["filename"]).exists()
    (folder,) = (data_dir / "_trash" / "frames").iterdir()
    assert (folder / f1["filename"]).is_file()
    rec = json.loads((folder / "frame.json").read_text("utf-8"))
    assert rec["frame"]["id"] == f1["id"] and rec["storyboard_id"] == board_id
    assert [f["scene"] for f in frames_of(data_dir, board_id)] == ["two"]


def test_frame_delete_keeps_order_and_csv(client, data_dir, board_id):
    add(client, board_id, section="intro", scene="a")
    add(client, board_id, section="hook", scene="b")
    add(client, board_id, section="intro", scene="c")
    order = [f["scene"] for f in frames_of(data_dir, board_id)]
    victim = frames_of(data_dir, board_id)[1]
    client.post(f"/storyboards/{board_id}/frames/{victim['id']}/delete")
    expected = [s for s in order if s != victim["scene"]]
    assert [f["scene"] for f in frames_of(data_dir, board_id)] == expected
    rows = list(csv.reader(io.StringIO(
        client.get(f"/storyboards/{board_id}/shotlist.csv").data.decode())))
    assert [r[1] for r in rows[1:]] == expected
    assert victim["filename"] not in "".join(r[-1] for r in rows)


def test_frame_delete_nonexistent_and_repeat(client, data_dir, board_id):
    add(client, board_id)
    fid = frames_of(data_dir, board_id)[0]["id"]
    assert client.post(f"/storyboards/{board_id}/frames/{'b' * 32}/delete").status_code == 404
    assert client.post(f"/storyboards/{board_id}/frames/{fid}/delete").status_code == 302
    assert client.post(f"/storyboards/{board_id}/frames/{fid}/delete").status_code == 404
    assert client.post(f"/storyboards/{'c' * 32}/frames/{fid}/delete").status_code == 404
    assert client.post(f"/storyboards/{board_id}/frames/not-an-id/delete").status_code == 404


def test_frame_delete_get_does_not_delete(client, data_dir, board_id):
    add(client, board_id)
    f = frames_of(data_dir, board_id)[0]
    r = client.get(f"/storyboards/{board_id}/frames/{f['id']}/delete")
    assert r.status_code == 200
    assert (data_dir / board_id / f["filename"]).is_file()
    assert len(frames_of(data_dir, board_id)) == 1


def test_frame_delete_json_failure_rolls_back(client, data_dir, board_id, monkeypatch):
    add(client, board_id)
    f = frames_of(data_dir, board_id)[0]
    before = (data_dir / board_id / "storyboard.json").read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "_write_json_atomic", boom)
    with pytest.raises(OSError):
        storage.trash_frame(data_dir, board_id, f["id"])
    assert (data_dir / board_id / f["filename"]).is_file()
    assert (data_dir / board_id / "storyboard.json").read_bytes() == before


# ---- atomic writes --------------------------------------------------------

def test_atomic_write_failure_leaves_original(client, data_dir, board_id, monkeypatch):
    path = data_dir / board_id / "storyboard.json"
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("crash")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.rename_storyboard(data_dir, board_id, "Changed")
    assert path.read_bytes() == before
    assert json.loads(before)["song_title"] == "Neon Nights"
