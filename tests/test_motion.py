import numpy as np
import pytest

from app import motion

W, H = 1280, 720
TS = np.linspace(0, 1, 41)


@pytest.mark.parametrize("move", motion.MOVE_IDS)
def test_window_stays_inside_the_image_for_every_move(move):
    for t in TS:
        x0, y0, x1, y1 = motion.window(move, float(t), W, H)
        assert 0 <= x0 < x1 <= W
        assert 0 <= y0 < y1 <= H
        assert (x1 - x0) / (y1 - y0) == pytest.approx(W / H)  # 16:9 is preserved


def test_smootherstep_is_clamped_monotone_and_eased():
    assert motion.smootherstep(-1) == 0
    assert motion.smootherstep(2) == 1
    values = [motion.smootherstep(float(t)) for t in TS]
    assert values == sorted(values)
    assert motion.smootherstep(0.05) < 0.05  # slow start
    assert motion.smootherstep(0.5) == pytest.approx(0.5)


def test_directions():
    first = {m: motion.window(m, 0.0, W, H) for m in motion.MOVE_IDS}
    last = {m: motion.window(m, 1.0, W, H) for m in motion.MOVE_IDS}
    assert first["static"] == last["static"] == (0, 0, W, H)
    assert (first["zoom-in"][2] - first["zoom-in"][0]) > (last["zoom-in"][2] - last["zoom-in"][0])
    assert (first["zoom-out"][2] - first["zoom-out"][0]) < (last["zoom-out"][2] - last["zoom-out"][0])
    assert last["pan-left"][0] < first["pan-left"][0]
    assert last["pan-right"][0] > first["pan-right"][0]
    assert last["tilt-up"][1] < first["tilt-up"][1]
    assert last["tilt-down"][1] > first["tilt-down"][1]


@pytest.mark.parametrize("bad", [None, "", "spin", "ZOOM-IN", 3, "zoom-in\n"])
def test_missing_or_unknown_move_falls_back_to_default(bad):
    assert motion.resolve_move(bad) == motion.DEFAULT_MOVE
    assert not motion.is_valid_move(bad)
    assert motion.window(bad, 0.5, W, H) == motion.window(motion.DEFAULT_MOVE, 0.5, W, H)


def test_every_listed_move_is_valid():
    for move in motion.MOVE_IDS:
        assert motion.is_valid_move(move)
        assert motion.resolve_move(move) == move
