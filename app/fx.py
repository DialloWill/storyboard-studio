"""Glitch FX: pixel-level post-processing applied after a generator returns.

Pure functions. Each effect takes an RGB PIL Image and an integer seed and
returns a new RGB PIL Image of the same size. All randomness comes from a
numpy Generator built from the seed, so the same input and seed always give
the same output. Everything is vectorized; the only Python loops run over a
handful of bands or tiles, never over pixels.
"""

import io

import numpy as np
from PIL import Image

SKY_THRESHOLD = 0.55   # luminance (0..1) above which Sky Smear starts to apply
SKY_SOFTNESS = 0.15    # width of the blend ramp above the threshold


def seed_from_frame_id(frame_id):
    """Stable 64-bit seed from a frame's uuid hex."""
    return int(frame_id, 16) % (2 ** 64)


def _rng(seed):
    return np.random.default_rng(seed)


def _to_array(image):
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _to_image(array):
    return Image.fromarray(np.ascontiguousarray(array, dtype=np.uint8), "RGB")


def _luminance(arr):
    """Rec. 601 luminance scaled to 0..1."""
    return (arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114) / 255.0


def _bands(rng, height, count, min_h, max_h):
    """Random (top, bottom) row ranges."""
    out = []
    for _ in range(count):
        h = int(rng.integers(min_h, max_h + 1))
        top = int(rng.integers(0, max(1, height - h + 1)))
        out.append((top, min(height, top + h)))
    return out


def _smear_rows(arr, rng):
    """Stretch each row of a few random bands sideways from a sampled column."""
    h, w, _ = arr.shape
    out = arr.copy()
    count = int(rng.integers(3, 8))
    for top, bottom in _bands(rng, h, count, max(2, h // 20), max(3, h // 6)):
        col = int(rng.integers(0, w))
        direction = int(rng.integers(0, 2))
        band = out[top:bottom]
        if direction:   # smear to the right of the sampled column
            band[:, col:] = band[:, col:col + 1]
        else:           # smear to the left
            band[:, :col + 1] = band[:, col:col + 1]
    return out


def _shift_channel(arr, channel, dx):
    """Horizontally shift one channel by dx pixels, wrapping at the edges."""
    arr[..., channel] = np.roll(arr[..., channel], dx, axis=1)


def row_smear(image, seed):
    rng = _rng(seed)
    arr = _smear_rows(_to_array(image), rng)
    w = arr.shape[1]
    d = max(1, w // 64)
    _shift_channel(arr, 0, d)
    _shift_channel(arr, 2, -d)
    return _to_image(arr)


def _sample(arr, ys, xs):
    """Nearest-neighbor gather with clamped coordinates."""
    h, w = arr.shape[:2]
    return arr[np.clip(np.rint(ys).astype(np.intp), 0, h - 1),
               np.clip(np.rint(xs).astype(np.intp), 0, w - 1)]


def prism_zoom(image, seed):
    rng = _rng(seed)
    arr = _to_array(image)
    h, w, _ = arr.shape
    cy, cx = (h - 1) / 2, (w - 1) / 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dy, dx = yy - cy, xx - cx
    radius = np.sqrt(dy * dy + dx * dx)
    radial = radius / max(radius.max(), 1.0)          # 0 at center, 1 at corners
    strength = float(rng.uniform(0.06, 0.10))
    # Per-channel zoom factors: R samples a little outward, B a little inward.
    spread = float(rng.uniform(0.012, 0.022))
    channel_scale = (1.0 - spread, 1.0, 1.0 + spread)
    steps = 5
    flat = [np.ascontiguousarray(arr[..., c]).ravel() for c in range(3)]
    out = np.zeros((h, w, 3), dtype=np.float32)
    for c, base in enumerate(channel_scale):
        acc = np.zeros(h * w, dtype=np.float32)
        for s in range(steps):
            # Zoom blur samples along the ray; reach grows with distance from center.
            zoom = (base * (1.0 - strength * radial * s / (steps - 1))).astype(np.float32)
            sy = np.clip(np.rint(cy + dy * zoom), 0, h - 1).astype(np.int32)
            sx = np.clip(np.rint(cx + dx * zoom), 0, w - 1).astype(np.int32)
            acc += np.take(flat[c], (sy * w + sx).ravel())
        out[..., c] = (acc / steps).reshape(h, w)
    return _to_image(np.clip(out, 0, 255))


def signal_drip(image, seed):
    rng = _rng(seed)
    arr = _to_array(image)
    h, w, _ = arr.shape
    lum = _luminance(arr)
    threshold = float(rng.uniform(0.55, 0.7))
    trigger = lum > threshold
    # Only a subset of triggering pixels start a drip.
    trigger &= rng.random((h, w)) < 0.12
    length = rng.integers(h // 8, max(h // 8 + 1, h // 2), size=(h, w))
    rows = np.arange(h)[:, None]
    # Row of the most recent trigger at or above each pixel (-1 if none).
    last = np.maximum.accumulate(np.where(trigger, rows, -1), axis=0)
    src = np.clip(last, 0, h - 1)
    reach = np.take_along_axis(length, src, axis=0)
    active = (last >= 0) & (rows - last <= reach)
    cols = np.arange(w)[None, :]
    dripped = arr[src, cols]
    return _to_image(np.where(active[..., None], dripped, arr))


def burst(image, seed):
    rng = _rng(seed)
    arr = _to_array(image)
    h, w, _ = arr.shape
    cy, cx = (h - 1) / 2, (w - 1) / 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dy, dx = yy - cy, xx - cx
    radius = np.sqrt(dy * dy + dx * dx)
    angle = np.arctan2(dy, dx)
    max_r = float(radius.max())
    inner = max_r * float(rng.uniform(0.25, 0.35))
    rays = int(rng.integers(36, 72))
    ring = max(2.0, max_r / int(rng.integers(10, 18)))
    # Coarse blocks: quantize the angle into rays and the radius into rings.
    q_angle = np.floor((angle + np.pi) / (2 * np.pi) * rays) / rays * 2 * np.pi - np.pi
    q_angle = q_angle + np.pi / rays
    # Every ray gets its own random starting ring so the smear is ragged.
    start = inner + ring * rng.integers(0, 3, size=rays)[
        np.minimum(((angle + np.pi) / (2 * np.pi) * rays).astype(np.intp), rays - 1)]
    # Beyond the start radius, advance only 30% as fast, in coarse steps: an outward stretch.
    sample_r = np.where(radius > start, start + np.floor((radius - start) / ring) * ring * 0.3, radius)
    smeared = _sample(arr, cy + np.sin(q_angle) * sample_r, cx + np.cos(q_angle) * sample_r)
    outside = (radius > start)[..., None]
    return _to_image(np.where(outside, smeared, arr))


def band_shift(image, seed):
    rng = _rng(seed)
    arr = _to_array(image)
    h, w, _ = arr.shape
    out = arr.copy()
    for top, bottom in _bands(rng, h, int(rng.integers(5, 10)), max(2, h // 25), max(3, h // 8)):
        if rng.random() < 0.7:
            out[top:bottom] = np.roll(out[top:bottom], int(rng.integers(-w // 6, w // 6 + 1)) or 1, axis=1)
    for top, bottom in _bands(rng, h, int(rng.integers(2, 5)), 1, max(2, h // 30)):
        d = int(rng.integers(max(1, w // 40), max(2, w // 12)))
        thin = out[top:bottom]
        thin[..., 0] = np.roll(thin[..., 0], d, axis=1)
        thin[..., 2] = np.roll(thin[..., 2], -d, axis=1)
    return _to_image(out)


def tape_decay(image, seed):
    rng = _rng(seed)
    arr = _to_array(image)
    h, w, _ = arr.shape
    current = _to_image(arr)
    for _ in range(int(rng.integers(3, 5))):
        buffer = io.BytesIO()
        current.save(buffer, format="JPEG", quality=int(rng.integers(6, 16)))
        buffer.seek(0)
        current = Image.open(buffer).convert("RGB")
    out = np.array(current)
    # Coarse macroblocking on random tiles: downscale then upscale by blocks.
    for _ in range(int(rng.integers(4, 9))):
        th = int(rng.integers(max(4, h // 10), max(5, h // 3)))
        tw = int(rng.integers(max(4, w // 10), max(5, w // 3)))
        y = int(rng.integers(0, max(1, h - th + 1)))
        x = int(rng.integers(0, max(1, w - tw + 1)))
        block = int(rng.integers(4, 12))
        tile = out[y:y + th, x:x + tw]
        small = tile[::block, ::block]
        tile[:] = np.repeat(np.repeat(small, block, axis=0), block, axis=1)[:tile.shape[0], :tile.shape[1]]
    # Light posterize: keep the top 5 bits.
    out = out & np.uint8(0xF8)
    # Faint offset ghost of the original.
    ghost = np.roll(arr, (int(rng.integers(1, 4)), max(2, w // 40)), axis=(0, 1))
    blended = out.astype(np.float32) * 0.82 + ghost.astype(np.float32) * 0.18
    return _to_image(np.clip(blended, 0, 255))


def _box_blur(mask, radius):
    """Separable box blur via cumulative sums; radius in pixels."""
    k = 2 * radius + 1
    for axis in (0, 1):
        padded = np.pad(mask, [(radius, radius) if a == axis else (0, 0) for a in (0, 1)], mode="edge")
        csum = np.cumsum(padded, axis=axis, dtype=np.float64)
        csum = np.concatenate([np.zeros_like(np.take(csum, [0], axis=axis)), csum], axis=axis)
        hi = np.take(csum, range(k, csum.shape[axis]), axis=axis)
        lo = np.take(csum, range(0, csum.shape[axis] - k), axis=axis)
        mask = ((hi - lo) / k).astype(np.float32)
    return mask


def sky_smear(image, seed):
    rng = _rng(seed)
    arr = _to_array(image)
    smeared = _smear_rows(arr, rng).astype(np.float32)
    d = max(1, arr.shape[1] // 64)
    smeared[..., 0] = np.roll(smeared[..., 0], d, axis=1)
    smeared[..., 2] = np.roll(smeared[..., 2], -d, axis=1)
    lum = _luminance(arr)
    mask = np.clip((lum - SKY_THRESHOLD) / SKY_SOFTNESS, 0.0, 1.0).astype(np.float32)
    mask = _box_blur(mask, max(1, min(arr.shape[:2]) // 40))
    # Blurring can bleed the mask into dark areas; keep it exactly zero below the threshold.
    mask = np.where(lum <= SKY_THRESHOLD - SKY_SOFTNESS, 0.0, mask)[..., None]
    blended = arr.astype(np.float32) * (1 - mask) + smeared * mask
    return _to_image(np.clip(np.rint(blended), 0, 255))


def _none(image, seed):
    return image.convert("RGB").copy()


EFFECTS = {
    "none": _none,
    "row-smear": row_smear,
    "prism-zoom": prism_zoom,
    "signal-drip": signal_drip,
    "burst": burst,
    "band-shift": band_shift,
    "tape-decay": tape_decay,
    "sky-smear": sky_smear,
}


def apply_fx(image, fx_id, seed):
    """Apply an effect by id. Returns a new RGB image of the same size."""
    effect = EFFECTS.get(fx_id)
    if effect is None:
        raise ValueError(f"Unknown fx: {fx_id!r}")
    result = effect(image.convert("RGB"), seed)
    if result.mode != "RGB" or result.size != image.size:
        raise ValueError(f"fx {fx_id!r} changed the image mode or size")
    return result
