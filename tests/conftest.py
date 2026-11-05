import re

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock"})


@pytest.fixture(autouse=True)
def _same_origin_by_default(monkeypatch):
    """Every test client sends a same-origin Origin header unless it opts out.

    The app rejects state-changing requests without one (see app/security.py).
    Patching Flask.test_client here also covers clients that tests build
    themselves, so no individual test needs editing. `bare_client` removes the
    default to prove the rejection.
    """
    from flask import Flask

    original = Flask.test_client

    def with_origin(self, *args, **kwargs):
        c = original(self, *args, **kwargs)
        c.environ_base["HTTP_ORIGIN"] = "http://localhost"
        return c

    monkeypatch.setattr(Flask, "test_client", with_origin)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def bare_client(app):
    c = app.test_client()
    c.environ_base.pop("HTTP_ORIGIN", None)
    return c


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
