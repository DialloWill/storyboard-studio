"""Comfy Cloud generator (stub).

Implemented at build night. Notes for that work:
- Base URL: https://cloud.comfy.org
- Auth header: X-API-Key
- Use API v2 (v1 is deprecated).
- 401 = invalid API key, 429 = inactive subscription, 402 = insufficient credits.

No HTTP calls are made yet. Never log or print the API key.
"""

import os

from .base import ConfigurationError, ImageGenerator


class ComfyGenerator(ImageGenerator):
    def __init__(self, api_key=None):
        if api_key is None:
            api_key = os.environ.get("COMFY_API_KEY", "")
        if not api_key or not api_key.strip():
            raise ConfigurationError(
                "COMFY_API_KEY is not set. Add it to your .env file to use GENERATOR=comfy."
            )
        self._api_key = api_key.strip()

    def generate(self, prompt: str) -> bytes:
        raise NotImplementedError("Comfy API v2 integration is implemented at build night")
