import io
import re

import pytest
from PIL import Image

from app import display
from app.generators.mock import MockGenerator
from conftest import frame_form


@pytest.mark.parametrize("index, expected", [
    (0, "00:00:00:00"),
    (1, "00:00:12:00"),
    (5, "00:01:00:00"),
    (6, "00:01:12:00"),
    (300, "01:00:00:00"),
])
def test_timecode(index, expected):
    assert display.timecode(index) == expected


def test_timecode_fields_are_always_valid():
    for index in range(0, 1000):
        hh, mm, ss, ff = (int(x) for x in display.timecode(index).split(":"))
        assert mm < 60 and ss < 60 and ff == 0


def test_date_stamp():
    assert display.date_stamp("2026-10-29T12:30:00+00:00") == "OCT 29 1996"
    assert display.date_stamp("2026-01-05T00:00:00+00:00") == "JAN 05 1996"
    assert display.date_stamp("garbage").endswith("1996")


def test_channel_label():
    assert display.channel_label("intro", "Intro") == "CH.01 INTRO"
    assert display.channel_label("outro", "Outro") == "CH.05 OUTRO"


def add_frames(client, board_id, sections):
    for section in sections:
        resp = client.post(f"/storyboards/{board_id}/frames",
                           data=frame_form(section=section, scene=f"Scene for {section}"))
        assert resp.status_code == 302


def test_viewfinder_content_and_order(client, board_id):
    add_frames(client, board_id, ["outro", "intro", "hook"])
    html = client.get(f"/storyboards/{board_id}").data.decode()
    assert html.index("CH.01 INTRO") < html.index("CH.03 HOOK") < html.index("CH.05 OUTRO")
    assert html.index("00:00:00:00") < html.index("00:00:12:00") < html.index("00:00:24:00")
    assert "1996" in html
    assert html.count("REC") >= 3
    assert re.search(r"\b[A-Z]{3} \d{2} 1996\b", html)


def test_overlays_are_aria_hidden_and_images_have_alt(client, board_id):
    add_frames(client, board_id, ["verse"])
    html = client.get(f"/storyboards/{board_id}").data.decode()
    for cls in ("vf-rec", "vf-batt", "vf-tc", "vf-date", "vf-scan"):
        assert f'class="{cls}" aria-hidden="true"' in html, cls
    for corner in ("tl", "tr", "bl", "br"):
        assert f'class="vf-corner {corner}" aria-hidden="true"' in html, corner
    assert 'alt="Verse: Scene for verse"' in html


def test_alt_text_is_escaped(client, board_id):
    resp = client.post(f"/storyboards/{board_id}/frames",
                       data=frame_form(scene='"><script>x</script>'))
    assert resp.status_code == 302
    html = client.get(f"/storyboards/{board_id}").data.decode()
    assert "<script" not in html.lower()


def test_tape_shelf(client, board_id):
    add_frames(client, board_id, ["intro"])
    html = client.get("/").data.decode()
    assert "T-120" in html
    assert "0001" in html
    assert "Insert tape" in html


def test_buttons_labelled(client, board_id):
    html = client.get(f"/storyboards/{board_id}").data.decode()
    assert re.search(r'<button class="btn" type="submit"><span class="rec">&#9679;</span> REC</button>', html)


WARN_HEAD = '<p class="warn-head">!! TRACKING ERROR !!</p>'


def test_error_boxes_show_tracking_error(client, board_id, monkeypatch):
    bad_title = client.post("/storyboards", data={"song_title": ""})
    assert bad_title.status_code == 400
    assert WARN_HEAD in bad_title.data.decode()
    assert "Song title is required." in bad_title.data.decode()

    bad_frame = client.post(f"/storyboards/{board_id}/frames", data=frame_form(scene=""))
    assert bad_frame.status_code == 400
    assert WARN_HEAD in bad_frame.data.decode()

    def boom(self, prompt):
        raise RuntimeError("down")

    monkeypatch.setattr(MockGenerator, "generate", boom)
    failed = client.post(f"/storyboards/{board_id}/frames", data=frame_form())
    assert failed.status_code == 502
    assert WARN_HEAD in failed.data.decode()
    assert "Image generation failed." in failed.data.decode()


def test_no_error_box_on_clean_pages(client, board_id):
    assert WARN_HEAD not in client.get("/").data.decode()
    assert WARN_HEAD not in client.get(f"/storyboards/{board_id}").data.decode()


def test_animation_only_inside_reduced_motion_query(client):
    html = client.get("/").data.decode()
    gate = html.index("@media (prefers-reduced-motion: no-preference)")
    assert html.index("animation") > gate
    assert html.index("@keyframes") > gate
    assert html.count("animation:") == 1


def test_mock_card_has_color_bars_and_black_lower_third():
    img = Image.open(io.BytesIO(MockGenerator().generate("A prompt. " * 30))).convert("RGB")
    assert img.size == (1280, 720)
    assert img.getpixel((10, 10)) == (192, 192, 192)      # white bar
    assert img.getpixel((1270, 10)) == (0, 0, 192)        # blue bar
    assert img.getpixel((10, 479)) == (192, 192, 192)     # bars fill the top two-thirds
    assert img.getpixel((10, 481)) == (0, 0, 0)           # black below
    assert img.getpixel((1270, 715)) == (0, 0, 0)
    lower = img.crop((0, 480, 1280, 720))
    white = lower.convert("L").histogram()[255]
    assert white > 200                                    # caption text was drawn
