import io

import pytest
from PIL import Image

from app.generators import ComfyGenerator, ConfigurationError, MockGenerator, get_generator
from app.generators.base import ImageGenerator


def test_default_is_mock():
    assert isinstance(get_generator({}), MockGenerator)
    assert isinstance(get_generator({"GENERATOR": "mock"}), MockGenerator)


def test_unknown_generator_raises():
    with pytest.raises(ConfigurationError, match="Unknown GENERATOR"):
        get_generator({"GENERATOR": "bogus"})


def test_mock_png_is_1280x720():
    png = MockGenerator().generate("a test prompt " * 40)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (1280, 720)


def test_comfy_requires_key(monkeypatch):
    monkeypatch.setenv("COMFY_API_KEY", "")
    with pytest.raises(ConfigurationError, match="COMFY_API_KEY"):
        ComfyGenerator()
    with pytest.raises(ConfigurationError):
        ComfyGenerator("")
    with pytest.raises(ConfigurationError):
        get_generator({"GENERATOR": "comfy", "COMFY_API_KEY": ""})


def test_comfy_generate_not_implemented():
    gen = ComfyGenerator("test-key-not-real")
    assert isinstance(gen, ImageGenerator)
    with pytest.raises(NotImplementedError, match="implemented at build night"):
        gen.generate("x")


@pytest.mark.parametrize("scene", [
    "A singer — alone, under “neon” lights \U0001F3A4",
    "Café … ‘quiet’ 中文",
    "plain ascii scene",
])
def test_mock_drawn_text_is_ascii(monkeypatch, scene):
    from PIL import ImageDraw
    drawn = []
    real_text, real_multi = ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.multiline_text

    def spy_text(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return real_text(self, xy, text, *args, **kwargs)

    def spy_multi(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return real_multi(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy_text)
    monkeypatch.setattr(ImageDraw.ImageDraw, "multiline_text", spy_multi)
    png = MockGenerator().generate(f"Shot of {scene}, close-up, neon lighting")
    assert Image.open(io.BytesIO(png)).size == (1280, 720)
    assert drawn and all(t.isascii() for t in drawn)
    assert "NO SIGNAL - MOCK FRAME" in drawn


def test_mock_ascii_text_mapping():
    from app.generators.mock import ascii_text
    assert ascii_text("a — b “q” ’s") == 'a - b "q" \'s'
    assert ascii_text("café") == "cafe"
    assert ascii_text("hi \U0001F3A4") == "hi ?"
