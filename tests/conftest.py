import re

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock"})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def data_dir(app):
    return app.config["DATA_DIR"]


def make_storyboard(client, title="Neon Nights"):
    resp = client.post("/storyboards", data={"song_title": title})
    assert resp.status_code == 302
    return re.search(r"/storyboards/([0-9a-f]{32})$", resp.headers["Location"]).group(1)


def frame_form(**overrides):
    data = {"section": "intro", "scene": "A singer on a rooftop at midnight",
            "camera": "vhs-camcorder", "shot": "close-up", "lighting": "neon"}
    data.update(overrides)
    return data


@pytest.fixture
def board_id(client):
    return make_storyboard(client)
