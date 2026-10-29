import json

import pytest

from app.generators.mock import MockGenerator
from conftest import frame_form


def pngs(data_dir):
    return list(data_dir.rglob("*.png"))


def read_board(data_dir, board_id):
    return json.loads((data_dir / board_id / "storyboard.json").read_text(encoding="utf-8"))


def test_add_valid_frame(client, data_dir, board_id):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/storyboards/{board_id}")
    files = pngs(data_dir)
    assert len(files) == 1
    assert files[0].read_bytes().startswith(b"\x89PNG")
    frames = read_board(data_dir, board_id)["frames"]
    assert len(frames) == 1
    assert frames[0]["filename"] == files[0].name
    assert frames[0]["scene"] == "A singer on a rooftop at midnight"
    page = client.get(f"/storyboards/{board_id}")
    assert b"A singer on a rooftop at midnight" in page.data
    assert files[0].name.encode() in page.data


def test_frames_sorted_by_section(client, board_id):
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(section="outro", scene="Last scene"))
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(section="intro", scene="First scene"))
    page = client.get(f"/storyboards/{board_id}").data
    assert page.index(b"First scene") < page.index(b"Last scene")


def test_form_defaults_preselected(client, board_id):
    page = client.get(f"/storyboards/{board_id}").data.decode()
    assert '<option value="vhs-camcorder" selected>' in page
    assert '<option value="neon" selected>' in page


@pytest.mark.parametrize("overrides", [
    {"scene": ""},
    {"scene": "   "},
    {"scene": "x" * 301},
    {"camera": "bogus"},
    {"shot": "bogus"},
    {"lighting": "bogus"},
    {"section": "bogus"},
])
def test_invalid_frame(client, data_dir, board_id, overrides):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(**overrides))
    assert resp.status_code == 400
    assert b'class="error"' in resp.data
    assert pngs(data_dir) == []
    assert read_board(data_dir, board_id)["frames"] == []


def test_frame_on_unknown_storyboard_404(client):
    assert client.post("/storyboards/" + "0" * 32 + "/frames", data=frame_form()).status_code == 404


def test_generator_failure_returns_502(client, data_dir, board_id, monkeypatch):
    def boom(self, prompt):
        raise NotImplementedError("Comfy API v2 integration is implemented at build night")

    monkeypatch.setattr(MockGenerator, "generate", boom)
    before = (data_dir / board_id / "storyboard.json").read_text(encoding="utf-8")
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    assert resp.status_code == 502
    assert b"Image generation failed. Check the generator configuration or API credits." in resp.data
    assert pngs(data_dir) == []
    assert (data_dir / board_id / "storyboard.json").read_text(encoding="utf-8") == before


def test_comfy_without_key_returns_502(client, app, data_dir, board_id):
    app.config.update(GENERATOR="comfy", COMFY_API_KEY="")
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    assert resp.status_code == 502
    assert pngs(data_dir) == []
