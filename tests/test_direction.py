import csv
import io
import json
import re

import pytest

from app import presets
from app.prompt import build_prompt
from conftest import frame_form

ORIGINAL_SHOTS = {
    "close-up": "tight close-up framing on the face, shallow focus, eyes in sharp detail, "
                "background melting into soft bokeh",
    "wide-shot": "wide establishing shot, subject small within a vast environment, "
                 "strong leading lines and deep layered space",
    "low-angle": "low angle shot looking up from near the ground, subject towering and heroic, "
                 "dramatic perspective against the sky or ceiling",
}

BANNED = ["nolan", "kubrick", "coogler", "inception", "interstellar", "shining",
          "2001", "black panther", "sinners", "creed"]


def _boards_json(data_dir, board_id):
    return data_dir / board_id / "storyboard.json"


def _inject_frame(data_dir, board_id, **extra):
    """Write a frame straight into storyboard.json (like an older or edited file)."""
    path = _boards_json(data_dir, board_id)
    board = json.loads(path.read_text(encoding="utf-8"))
    frame = {"id": "f" * 32, "section": "intro", "scene": "Old frame", "camera": "vhs-camcorder",
             "shot": "close-up", "lighting": "neon", "prompt": "p",
             "filename": "0" * 32 + ".png", "created": "2026-01-01T00:00:00+00:00"}
    frame.update(extra)
    frame = {k: v for k, v in frame.items() if v is not None}
    board["frames"].append(frame)
    path.write_text(json.dumps(board), encoding="utf-8")


def _csv_rows(client, board_id):
    resp = client.get(f"/storyboards/{board_id}/shotlist.csv")
    return list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))


@pytest.mark.parametrize("group", ["shot", "direction"])
def test_new_groups_are_well_formed(group):
    items = presets.GROUPS[group]
    ids = [p["id"] for p in items]
    assert len(ids) == len(set(ids))
    for p in items:
        assert p["id"] and p["name"] and "fragment" in p
        if not (group == "direction" and p["id"] == "none"):
            assert p["fragment"]


def test_direction_none_is_default_first_and_empty():
    assert presets.DEFAULT_DIRECTION == "none"
    assert presets.DIRECTIONS[0]["id"] == "none"
    assert presets.DIRECTIONS[0]["fragment"] == ""
    assert [d["id"] for d in presets.DIRECTIONS[1:]] == [
        "monumental", "one-point-symmetry", "warm-intimate"]


def test_original_shots_unchanged_and_default_kept():
    for shot_id, fragment in ORIGINAL_SHOTS.items():
        assert presets.get_preset("shot", shot_id)["fragment"] == fragment
    assert presets.DEFAULT_SHOT == "close-up"


def test_shot_display_order():
    by_cat = {}
    for s in presets.SHOTS:
        by_cat.setdefault(s["category"], []).append(s["name"])
    assert list(by_cat) == ["Framing", "Angle", "Perspective"]
    assert by_cat["Framing"] == ["Extreme Close-Up", "Close-Up", "Medium Shot", "Wide Shot"]
    assert by_cat["Angle"] == ["Eye Level", "High Angle", "Low Angle", "Bird's-Eye", "Dutch Angle"]
    assert by_cat["Perspective"] == ["Over-the-Shoulder", "POV"]


def test_build_prompt_includes_direction_fragment():
    prompt = build_prompt("A singer", "hook", "16mm-film", "pov", "noir", direction="monumental")
    assert presets.get_preset("direction", "monumental")["fragment"] in prompt


def test_build_prompt_none_equals_omitted():
    args = ("A singer.", "hook", "16mm-film", "pov", "noir")
    with_none = build_prompt(*args, direction="none")
    assert with_none == build_prompt(*args)
    assert ",," not in with_none
    assert "  " not in with_none
    assert not with_none.rstrip().endswith(",")


def test_build_prompt_rejects_unknown_direction():
    with pytest.raises(ValueError):
        build_prompt("x", "intro", "vhs-camcorder", "close-up", "neon", direction="nope")


def test_new_frame_stores_direction(client, data_dir, board_id):
    client.post(f"/storyboards/{board_id}/frames", data=frame_form(direction="warm-intimate"))
    board = json.loads(_boards_json(data_dir, board_id).read_text(encoding="utf-8"))
    assert board["frames"][0]["direction"] == "warm-intimate"
    page = client.get(f"/storyboards/{board_id}").data.decode()
    assert "Warm Intimate" in page
    rows = _csv_rows(client, board_id)
    assert rows[1][rows[0].index("direction")] == "warm-intimate"


def test_missing_direction_key_renders_and_exports_none(client, data_dir, board_id):
    _inject_frame(data_dir, board_id)
    resp = client.get(f"/storyboards/{board_id}")
    assert resp.status_code == 200
    settings = re.search(r'class="settings">(.*?)</p>', resp.data.decode(), re.S).group(1)
    assert "None" not in settings
    rows = _csv_rows(client, board_id)
    assert rows[1][rows[0].index("direction")] == "none"


def test_unknown_direction_id_renders_and_exports_none(client, data_dir, board_id):
    _inject_frame(data_dir, board_id, direction="removed-style")
    resp = client.get(f"/storyboards/{board_id}")
    assert resp.status_code == 200
    assert "removed-style" not in resp.data.decode()
    rows = _csv_rows(client, board_id)
    assert rows[1][rows[0].index("direction")] == "none"


def test_csv_header_direction_follows_lighting(client, board_id):
    header = _csv_rows(client, board_id)[0]
    assert header.index("direction") == header.index("lighting") + 1


def test_csv_direction_is_formula_guarded(client, data_dir, board_id):
    # The guard is applied to the cell; a valid id never starts with a trigger
    # character, so verify the helper directly as well as the column in place.
    from app.routes import _csv_safe
    assert _csv_safe("=cmd") == "'=cmd"
    _inject_frame(data_dir, board_id, direction="=cmd")
    rows = _csv_rows(client, board_id)
    assert not rows[1][rows[0].index("direction")].startswith("=")


@pytest.mark.parametrize("override", [
    {"direction": "bogus"}, {"direction": ""}, {"shot": "bogus"}, {"shot": ""},
])
def test_invalid_direction_or_shot_returns_400_without_side_effects(
        client, data_dir, board_id, override):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(**override))
    assert resp.status_code == 400
    assert list((data_dir / board_id).glob("*.png")) == []
    board = json.loads(_boards_json(data_dir, board_id).read_text(encoding="utf-8"))
    assert board["frames"] == []


def test_form_without_direction_field_still_works(client, board_id):
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    assert resp.status_code == 302


def test_no_banned_names_in_any_preset():
    patterns = [(t, re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", re.IGNORECASE))
                for t in BANNED]
    hits = []
    for group, items in presets.GROUPS.items():
        for preset in items:
            for field in ("id", "name", "fragment"):
                for term, pattern in patterns:
                    if pattern.search(str(preset.get(field, ""))):
                        hits.append(f"{group}/{preset['id']}.{field} contains {term!r}")
    assert not hits, "; ".join(hits)
