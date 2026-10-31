import pytest

from app import presets
from app.prompt import build_prompt


def test_build_prompt_includes_scene_and_fragments():
    prompt = build_prompt("A drummer in the rain", "hook", "16mm-film", "low-angle", "noir")
    assert "A drummer in the rain" in prompt
    assert presets.get_preset("camera", "16mm-film")["fragment"] in prompt
    assert presets.get_preset("shot", "low-angle")["fragment"] in prompt
    assert presets.get_preset("lighting", "noir")["fragment"] in prompt


@pytest.mark.parametrize("scene", [
    "A drummer in the rain.",
    "A drummer in the rain!?  ",
    "A drummer in the rain;:,.",
    "A drummer in the rain...\n",
])
def test_build_prompt_strips_trailing_punctuation(scene):
    prompt = build_prompt(scene, "hook", "vhs-camcorder", "close-up", "neon")
    assert prompt.startswith("A drummer in the rain, ")
    for bad in (".,", ",,", ";,", ":,", "!,", "?,"):
        assert bad not in prompt


def test_build_prompt_keeps_inner_punctuation():
    prompt = build_prompt("Wait, what? Yes.", "intro", "vhs-camcorder", "close-up", "neon")
    assert prompt.startswith("Wait, what? Yes, ")


def test_no_prompt_contains_4_3():
    for section in presets.SECTION_ORDER:
        for camera in presets.CAMERAS:
            for shot in presets.SHOTS:
                for lighting in presets.LIGHTING:
                    prompt = build_prompt("A scene.", section, camera["id"], shot["id"], lighting["id"])
                    assert "4:3" not in prompt
    # fx presets are pixel effects with no prompt fragment; they never reach a prompt.
    for name, group in presets.GROUPS.items():
        if name != "fx":
            assert all("4:3" not in p["fragment"] for p in group)


def test_build_prompt_rejects_unknown_preset():
    with pytest.raises(ValueError):
        build_prompt("x", "intro", "nope", "close-up", "neon")


@pytest.mark.parametrize("group", ["section", "camera", "shot", "lighting"])
def test_preset_groups_are_well_formed(group):
    items = presets.GROUPS[group]
    ids = [p["id"] for p in items]
    assert len(ids) == len(set(ids))
    for p in items:
        assert p["id"] and p["name"] and p["fragment"]


def test_defaults_and_order():
    assert presets.CAMERAS[0]["name"] == "VHS Camcorder"
    assert presets.LIGHTING[0]["name"] == "Neon"
    assert presets.DEFAULT_CAMERA == presets.CAMERAS[0]["id"]
    assert presets.DEFAULT_LIGHTING == presets.LIGHTING[0]["id"]
    assert presets.SECTION_ORDER == ["intro", "verse", "hook", "bridge", "outro"]
