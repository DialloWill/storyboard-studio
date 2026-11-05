import json

import pytest
from conftest import frame_form, make_storyboard

from app import security
from app.generators.mock import MockGenerator

FOREIGN = "http://evil.example"


def routes(board_id, frame_id):
    return [
        ("/storyboards", {"song_title": "Evil"}),
        (f"/storyboards/{board_id}/frames", frame_form()),
        (f"/storyboards/{board_id}/rename", {"song_title": "Evil"}),
        (f"/storyboards/{board_id}/frames/{frame_id}/delete", {}),
        (f"/storyboards/{board_id}/delete", {}),
    ]


def setup(client, data_dir):
    board_id = make_storyboard(client)
    client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    board = json.loads((data_dir / board_id / "storyboard.json").read_text())
    return board_id, board["frames"][0]["id"]


def snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


ATTACKS = {
    "foreign-origin": {"Origin": FOREIGN},
    "null-origin": {"Origin": "null"},
    "foreign-origin-matching-referer": {"Origin": FOREIGN, "Referer": "http://localhost/x"},
    "wrong-port": {"Origin": "http://localhost:6666"},
    "wrong-scheme": {"Origin": "https://localhost"},
}


@pytest.mark.parametrize("name", ATTACKS)
def test_cross_origin_rejected_on_every_post(client, data_dir, name):
    board_id, frame_id = setup(client, data_dir)
    before = snapshot(data_dir)
    for url, data in routes(board_id, frame_id):
        r = client.post(url, data=data, headers=ATTACKS[name])
        assert r.status_code == 403, url
        assert b"Traceback" not in r.data
    assert snapshot(data_dir) == before


def test_no_origin_or_referer_rejected_on_every_post(bare_client, client, data_dir):
    board_id, frame_id = setup(client, data_dir)
    before = snapshot(data_dir)
    for url, data in routes(board_id, frame_id):
        assert bare_client.post(url, data=data).status_code == 403, url
    assert snapshot(data_dir) == before


def test_foreign_referer_without_origin_rejected(bare_client, client, data_dir):
    board_id, frame_id = setup(client, data_dir)
    before = snapshot(data_dir)
    for url, data in routes(board_id, frame_id):
        r = bare_client.post(url, data=data, headers={"Referer": FOREIGN + "/page"})
        assert r.status_code == 403, url
    assert snapshot(data_dir) == before


def test_rejected_add_frame_never_calls_generator(client, data_dir, monkeypatch):
    board_id, _ = setup(client, data_dir)
    calls = []
    monkeypatch.setattr(MockGenerator, "generate",
                        lambda self, prompt: calls.append(prompt) or b"")
    r = client.post(f"/storyboards/{board_id}/frames", data=frame_form(),
                    headers={"Origin": FOREIGN})
    assert r.status_code == 403 and calls == []


def test_matching_origin_and_referer_pass(bare_client):
    ok = bare_client.post("/storyboards", data={"song_title": "A"},
                          headers={"Origin": "http://localhost"})
    assert ok.status_code == 302
    ok = bare_client.post("/storyboards", data={"song_title": "B"},
                          headers={"Referer": "http://localhost/some/page"})
    assert ok.status_code == 302


def test_non_local_host_rejected(bare_client):
    r = bare_client.post("/storyboards", data={"song_title": "A"},
                         base_url="http://evil.example",
                         headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_local_ip_and_port_allowed(bare_client):
    r = bare_client.post("/storyboards", data={"song_title": "A"},
                         base_url="http://127.0.0.1:5000",
                         headers={"Origin": "http://127.0.0.1:5000"})
    assert r.status_code == 302


def test_safe_methods_never_blocked(bare_client):
    assert bare_client.get("/").status_code == 200
    assert bare_client.head("/").status_code == 200
    assert bare_client.options("/").status_code == 200


def test_origin_parser_rejects_garbage():
    assert security._origin_of("not a url") is None
    assert security._origin_of("null") is None
    assert security._origin_of("") is None
