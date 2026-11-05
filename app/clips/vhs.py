"""VHS treatment: scanlines, rolling tracking band, jitter, chroma bleed, noise.

Pure numpy. Input and output are uint8 (H, W, 3) arrays; all randomness comes
from the Generator passed in, so the same input and rng state give the same output.
"""

import numpy as np


def _to_u8(f):
    return np.clip(np.rint(f), 0, 255).astype(np.uint8)


def vhs_pass(arr, rng, t):
    """One frame of VHS look. t (0..1) is clip progress; it rolls the tracking band."""
    h, w, _ = arr.shape
    f = arr.astype(np.float32)

    f[::2] *= 0.88  # scanlines

    # Rolling tracking-noise band: brighter, noisy, sheared sideways.
    bh = max(4, h // 12)
    top = int((t * 1.7 % 1.0) * h)
    rows = (np.arange(bh) + top) % h
    band = f[rows] * 1.12 + rng.normal(0, 22, (bh, w, 3)).astype(np.float32)
    f[rows] = np.roll(band, int(rng.integers(-6, 7)), axis=1)

    # Horizontal jitter: a small whole-frame wobble plus per-row +/-1 px.
    shifts = rng.integers(-1, 2, h) + int(rng.integers(-2, 3))
    idx = (np.arange(w)[None, :] - shifts[:, None]) % w
    f = f[np.arange(h)[:, None], idx]

    # Chroma bleed: red and blue drift apart.
    f[..., 0] = np.roll(f[..., 0], 2, axis=1)
    f[..., 2] = np.roll(f[..., 2], -2, axis=1)

    f += rng.normal(0, 4, f.shape).astype(np.float32)  # light noise
    return _to_u8(f)


def tracking_hit(a, b, mix, rng):
    """A transition frame: a/b blended by mix, torn sideways in bands, noisy."""
    h, w, _ = a.shape
    f = a.astype(np.float32) * (1 - mix) + b.astype(np.float32) * mix
    for _ in range(int(rng.integers(4, 9))):
        bh = int(rng.integers(max(2, h // 30), max(3, h // 5)))
        top = int(rng.integers(0, h - bh + 1))
        f[top:top + bh] = np.roll(f[top:top + bh], int(rng.integers(-w // 6, w // 6 + 1)), axis=1)
    top = int(rng.integers(0, h - h // 10))
    f[top:top + h // 10] = f[top:top + h // 10] * 1.3 + 30
    f += rng.normal(0, 35, f.shape).astype(np.float32)
    return vhs_pass(_to_u8(f), rng, mix)
