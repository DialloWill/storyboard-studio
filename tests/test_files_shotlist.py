import csv
import io

import pytest

from conftest import frame_form, make_storyboard


def add_frame(client, board_id, **overrides):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(**overrides))
    assert resp.status_code == 302


def first_filename(data_dir, board_id):
    return next((data_dir / board_id).glob("*.png")).name


def test_image_and_download(client, data_dir, board_id):
    add_frame(client, board_id)
    name = first_filename(data_dir, board_id)
    img = client.get(f"/storyboards/{board_id}/frames/{name}")
    assert img.status_code == 200
    assert img.mimetype == "image/png"
    dl = client.get(f"/storyboards/{board_id}/frames/{name}/download")
    assert dl.status_code == 200
    assert dl.headers["Content-Disposition"].startswith("attachment")


def test_relative_data_dir_serves_images(tmp_path, monkeypatch):
    from app import create_app

    monkeypatch.chdir(tmp_path)
    client = create_app({"TESTING": True, "DATA_DIR": "data", "GENERATOR": "mock"}).test_client()
    board_id = make_storyboard(client)
    add_frame(client, board_id)
    name = first_filename(tmp_path / "data", board_id)
    assert client.get(f"/storyboards/{board_id}/frames/{name}").status_code == 200
    assert client.get(f"/storyboards/{board_id}/frames/{name}/download").status_code == 200


def test_traversal_and_bad_names_404(client, data_dir, board_id):
    add_frame(client, board_id)
    name = first_filename(data_dir, board_id)
    stem = name[:-4]
    bad = [
        "../storyboard.json",
        "..%2Fstoryboard.json",
        "%2e%2e%2fstoryboard.json",
        "..%5Cstoryboard.json",
        "notauuid.png",
        stem + ".jpg",
        stem,
        "storyboard.json",
        "0" * 32 + ".png",
    ]
    for b in bad:
        assert client.get(f"/storyboards/{board_id}/frames/{b}").status_code == 404, b
        assert client.get(f"/storyboards/{board_id}/frames/{b}/download").status_code == 404, b


def test_bad_storyboard_ids_404(client, board_id):
    for bad in ["..", "..%2F", "%2e%2e", "not-an-id", "0" * 32, "A" * 32]:
        # Werkzeug may normalise odd paths with a redirect first; the end result must be 404.
        img = client.get(f"/storyboards/{bad}/frames/{'0' * 32}.png", follow_redirects=True)
        assert img.status_code == 404, bad
        csv_resp = client.get(f"/storyboards/{bad}/shotlist.csv", follow_redirects=True)
        assert csv_resp.status_code == 404, bad


def test_frame_under_wrong_storyboard_404(client, data_dir, board_id):
    add_frame(client, board_id)
    name = first_filename(data_dir, board_id)
    other = make_storyboard(client, "Other song")
    assert client.get(f"/storyboards/{other}/frames/{name}").status_code == 404
    assert client.get(f"/storyboards/{other}/frames/{name}/download").status_code == 404


def test_shotlist_csv(client, board_id):
    add_frame(client, board_id, section="outro", scene="Closing")
    add_frame(client, board_id, section="intro", scene="=SUM(1,1) opening")
    resp = client.get(f"/storyboards/{board_id}/shotlist.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))
    assert rows[0] == ["section", "scene", "camera", "shot", "lighting", "direction", "prompt", "filename"]
    assert len(rows) == 3
    assert [r[0] for r in rows[1:]] == ["intro", "outro"]
    assert rows[1][1].startswith("'=")


def test_shotlist_header_only_when_empty(client, board_id):
    resp = client.get(f"/storyboards/{board_id}/shotlist.csv")
    assert len(resp.data.decode().strip().splitlines()) == 1
