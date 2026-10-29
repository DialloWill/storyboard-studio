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
