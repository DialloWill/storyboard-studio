"""Animated clips: per-frame clips and the whole-tape "Play tape" export.

Nothing here writes to storyboard.json except set_camera_move (an explicit user
pick). Clips live in data/<tape>/clips/ and are published atomically.
"""

from .. import fx, motion, presets, storage
from . import ai, fingerprint, render, settings
from .errors import (ClipError, ClipSourceError, EmptyTape, EncodeError,  # noqa: F401
                     EncoderUnavailable, TooManyFrames)


def effective_fx(frame):
    found = frame.get("fx")
    return found if presets.get_preset("fx", found) is not None else presets.DEFAULT_FX


def _png_path(data_dir, storyboard_id, frame):
    return storage.frame_image_path(data_dir, storyboard_id, frame.get("filename"))


def _frame_fp(png, frame):
    return fingerprint.frame_fingerprint(
        frame["id"], fingerprint.file_sha256(png), effective_fx(frame),
        motion.resolve_move(frame.get("camera_move")))


def _missing():
    return ClipSourceError("A frame image is missing from disk. Nothing was saved.")


def frame_state(data_dir, storyboard_id, frame):
    """("none" | "fresh" | "stale" | "missing", clip path or None) for one frame's clip."""
    png = _png_path(data_dir, storyboard_id, frame)
    if png is None:
        return "missing", None
    meta = storage.read_clip_meta(data_dir, storyboard_id, frame["id"])
    if meta is None:
        return "none", None
    path = storage.clip_file_path(data_dir, storyboard_id, frame["id"], meta)
    if path is not None and meta.get("fingerprint") == _frame_fp(png, frame):
        return "fresh", path
    return "stale", None


def _entry_fp(data_dir, storyboard_id, frame, png):
    """What one frame contributes to the tape fingerprint: its chosen clip's fingerprint.

    A procedural frame contributes exactly what it always did (so existing tapes stay
    fresh); a frame using a valid AI clip contributes "ai:" plus that clip's fingerprint.
    """
    chosen = ai.active_clip(data_dir, storyboard_id, frame)
    if chosen is not None:
        return "ai:" + chosen[1]["fingerprint"]
    return _frame_fp(png, frame)


def _tape_fp(data_dir, storyboard_id, frames):
    fps = []
    for frame in frames:
        png = _png_path(data_dir, storyboard_id, frame)
        if png is None:
            return None
        fps.append(_entry_fp(data_dir, storyboard_id, frame, png))
    return fingerprint.tape_fingerprint(fps)


def tape_frame_count(data_dir, storyboard_id, board):
    """Video frames Play tape will contain (AI clips vary in length), transitions included."""
    frames = storage.sorted_frames(board)
    total = 0
    for frame in frames:
        chosen = ai.active_clip(data_dir, storyboard_id, frame)
        total += chosen[1].get("frames", 0) if chosen else settings.FRAMES
    return total + max(0, len(frames) - 1) * settings.TRANSITION_FRAMES


def tape_state(data_dir, storyboard_id, board):
    """("empty" | "none" | "fresh" | "stale" | "missing", clip path or None) for the tape export."""
    frames = storage.sorted_frames(board)
    if not frames:
        return "empty", None
    current = _tape_fp(data_dir, storyboard_id, frames)
    if current is None:
        return "missing", None
    meta = storage.read_clip_meta(data_dir, storyboard_id, storage.TAPE_KEY)
    if meta is None:
        return "none", None
    path = storage.clip_file_path(data_dir, storyboard_id, storage.TAPE_KEY, meta)
    if path is not None and meta.get("fingerprint") == current:
        return "fresh", path
    return "stale", None


def _publish(data_dir, storyboard_id, key, encoder, frames, fp, info):
    """Encode to a temp file, then commit. Any failure removes the temp file."""
    tmp = storage.new_clip_tmp(data_dir, storyboard_id, key)
    try:
        encoder.encode(frames, tmp, settings.FPS, (settings.WIDTH, settings.HEIGHT))
        return storage.commit_clip(data_dir, storyboard_id, key, tmp, fp, info)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _info(frame_count):
    return {"fps": settings.FPS, "width": settings.WIDTH, "height": settings.HEIGHT,
            "frames": frame_count}


def _seed(frame):
    return fx.seed_from_frame_id(frame["id"])


def animate_frame(data_dir, storyboard_id, frame_id, encoder, move=None):
    """Render one frame's clip. Returns "fresh" if it was already up to date, else "rendered".

    `move` is an explicit user pick (already validated); it is saved on the frame
    only after the encoder and the image are confirmed usable.
    """
    board = storage.load_storyboard(data_dir, storyboard_id)
    frame = next((f for f in (board or {}).get("frames", []) if f.get("id") == frame_id), None)
    if frame is None:
        raise ClipSourceError("That frame no longer exists.")
    encoder.check_available()
    png = _png_path(data_dir, storyboard_id, frame)
    if png is None:
        raise _missing()
    if move is not None and move != frame.get("camera_move"):
        storage.set_camera_move(data_dir, storyboard_id, frame_id, move)
        frame = {**frame, "camera_move": move}
    fp = _frame_fp(png, frame)
    meta = storage.read_clip_meta(data_dir, storyboard_id, frame_id)
    if meta and meta.get("fingerprint") == fp and storage.clip_file_path(
            data_dir, storyboard_id, frame_id, meta):
        return "fresh"
    source = render.load_source(png)
    frames = render.frame_sequence(source, effective_fx(frame),
                                   motion.resolve_move(frame.get("camera_move")), _seed(frame))
    _publish(data_dir, storyboard_id, frame_id, encoder, frames, fp, _info(settings.FRAMES))
    return "rendered"


def export_tape(data_dir, storyboard_id, encoder, normalizer=None):
    """Render the whole tape in sorted_frames order. "fresh" if already up to date.

    Per frame: the AI clip when clip_source is "ai" and the clip is valid and not stale,
    otherwise the procedural clip's frames. `normalizer` is only needed for AI clips.
    """
    board = storage.load_storyboard(data_dir, storyboard_id)
    if board is None:
        raise ClipSourceError("That tape no longer exists.")
    frames = storage.sorted_frames(board)
    if not frames:
        raise EmptyTape("This tape has no frames yet. Add a frame, then play the tape.")
    if len(frames) > settings.MAX_EXPORT_FRAMES:
        raise TooManyFrames(f"Play tape supports up to {settings.MAX_EXPORT_FRAMES} frames.")
    encoder.check_available()
    pngs = []
    for frame in frames:
        png = _png_path(data_dir, storyboard_id, frame)
        if png is None:
            raise _missing()
        pngs.append(png)
    chosen = [ai.active_clip(data_dir, storyboard_id, f) for f in frames]
    if any(chosen):
        if normalizer is None:
            raise EncoderUnavailable("Video reader not available.")
        normalizer.check_available()
    fp = fingerprint.tape_fingerprint([_entry_fp(data_dir, storyboard_id, f, p)
                                       for p, f in zip(pngs, frames)])
    meta = storage.read_clip_meta(data_dir, storyboard_id, storage.TAPE_KEY)
    if meta and meta.get("fingerprint") == fp and storage.clip_file_path(
            data_dir, storyboard_id, storage.TAPE_KEY, meta):
        return "fresh"
    size = (settings.WIDTH, settings.HEIGHT)
    items = []
    for p, f, pick in zip(pngs, frames, chosen):
        if pick is not None:
            # Already VHS-treated at import: decode only, no second pass.
            items.append((render.Prerendered(lambda path=pick[0]: normalizer.read_frames(
                path, size, settings.FPS, settings.AI_MAX_SECONDS)), None, None, _seed(f)))
        else:
            items.append(((lambda p=p: render.load_source(p)), effective_fx(f),
                          motion.resolve_move(f.get("camera_move")), _seed(f)))
    _publish(data_dir, storyboard_id, storage.TAPE_KEY, encoder,
             render.tape_sequence(items), fp,
             _info(tape_frame_count(data_dir, storyboard_id, board)))
    return "rendered"
