"""Imported AI clips: video made elsewhere (Kaggle, Comfy, anything) for a frame's still.

An import decodes the untrusted upload, gives it the tape's VHS look once, and encodes
it to the clip spec. The result is stored beside the procedural clips as
clips/<frame_id>.ai.<fp12>.mp4 plus a <frame_id>.ai.json commit marker that records
the sha256 of the frame PNG at import time. If that PNG ever changes, the AI clip is
stale and is never used.
"""

import numpy as np

from .. import fx, storage
from . import fingerprint, settings, vhs
from .errors import ClipSourceError, InvalidClip

TOO_SHORT = "That video is too short. Clips must be at least half a second long."


def clip_source(frame):
    """Which clip Play tape wants for this frame. A missing field means procedural."""
    return "ai" if frame.get("clip_source") == "ai" else "procedural"


def _png(data_dir, storyboard_id, frame):
    return storage.frame_image_path(data_dir, storyboard_id, frame.get("filename"))


def ai_state(data_dir, storyboard_id, frame):
    """("none" | "fresh" | "stale" | "missing", clip path or None, meta or None).

    fresh   the marker, the video file and the frame PNG all still match
    stale   the PNG (or the video file) differs from what the import recorded
    missing the frame's picture is gone
    """
    png = _png(data_dir, storyboard_id, frame)
    key = storage.ai_key(frame["id"])
    meta = storage.read_clip_meta(data_dir, storyboard_id, key)
    if meta is None:
        return "none", None, None
    if png is None:
        return "missing", None, meta
    path = storage.clip_file_path(data_dir, storyboard_id, key, meta)
    if path is None:
        return "stale", None, meta
    png_sha = fingerprint.file_sha256(png)
    clip_sha = fingerprint.file_sha256(path)
    expected = fingerprint.ai_fingerprint(frame["id"], png_sha, clip_sha)
    if (meta.get("png_sha256") == png_sha and meta.get("clip_sha256") == clip_sha
            and meta.get("fingerprint") == expected):
        return "fresh", path, meta
    return "stale", None, meta


def active_clip(data_dir, storyboard_id, frame):
    """(path, meta) of the AI clip Play tape must use for this frame, or None."""
    if clip_source(frame) != "ai":
        return None
    state, path, meta = ai_state(data_dir, storyboard_id, frame)
    return (path, meta) if state == "fresh" else None


def badge(data_dir, storyboard_id, frame):
    """Storyboard-page label: "ai" | "ai-stale" | "procedural"."""
    if clip_source(frame) != "ai":
        return "procedural"
    return "ai" if ai_state(data_dir, storyboard_id, frame)[0] == "fresh" else "ai-stale"


def _look(frames, frame_id, counter):
    """VHS pass on every decoded frame, seeded from the frame id like the procedural clips.

    `t` rolls the tracking band. Procedural clips use progress over a fixed 3 s; AI clips
    have any length and stream without buffering, so progress is measured in seconds
    against the same 3 s cycle, which keeps the band moving at the same speed.
    """
    seed = fx.seed_from_frame_id(frame_id)
    cycle = settings.FPS * settings.DURATION
    for i, frame in enumerate(frames):
        counter["n"] = i + 1
        yield vhs.vhs_pass(np.asarray(frame), np.random.default_rng([seed, i]), (i / cycle) % 1.0)
    if counter["n"] < settings.AI_MIN_FRAMES:
        raise InvalidClip(TOO_SHORT)


def import_clip(data_dir, storyboard_id, frame_id, src, encoder, normalizer):
    """Normalize the video at `src` and store it as the frame's AI clip; selects it.

    Raises ClipSourceError (frame gone), InvalidClip (bad, too short or too slow) or an
    encoder error. Nothing is committed unless every step succeeded.
    """
    board = storage.load_storyboard(data_dir, storyboard_id)
    frame = next((f for f in (board or {}).get("frames", []) if f.get("id") == frame_id), None)
    if frame is None:
        raise ClipSourceError("That frame no longer exists.")
    png = _png(data_dir, storyboard_id, frame)
    if png is None:
        raise ClipSourceError("A frame image is missing from disk. Nothing was saved.")
    encoder.check_available()
    normalizer.check_available()
    png_sha = fingerprint.file_sha256(png)
    size = (settings.WIDTH, settings.HEIGHT)
    key = storage.ai_key(frame_id)
    tmp = storage.new_clip_tmp(data_dir, storyboard_id, key)
    counter = {"n": 0}
    try:
        decoded = normalizer.read_frames(src, size, settings.FPS, settings.AI_MAX_SECONDS)
        encoder.encode(_look(decoded, frame_id, counter), tmp, settings.FPS, size)
        clip_sha = fingerprint.file_sha256(tmp)
        fp = fingerprint.ai_fingerprint(frame_id, png_sha, clip_sha)
        meta = storage.commit_clip(data_dir, storyboard_id, key, tmp, fp, {
            "fps": settings.FPS, "width": settings.WIDTH, "height": settings.HEIGHT,
            "frames": counter["n"], "png_sha256": png_sha, "clip_sha256": clip_sha})
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    storage.set_clip_source(data_dir, storyboard_id, frame_id, "ai")
    return meta
