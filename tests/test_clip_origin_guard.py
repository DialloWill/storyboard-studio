import pytest

from fake_encoder import add_frame, animate_url, app, encoder, snapshot  # noqa: F401

FOREIGN = [{"Origin": "http://evil.example"}, {"Origin": "null"},
           {"Origin": "http://localhost:9999"}, {"Referer": "http://evil.example/x"}]


def routes(board_id, frame_id):
    return [
        (animate_url(board_id, frame_id), {"camera_move": "pan-left"}),
        (f"/storyboards/{board_id}/frames/{frame_id}/move", {"camera_move": "pan-left"}),
        (f"/storyboards/{board_id}/play", {}),
    ]


@pytest.mark.parametrize("headers", FOREIGN)
def test_cross_origin_posts_to_new_routes_get_403_and_change_nothing(client, bare_client, data_dir,
                                                                    board_id, encoder, headers):
    fid = add_frame(client, board_id)
    before = snapshot(data_dir)
    for url, data in routes(board_id, fid):
        resp = bare_client.post(url, data=data, headers=headers)
        assert resp.status_code == 403, url
    assert snapshot(data_dir) == before and encoder.calls == []


def test_posts_without_origin_or_referer_are_refused(client, bare_client, board_id, encoder):
    fid = add_frame(client, board_id)
    for url, data in routes(board_id, fid):
        assert bare_client.post(url, data=data).status_code == 403
    assert encoder.calls == []


def test_same_origin_posts_still_work(client, board_id):
    fid = add_frame(client, board_id)
    for url, data in routes(board_id, fid):
        assert client.post(url, data=data).status_code == 302
