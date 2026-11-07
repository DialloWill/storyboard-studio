"""Fingerprints: a clip is fresh only if its stored fingerprint equals the current one.

A frame's fingerprint covers everything that changes the pixels: the PNG's
actual bytes, its FX, its camera move, the frame id (the seed), and the render
settings. A tape's covers the ordered frame fingerprints, so adding, removing
or reordering frames changes it. Renaming the tape changes neither.
"""

import hashlib
import os

from . import settings

_sha_cache = {}


def file_sha256(path):
    """sha256 of a file's bytes, cached by (path, size, mtime) so page renders stay cheap."""
    st = os.stat(path)
    key = (str(path), st.st_size, st.st_mtime_ns)
    digest = _sha_cache.get(key)
    if digest is None:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        if len(_sha_cache) > 1024:
            _sha_cache.clear()
        _sha_cache[key] = digest
    return digest


def _digest(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def frame_fingerprint(frame_id, png_sha256, fx_name, move):
    return _digest("frame", settings.CLIP_VERSION, settings.WIDTH, settings.HEIGHT,
                   settings.FPS, settings.FRAMES, frame_id, png_sha256, fx_name, move)


def tape_fingerprint(frame_fingerprints):
    return _digest("tape", settings.CLIP_VERSION, settings.TRANSITION_FRAMES,
                   *frame_fingerprints)


def ai_fingerprint(frame_id, png_sha256, clip_sha256):
    """An imported AI clip: tied to the frame's PNG at import time and to the clip's own bytes."""
    return _digest("ai", settings.CLIP_VERSION, settings.WIDTH, settings.HEIGHT,
                   settings.FPS, frame_id, png_sha256, clip_sha256)
