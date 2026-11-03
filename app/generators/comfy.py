"""Comfy generator: calls bfl/flux-3-image through the Comfy Router (synchronous).

The Router returns a signed, expiring image URL. It is downloaded immediately and
re-encoded as PNG; the URL is never stored. Error messages are built only from
fixed text, status codes and allowlisted values, so the API key and any other
server-supplied text can never reach a log line or an error page.
"""

import io
import json
import os
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from PIL import Image

from .base import ConfigurationError, ImageGenerator

MODEL_ID = "bfl/flux-3-image"
ENDPOINT = f"https://api.comfy.org/v2/models/{MODEL_ID}"
REQUEST_TIMEOUT = 300  # seconds; the Router holds the connection while it renders
DOWNLOAD_TIMEOUT = 60  # seconds
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024  # API JSON bodies are tiny; cap what we read

# Server-supplied text is only ever echoed if it is one of these exact values.
ALLOWED_ERROR_TYPES = {"insufficient_credits", "invalid_api_key", "rate_limited", "validation_error"}
KNOWN_STATUSES = {"Request Moderated", "Content Moderated", "Error", "Task not found", "Pending"}

_HTTP_MESSAGES = {
    401: "Comfy rejected the API key (401)",
    402: "Comfy account has insufficient credits (402)",
    422: "Comfy rejected the input (422)",
    429: "Comfy subscription or rate limit problem (429)",
}


class ComfyError(RuntimeError):
    """A failed Comfy request. The message never contains the key or server text."""


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise ComfyError("Comfy redirected to a non-https URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirect)


def _read_limited(response, limit):
    """Read at most `limit` bytes; raise if the body is larger."""
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ComfyError("Comfy response was too large")
    return data


def _http_error_message(exc):
    message = _HTTP_MESSAGES.get(exc.code, f"Comfy returned HTTP {exc.code}")
    try:
        error_type = json.loads(exc.read(4096)).get("error_type")
    except Exception:
        error_type = None
    if isinstance(error_type, str) and error_type in ALLOWED_ERROR_TYPES:
        if error_type == "insufficient_credits" and exc.code != 402:
            message = _HTTP_MESSAGES[402]
        message += f" [{error_type}]"
    return message


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
        sample_url = self._request_sample_url(prompt)
        return self._download_png(sample_url)

    def _request_sample_url(self, prompt):
        body = json.dumps({
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "resolution": "1k",
            "grounding": False,  # True lets the model web-search before generating
        }).encode("utf-8")
        request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "X-API-Key": self._api_key,
            "Idempotency-Key": str(uuid.uuid4()),  # fresh per call: a retry is a new generation
            "Content-Type": "application/json",
        })
        try:
            with _OPENER.open(request, timeout=REQUEST_TIMEOUT) as response:
                payload = json.loads(_read_limited(response, MAX_RESPONSE_BYTES))
        except urllib.error.HTTPError as exc:
            raise ComfyError(_http_error_message(exc)) from None
        except (TimeoutError, OSError):  # URLError and socket.timeout are OSErrors
            raise ComfyError("Comfy request timed out or could not connect") from None
        except ValueError:
            raise ComfyError("Comfy returned an unreadable response") from None

        if not isinstance(payload, dict):
            raise ComfyError("Comfy returned an unexpected response")
        status = payload.get("status")
        if status != "Ready":
            shown = f": {status}" if status in KNOWN_STATUSES else ""
            raise ComfyError(f"Comfy did not return an image{shown}")
        result = payload.get("result")
        sample = result.get("sample") if isinstance(result, dict) else None
        if not isinstance(sample, str):
            raise ComfyError("Comfy response had no image URL")
        parsed = urlparse(sample)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ComfyError("Comfy image URL is not https")
        return sample

    def _download_png(self, url):
        # No API key on this request: the URL is signed and may be on another host.
        try:
            with _OPENER.open(urllib.request.Request(url), timeout=DOWNLOAD_TIMEOUT) as response:
                length = response.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > MAX_DOWNLOAD_BYTES:
                    raise ComfyError("Comfy image is too large")
                data = _read_limited(response, MAX_DOWNLOAD_BYTES)
        except urllib.error.HTTPError as exc:
            raise ComfyError(f"Comfy image download failed (HTTP {exc.code})") from None
        except (TimeoutError, OSError):
            raise ComfyError("Comfy image download timed out or failed") from None

        try:
            image = Image.open(io.BytesIO(data))
            image.load()  # full decode; verify() alone misses truncated data
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
        except Exception:  # not an image, truncated, or a decompression bomb
            raise ComfyError("Comfy download was not a valid image") from None
        return buffer.getvalue()
