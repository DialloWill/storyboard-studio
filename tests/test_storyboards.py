import pytest

from conftest import make_storyboard


def test_index_ok(client):
    assert client.get("/").status_code == 200


def test_create_redirects_and_lists(client):
    make_storyboard(client, "Midnight Static")
    assert b"Midnight Static" in client.get("/").data


@pytest.mark.parametrize("title", ["", "   ", "x" * 101])
def test_invalid_title(client, data_dir, title):
    resp = client.post("/storyboards", data={"song_title": title})
    assert resp.status_code == 400
    assert b"Song title" in resp.data
    assert list(data_dir.iterdir()) == []


def test_title_at_limit_ok(client):
    make_storyboard(client, "x" * 100)


def test_title_is_escaped(client, board_id):
    make_storyboard(client, "<b>hi</b>")
    assert b"<b>hi</b>" not in client.get("/").data


def test_unknown_storyboard_404(client):
    assert client.get("/storyboards/" + "0" * 32).status_code == 404
    assert client.get("/storyboards/not-an-id").status_code == 404
