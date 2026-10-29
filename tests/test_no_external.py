import re

from conftest import frame_form

EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']?\s*https?://""", re.IGNORECASE)


def assert_self_contained(html):
    lower = html.lower()
    assert "<script" not in lower
    assert "<link" not in lower
    assert not EXTERNAL.search(html)
    assert "@import" not in lower
    assert "url(http" not in lower


def test_no_external_resources(client, board_id):
    client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    pages = [
        client.get("/"),
        client.get(f"/storyboards/{board_id}"),
        client.post("/storyboards", data={"song_title": ""}),
    ]
    assert pages[2].status_code == 400
    for page in pages:
        assert_self_contained(page.data.decode("utf-8"))
