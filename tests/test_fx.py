import csv
import io
import json
import re

import numpy as np
import pytest
from PIL import Image

from app import fx, presets, storage
from conftest import frame_form

NON_NONE = [p["id"] for p in presets.FX if p["id"] != "none"]
DARK_TOLERANCE = 2  # max per-channel difference allowed for Sky Smear on a dark image


def synthetic(width=64, height=48, dark=False):
    """Seeded gradient + noise, bright in the upper half unless dark."""
    rng = np.random.default_rng(3)
    y, x = np.mgrid[0:height, 0:width]
    arr = np.stack([x * 4 % 256, y * 5 % 256, (x + y) * 3 % 256], -1)
    arr = arr + rng.integers(0, 30, arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    arr[: height // 2] = np.clip(arr[: height // 2].astype(int) // 2 + 150, 0, 255)
    arr[: height // 2, ::7] = 255
    if dark:
        arr = (arr // 8).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def pixels(image):
    return np.asarray(image)


def board_json(data_dir, board_id):
    return json.loads((data_dir / board_id / "storyboard.json").read_text(encoding="utf-8"))


def pngs(data_dir, board_id):
    return sorted((data_dir / board_id).glob("*.png"))


def csv_rows(client, board_id):
    resp = client.get(f"/storyboards/{board_id}/shotlist.csv")
    return list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))


def test_fx_presets_well_formed():
    ids = [p["id"] for p in presets.FX]
    assert len(ids) == len(set(ids))
    assert ids[0] == "none" and presets.DEFAULT_FX == "none"
    assert ids[1:] == ["row-smear", "prism-zoom", "signal-drip", "burst",
                       "band-shift", "tape-decay", "sky-smear"]
    for p in presets.FX:
        assert p["id"] and p["name"] and p["description"]
        assert "fragment" not in p
    assert set(ids) == set(fx.EFFECTS)


def test_none_is_pixel_identical():
    image = synthetic()
    out = fx.apply_fx(image, "none", 1)
    assert out is not image
    assert np.array_equal(pixels(out), pixels(image))


@pytest.mark.parametrize("fx_id", NON_NONE)
def test_effect_returns_rgb_same_size_and_changes_pixels(fx_id):
    image = synthetic()
    out = fx.apply_fx(image, fx_id, 12345)
    assert out.mode == "RGB" and out.size == image.size
    assert not np.array_equal(pixels(out), pixels(image))


@pytest.mark.parametrize("fx_id", NON_NONE)
def test_effect_is_deterministic_and_seed_sensitive(fx_id):
    image = synthetic()
    first = pixels(fx.apply_fx(image, fx_id, 1))
    assert np.array_equal(first, pixels(fx.apply_fx(image, fx_id, 1)))
    # A different seed must give different output (tried a few seeds so one
    # unlucky coincidence on a tiny image can't fail the test).
    others = [pixels(fx.apply_fx(image, fx_id, s)) for s in (2, 3, 4)]
    assert all(not np.array_equal(first, o) for o in others)


def test_effects_do_not_modify_input():
    image = synthetic()
    before = pixels(image).copy()
    for fx_id in NON_NONE:
        fx.apply_fx(image, fx_id, 5)
    assert np.array_equal(pixels(image), before)


def test_sky_smear_leaves_dark_image_alone():
    image = synthetic(dark=True)
    assert fx._luminance(pixels(image).astype(np.float32)).max() < fx.SKY_THRESHOLD
    out = pixels(fx.apply_fx(image, "sky-smear", 9)).astype(int)
    assert np.abs(out - pixels(image).astype(int)).max() <= DARK_TOLERANCE


def test_unknown_fx_raises():
    with pytest.raises(ValueError):
        fx.apply_fx(synthetic(), "nope", 1)


def test_effect_changing_size_is_rejected(monkeypatch):
    monkeypatch.setitem(fx.EFFECTS, "row-smear", lambda image, seed: image.resize((10, 10)))
    with pytest.raises(ValueError):
        fx.apply_fx(synthetic(), "row-smear", 1)


def test_seed_from_frame_id_is_stable():
    assert fx.seed_from_frame_id("0" * 31 + "a") == 10
    assert fx.seed_from_frame_id("f" * 32) < 2 ** 64


def test_fx_does_not_change_prompt(client, data_dir, board_id):
    client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(fx="burst"))
    a, b = board_json(data_dir, board_id)["frames"]
    assert a["prompt"] == b["prompt"]


def test_end_to_end_fx_changes_png(client, data_dir, board_id):
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(fx="none"))
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(fx="row-smear"))
    board = board_json(data_dir, board_id)
    assert [f["fx"] for f in board["frames"]] == ["none", "row-smear"]
    plain, smeared = (Image.open(data_dir / board_id / f["filename"]).convert("RGB")
                      for f in board["frames"])
    assert plain.size == smeared.size
    assert not np.array_equal(pixels(plain), pixels(smeared))
    assert "Row Smear" in client.get(f"/storyboards/{board_id}").data.decode()


def test_frame_seed_comes_from_its_id(client, data_dir, board_id):
    from app.generators.mock import MockGenerator
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(fx="band-shift"))
    frame = board_json(data_dir, board_id)["frames"][0]
    saved = Image.open(data_dir / board_id / frame["filename"]).convert("RGB")
    base = Image.open(io.BytesIO(MockGenerator().generate(frame["prompt"]))).convert("RGB")
    expected = fx.apply_fx(base, "band-shift", fx.seed_from_frame_id(frame["id"]))
    assert np.array_equal(pixels(saved), pixels(expected))


def test_effect_failure_gives_502_no_frame_no_png(client, data_dir, board_id, monkeypatch):
    def boom(image, seed):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(fx.EFFECTS, "burst", boom)
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(fx="burst"))
    assert resp.status_code == 502
    assert "kaboom" not in resp.data.decode()
    assert board_json(data_dir, board_id)["frames"] == []
    assert pngs(data_dir, board_id) == []


@pytest.mark.parametrize("bad", ["bogus", "", "ROW-SMEAR"])
def test_invalid_fx_gives_400_no_frame_no_png(client, data_dir, board_id, bad):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(fx=bad))
    assert resp.status_code == 400
    assert board_json(data_dir, board_id)["frames"] == []
    assert pngs(data_dir, board_id) == []


def test_missing_fx_field_means_none(client, data_dir, board_id):
    assert client.post(f"/storyboards/{board_id}/frames", data=frame_form()).status_code == 302
    assert board_json(data_dir, board_id)["frames"][0]["fx"] == "none"


def _inject(data_dir, board_id, **extra):
    path = data_dir / board_id / "storyboard.json"
    board = json.loads(path.read_text(encoding="utf-8"))
    frame = {"id": "f" * 32, "section": "intro", "scene": "Old", "camera": "vhs-camcorder",
             "shot": "close-up", "lighting": "neon", "prompt": "p",
             "filename": "0" * 32 + ".png", "created": "2026-01-01T00:00:00+00:00"}
    frame.update(extra)
    board["frames"].append(frame)
    path.write_text(json.dumps(board), encoding="utf-8")


@pytest.mark.parametrize("extra", [{}, {"fx": "removed-fx"}])
def test_missing_or_unknown_fx_renders_and_exports_none(client, data_dir, board_id, extra):
    _inject(data_dir, board_id, **extra)
    resp = client.get(f"/storyboards/{board_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "removed-fx" not in html
    settings = re.search(r'class="settings">(.*?)</p>', html, re.S).group(1)
    assert "None" not in settings
    rows = csv_rows(client, board_id)
    assert rows[1][rows[0].index("fx")] == "none"


def test_csv_header_fx_follows_direction(client, board_id):
    header = csv_rows(client, board_id)[0]
    assert header.index("fx") == header.index("direction") + 1


def test_csv_fx_is_formula_guarded(client, data_dir, board_id):
    from app.routes import _csv_safe
    assert _csv_safe("=cmd") == "'=cmd"
    _inject(data_dir, board_id, fx="=cmd")
    rows = csv_rows(client, board_id)
    assert not rows[1][rows[0].index("fx")].startswith("=")


def test_form_has_glitch_fx_select_after_direction(client, board_id):
    page = client.get(f"/storyboards/{board_id}").data.decode()
    assert 'name="fx"' in page and "Glitch FX" in page
    assert page.index('name="direction"') < page.index('name="fx"')


def test_banned_names_in_fx_descriptions():
    from test_direction import BANNED
    for p in presets.FX:
        text = " ".join(str(p[k]) for k in ("id", "name", "description")).lower()
        for term in BANNED:
            assert not re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text)


@pytest.mark.parametrize("bad", ["../" + "a" * 29, "A" * 32, "a" * 31, "a" * 33,
                                 "z" * 32, "", "a" * 32 + "\n", 5])
def test_add_frame_rejects_invalid_frame_id(data_dir, board_id, bad):
    fields = {"section": "intro", "scene": "s", "camera": "vhs-camcorder", "shot": "close-up",
              "lighting": "neon", "direction": "none", "fx": "none", "prompt": "p"}
    with pytest.raises(ValueError):
        storage.add_frame(data_dir, board_id, fields, b"png", frame_id=bad)
    assert board_json(data_dir, board_id)["frames"] == []
    assert list(data_dir.rglob("*.png")) == []
    assert [p.name for p in data_dir.iterdir()] == [board_id]
