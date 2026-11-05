import numpy as np
import pytest
from PIL import Image

from app import motion
from app.clips import render, settings, vhs
from app.clips.errors import ClipSourceError

SEED = 0xABCDEF


@pytest.fixture(scope="module")
def source():
    rng = np.random.default_rng(1)
    base = rng.integers(0, 255, (72, 128, 3), dtype=np.uint8)
    return Image.fromarray(base, "RGB").resize(settings.PRESCALE, Image.BICUBIC)


def run(source, fx="none", move="zoom-in", seed=SEED, n=6):
    return list(render.frame_sequence(source, fx, move, seed, n))


def test_frame_count_dimensions_and_dtype(source):
    frames = run(source, n=7)
    assert len(frames) == 7
    for f in frames:
        assert f.shape == (settings.HEIGHT, settings.WIDTH, 3)
        assert f.dtype == np.uint8
    assert settings.FRAMES == 45 and settings.FPS == 15


def test_intensity_starts_low_peaks_then_fades_to_clean():
    assert render.intensity(0.0) == pytest.approx(0.1)
    assert render.intensity(render.PEAK) == pytest.approx(1.0)
    assert render.intensity(1.0) == pytest.approx(0.0)
    ts = np.linspace(0, 1, 101)
    values = [render.intensity(float(t)) for t in ts]
    assert max(values) == pytest.approx(1.0)
    assert all(0 <= v <= 1 for v in values)
    up = [v for t, v in zip(ts, values) if t <= render.PEAK]
    down = [v for t, v in zip(ts, values) if t >= render.PEAK]
    assert up == sorted(up) and down == sorted(down, reverse=True)


def test_vhs_changes_pixels_but_keeps_shape_and_dtype():
    arr = np.full((settings.HEIGHT, settings.WIDTH, 3), 120, dtype=np.uint8)
    out = vhs.vhs_pass(arr, np.random.default_rng(3), 0.3)
    assert out.shape == arr.shape and out.dtype == np.uint8
    assert not np.array_equal(out, arr)
    assert arr.max() == 120 and arr.min() == 120  # the input is not modified


def test_fx_none_still_moves_and_static_still_gets_vhs(source, monkeypatch):
    # Isolate camera motion by turning the VHS pass into a no-op.
    monkeypatch.setattr(render.vhs, "vhs_pass", lambda arr, rng, t: arr)
    moving = run(source, "none", "zoom-in")
    assert not np.array_equal(moving[0], moving[-1])
    static = run(source, "none", "static")
    assert all(np.array_equal(static[0], f) for f in static)
    monkeypatch.undo()
    # With the real VHS pass, a static clip still changes: noise differs per frame
    # and every frame differs from the clean crop.
    treated = run(source, "none", "static")
    clean = np.asarray(source.resize((settings.WIDTH, settings.HEIGHT), Image.BICUBIC))
    assert not np.array_equal(treated[0], treated[1])
    assert not np.array_equal(treated[0], clean)


def test_fx_builds_in_and_fades_out(source):
    with_fx = run(source, "row-smear", "static")
    without = run(source, "none", "static")
    assert not np.array_equal(with_fx[2], without[2])      # FX visible mid-clip
    assert np.array_equal(with_fx[-1], without[-1])        # intensity 0 at the end: clean again


def test_determinism_and_seed_sensitivity(source):
    a = run(source, "prism-zoom", "pan-left")
    b = run(source, "prism-zoom", "pan-left")
    assert all(np.array_equal(x, y) for x, y in zip(a, b))
    c = run(source, "prism-zoom", "pan-left", seed=SEED + 1)
    assert not all(np.array_equal(x, y) for x, y in zip(a, c))


def test_unknown_move_renders_like_the_default(source):
    a = run(source, "none", "does-not-exist")
    b = run(source, "none", motion.DEFAULT_MOVE)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))


def test_load_source_cover_crops_real_sized_frames(tmp_path):
    path = tmp_path / "f.png"
    Image.new("RGB", (1360, 768), (200, 30, 90)).save(path)
    assert render.load_source(path).size == settings.PRESCALE


def test_load_source_unreadable_file_is_a_friendly_error(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not a png")
    with pytest.raises(ClipSourceError):
        render.load_source(path)


def test_tape_sequence_inserts_transitions_between_clips_only(source, monkeypatch):
    def stub(src, fx, move, seed, n=settings.FRAMES):
        for i in range(3):
            yield np.full((settings.HEIGHT, settings.WIDTH, 3), 10 * (seed + 1) + i, dtype=np.uint8)

    monkeypatch.setattr(render, "frame_sequence", stub)
    items = [(lambda: source, "none", "static", s) for s in range(3)]
    frames = list(render.tape_sequence(items))
    assert len(frames) == 3 * 3 + 2 * settings.TRANSITION_FRAMES
    assert frames[0][0, 0, 0] != frames[3 + settings.TRANSITION_FRAMES][0, 0, 0]
    assert list(render.tape_sequence([])) == []
