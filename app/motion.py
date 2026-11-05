"""Camera moves for animated clips: pure functions, no I/O.

A move is a crop window sliding over (or scaling within) the source image.
The window is always inside the image, so the clip never shows an edge.
"""

ZOOM = 1.12  # how far in the tightest crop goes (12% closer than the full frame)

MOVES = [
    {"id": "static", "name": "Static"},
    {"id": "zoom-in", "name": "Slow zoom in"},
    {"id": "zoom-out", "name": "Slow zoom out"},
    {"id": "pan-left", "name": "Pan left"},
    {"id": "pan-right", "name": "Pan right"},
    {"id": "tilt-up", "name": "Tilt up"},
    {"id": "tilt-down", "name": "Tilt down"},
]
MOVE_IDS = [m["id"] for m in MOVES]
MOVE_NAMES = {m["id"]: m["name"] for m in MOVES}

# Used for frames with no stored move, or a stored value no longer in the list.
DEFAULT_MOVE = "zoom-in"


def is_valid_move(value):
    return isinstance(value, str) and value in MOVE_NAMES


def resolve_move(value):
    """A usable move id: missing or unknown values read as the default."""
    return value if is_valid_move(value) else DEFAULT_MOVE


def smootherstep(t):
    """Ease in and out (zero velocity at both ends), t clamped to 0..1."""
    t = min(1.0, max(0.0, t))
    return t * t * t * (t * (6 * t - 15) + 10)


def window(move, t, src_w, src_h):
    """Crop box (x0, y0, x1, y1), floats, at progress t in 0..1; always inside the image."""
    move = resolve_move(move)
    e = smootherstep(t)
    tight = 1.0 / ZOOM
    if move == "zoom-in":
        scale = 1.0 - (1.0 - tight) * e
    elif move == "zoom-out":
        scale = tight + (1.0 - tight) * e
    elif move == "static":
        scale = 1.0
    else:
        scale = tight
    w, h = src_w * scale, src_h * scale
    x0 = (src_w - w) / 2
    y0 = (src_h - h) / 2
    if move == "pan-left":
        x0 = (src_w - w) * (1.0 - e)
    elif move == "pan-right":
        x0 = (src_w - w) * e
    elif move == "tilt-up":
        y0 = (src_h - h) * (1.0 - e)
    elif move == "tilt-down":
        y0 = (src_h - h) * e
    x0 = min(max(0.0, x0), src_w - w)
    y0 = min(max(0.0, y0), src_h - h)
    return (x0, y0, min(float(src_w), x0 + w), min(float(src_h), y0 + h))
