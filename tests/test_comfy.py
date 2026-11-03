"""ComfyGenerator tests. The urllib opener is faked, so nothing touches the network."""

import io
import json
import urllib.error

import pytest
from PIL import Image

from app import create_app
from app.generators import comfy
from app.generators.base import ConfigurationError
from app.generators.comfy import ComfyError, ComfyGenerator
from conftest import frame_form, make_storyboard

KEY = "sk-test-SECRET-key-123"
SAMPLE = "https://cdn.example.com/signed/abc.png?sig=SIGSECRET"


def image_bytes(fmt="PNG", size=(64, 36)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 90)).save(buf, format=fmt)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, body=b"", headers=None):
        self._buf = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ready(url=SAMPLE):
    return FakeResponse(json.dumps({"status": "Ready", "result": {"sample": url}}).encode())


class FakeOpener:
    """Answers the API POST with `api`, and the image download with `download`.
    Either may be a response or an exception to raise."""

    def __init__(self, api=None, download=None):
        self.api = api if api is not None else ready()
        self.download = download if download is not None else FakeResponse(image_bytes())
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        result = self.api if request.get_method() == "POST" else self.download
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def opener(monkeypatch):
    fake = FakeOpener()
    monkeypatch.setattr(comfy, "_OPENER", fake)
    return fake


def use(monkeypatch, **kwargs):
    fake = FakeOpener(**kwargs)
    monkeypatch.setattr(comfy, "_OPENER", fake)
    return fake


def http_error(code, body=b""):
    return urllib.error.HTTPError(comfy.ENDPOINT, code, "x", {}, io.BytesIO(body))


def generate():
    return ComfyGenerator(KEY).generate("a neon rooftop")


def test_success_saves_valid_image(opener):
    png = generate()
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (64, 36)
    assert [r.get_method() for r in opener.requests] == ["POST", "GET"]
    assert opener.timeouts == [comfy.REQUEST_TIMEOUT, comfy.DOWNLOAD_TIMEOUT] == [300, 60]


def test_jpeg_download_is_converted_to_png(monkeypatch):
    use(monkeypatch, download=FakeResponse(image_bytes("JPEG")))
    assert Image.open(io.BytesIO(generate())).format == "PNG"


def test_request_body_and_headers(opener):
    ComfyGenerator(KEY).generate("a neon rooftop")
    post = opener.requests[0]
    assert post.full_url == "https://api.comfy.org/v2/models/bfl/flux-3-image"
    assert comfy.MODEL_ID in post.full_url
    body = json.loads(post.data)
    assert body == {"prompt": "a neon rooftop", "aspect_ratio": "16:9",
                    "resolution": "1k", "grounding": False}
    headers = {k.lower(): v for k, v in post.header_items()}
    assert headers["x-api-key"] == KEY
    assert headers["content-type"] == "application/json"
    assert len(headers["idempotency-key"]) == 36


def test_idempotency_key_is_fresh_per_call(monkeypatch):
    keys = set()
    for _ in range(2):
        fake = use(monkeypatch)
        generate()
        keys.add(dict((k.lower(), v) for k, v in fake.requests[0].header_items())["idempotency-key"])
    assert len(keys) == 2


def test_download_does_not_send_api_key(opener):
    generate()
    download = opener.requests[1]
    assert download.full_url == SAMPLE
    assert "x-api-key" not in {k.lower() for k, _ in download.header_items()}


def failing_cases():
    def api(response):
        return {"api": response}

    return {
        "moderated": api(FakeResponse(b'{"status": "Request Moderated"}')),
        "content_moderated": api(FakeResponse(b'{"status": "Content Moderated"}')),
        "error_status": api(FakeResponse(b'{"status": "Error"}')),
        "not_found": api(FakeResponse(b'{"status": "Task not found"}')),
        "pending": api(FakeResponse(b'{"status": "Pending"}')),
        "weird_status": api(FakeResponse(b'{"status": "Ready; key=sk-test-SECRET-key-123"}')),
        "no_sample": api(FakeResponse(b'{"status": "Ready", "result": {}}')),
        "not_json": api(FakeResponse(b"<html>nope</html>")),
        "401": api(http_error(401)),
        "402": api(http_error(402)),
        "402_credits": api(http_error(402, b'{"error_type": "insufficient_credits"}')),
        "422": api(http_error(422, b'{"error_type": "validation_error"}')),
        "429": api(http_error(429)),
        "500": api(http_error(500)),
        "timeout": api(TimeoutError("timed out")),
        "url_timeout": api(urllib.error.URLError(TimeoutError("timed out"))),
        "http_url": api(ready("http://cdn.example.com/a.png")),
        "file_url": api(ready("file:///etc/passwd")),
        "oversize_stream": {"download": FakeResponse(b"x" * (comfy.MAX_DOWNLOAD_BYTES + 1))},
        "oversize_header": {"download": FakeResponse(
            image_bytes(), {"Content-Length": str(comfy.MAX_DOWNLOAD_BYTES + 1)})},
        "not_image": {"download": FakeResponse(b"this is not an image")},
        "download_403": {"download": http_error(403)},
        "download_timeout": {"download": TimeoutError("timed out")},
    }


@pytest.mark.parametrize("name", list(failing_cases()))
def test_failures_are_clean_and_never_leak(monkeypatch, name):
    use(monkeypatch, **failing_cases()[name])
    with pytest.raises(ComfyError) as info:
        generate()
    for text in (str(info.value), repr(info.value)):
        assert KEY not in text
        assert "SIGSECRET" not in text
        assert "cdn.example.com" not in text
    assert info.value.__cause__ is None


@pytest.mark.parametrize("name, expected", [
    ("401", "401"), ("402", "insufficient credits"), ("402_credits", "[insufficient_credits]"),
    ("422", "422"), ("429", "429"), ("timeout", "timed out"), ("url_timeout", "timed out"),
    ("http_url", "not https"), ("file_url", "not https"), ("oversize_stream", "too large"),
    ("oversize_header", "too large"), ("not_image", "not a valid image"),
    ("pending", "Pending"),
])
def test_failure_messages(monkeypatch, name, expected):
    use(monkeypatch, **failing_cases()[name])
    with pytest.raises(ComfyError, match=expected.replace("[", r"\[").replace("]", r"\]")):
        generate()


def test_unlisted_server_text_is_not_echoed(monkeypatch):
    use(monkeypatch, api=http_error(422, b'{"error_type": "leak sk-test-SECRET-key-123"}'))
    with pytest.raises(ComfyError) as info:
        generate()
    assert str(info.value) == "Comfy rejected the input (422)"
    use(monkeypatch, api=FakeResponse(b'{"status": "weird text"}'))
    with pytest.raises(ComfyError) as info:
        generate()
    assert "weird" not in str(info.value)


def test_non_https_url_is_never_downloaded(monkeypatch):
    fake = use(monkeypatch, api=ready("http://cdn.example.com/a.png"))
    with pytest.raises(ComfyError):
        generate()
    assert len(fake.requests) == 1


def test_missing_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("COMFY_API_KEY", "")
    with pytest.raises(ConfigurationError, match="COMFY_API_KEY"):
        ComfyGenerator()
    with pytest.raises(ConfigurationError, match="COMFY_API_KEY"):
        ComfyGenerator("   ")


def test_key_read_from_environment(monkeypatch, opener):
    monkeypatch.setenv("COMFY_API_KEY", KEY)
    ComfyGenerator().generate("x")
    assert dict((k.lower(), v) for k, v in opener.requests[0].header_items())["x-api-key"] == KEY


def test_route_failure_is_502_and_saves_no_frame(monkeypatch, tmp_path):
    use(monkeypatch, api=http_error(401))
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path,
                      "GENERATOR": "comfy", "COMFY_API_KEY": KEY})
    client = app.test_client()
    board = make_storyboard(client)
    resp = client.post(f"/storyboards/{board}/frames", data=frame_form())
    assert resp.status_code == 502
    assert KEY.encode() not in resp.data
    assert not list(tmp_path.rglob("*.png"))


def test_route_success_applies_glitch_fx_to_real_image(monkeypatch, tmp_path):
    use(monkeypatch, download=FakeResponse(image_bytes("PNG", (320, 180))))
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path,
                      "GENERATOR": "comfy", "COMFY_API_KEY": KEY})
    client = app.test_client()
    board = make_storyboard(client)
    resp = client.post(f"/storyboards/{board}/frames", data=frame_form(fx="row-smear"))
    assert resp.status_code == 302
    assert len(list(tmp_path.rglob("*.png"))) == 1
