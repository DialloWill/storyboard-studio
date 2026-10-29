from .base import ConfigurationError, ImageGenerator
from .comfy import ComfyGenerator
from .mock import MockGenerator


def get_generator(config):
    """Pick the generator named by config["GENERATOR"] ("mock" by default)."""
    name = (config.get("GENERATOR") or "mock").strip().lower()
    if name == "mock":
        return MockGenerator()
    if name == "comfy":
        return ComfyGenerator(config.get("COMFY_API_KEY", ""))
    raise ConfigurationError(
        f"Unknown GENERATOR {name!r}. Valid values are 'mock' and 'comfy'."
    )


__all__ = ["ConfigurationError", "ImageGenerator", "MockGenerator", "ComfyGenerator", "get_generator"]
