"""Turn a still into a sequence of RGB frames (uint8 arrays). No encoding, no file writes."""

import numpy as np
from PIL import Image

from .. import fx, motion
from . import settings, vhs
from .errors import ClipSourceError

PEAK = 0.4  # fraction of the clip at which the glitch FX is strongest


def intensity(t):
    """FX strength 0..1 over the clip: starts low, builds to a peak, fades to clean."""
    if t < PEAK:
        return 0.1 + 0.9 * motion.smootherstep(t / PEAK)
    return 1.0 - motion.smootherstep((t - PEAK) / (1.0 - PEAK))


def load_source(path):
    """Open a still and cover-crop it to the working 16:9 size, or raise ClipSourceError."""
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ClipSourceError("A frame image could not be read. Nothing was saved.") from exc
    tw, th = settings.PRESCALE
    scale = max(tw / img.width, th / img.height)
    size = (max(tw, round(img.width * scale)), max(th, round(img.height * scale)))
    img = img.resize(size, Image.LANCZOS)
    left, top = (size[0] - tw) // 2, (size[1] - th) // 2
    return img.crop((left, top, left + tw, top + th))


def frame_sequence(source, fx_name, move, seed, n=settings.FRAMES):
    """Yield n frames: eased camera move, FX blended in and out, VHS pass on every frame."""
    sw, sh = source.size
    size = (settings.WIDTH, settings.HEIGHT)
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        clean = source.resize(size, Image.BICUBIC, box=motion.window(move, t, sw, sh))
        arr = np.asarray(clean)
        if fx_name != "none":
            a = intensity(t)
            glitched = np.asarray(fx.apply_fx(clean, fx_name, seed + i // 2))
            arr = np.rint(arr.astype(np.float32) * (1 - a)
                          + glitched.astype(np.float32) * a).astype(np.uint8)
        yield vhs.vhs_pass(arr, np.random.default_rng([seed, i]), t)


def transition_frames(last, first, seed, count=settings.TRANSITION_FRAMES):
    """VHS tracking-hit frames bridging one clip's last frame and the next one's first."""
    for j in range(1, count + 1):
        yield vhs.tracking_hit(last, first, j / (count + 1), np.random.default_rng([seed, 10_000 + j]))


def sequence(clips):
    """clips: iterable of (seed, frames_factory), in tape order; a factory returns an
    iterator of RGB arrays of any length (procedural clips are 45 frames, AI clips vary).

    Each clip is opened lazily, one at a time, so memory stays flat. A tracking-hit
    transition needs only the previous clip's last frame and the next one's first.
    """
    prev_last = None
    for seed, make in clips:
        gen = iter(make())
        first = next(gen)
        if prev_last is not None:
            yield from transition_frames(prev_last, first, seed)
        yield first
        last = first
        for frame in gen:
            last = frame
            yield frame
        prev_last = last


class Prerendered:
    """Stands in for a still in tape_sequence items: its factory yields finished frames
    (an imported AI clip, already given the VHS look), so no FX or camera move applies."""

    def __init__(self, factory):
        self.factory = factory


def tape_sequence(items):
    """items: iterable of (load_source_callable | Prerendered, fx_name, move, seed), in tape order."""
    def clip(load, fx_name, move, seed):
        if isinstance(load, Prerendered):
            return seed, load.factory
        return seed, lambda: frame_sequence(load(), fx_name, move, seed)

    return sequence(clip(*item) for item in items)
