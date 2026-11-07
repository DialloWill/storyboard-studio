import json

import pytest

from ai_helpers import encoder, fake_video, normalizer, upload  # noqa: F401
from fake_encoder import add_frame, animate_url, app, clip_files  # noqa: F401

from app import clips, fx, storage
from app.clips import ai, fingerprint, render, settings

import io


def import_one(client, board_id, fid, frames=20):
    resp = upload(client, f"/storyboards/{board_id}/frames/{fid}/animate/ai", "clip",
                  io.BytesIO(fake_video(frames)), "any.mp4")
    assert resp.status_code == 302, resp.get_data(as_text=True)[:300]


def get_frame(data_dir, board_id, fid):
    board = storage.load_storyboard(data_dir, board_id)
    return next(f for f in board["frames"] if f["id"] == fid)


def png_of(data_dir, board_id, fid):
    return data_dir / board_id / get_frame(data_dir, board_id, fid)["filename"]


def change_png(data_dir, board_id, fid):
    p = png_of(data_dir, board_id, fid)
    p.write_bytes(p.read_bytes() + b"\x00changed")


def state(data_dir, board_id, fid):
    return ai.ai_state(data_dir, board_id, get_frame(data_dir, board_id, fid))[0]


def tape_state(data_dir, board_id):
    board = storage.load_storyboard(data_dir, board_id)
    return clips.tape_state(data_dir, board_id, board)[0]


def play(client, board_id):
    resp = client.post(f"/storyboards/{board_id}/play")
    assert resp.status_code == 302, resp.get_data(as_text=True)[:300]


# ---- staleness -----------------------------------------------------------------------

def test_fresh_after_import_and_marker_records_png_sha(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a, 17)
    assert state(data_dir, board_id, a) == "fresh"
    meta = storage.read_clip_meta(data_dir, board_id, storage.ai_key(a))
    assert meta["png_sha256"] == fingerprint.file_sha256(png_of(data_dir, board_id, a))
    assert meta["frames"] == 17 and meta["width"] == 640 and meta["height"] == 360 and meta["fps"] == 15


def test_ai_clip_is_stale_when_the_frame_png_changes(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    change_png(data_dir, board_id, a)
    assert state(data_dir, board_id, a) == "stale"
    assert ai.active_clip(data_dir, board_id, get_frame(data_dir, board_id, a)) is None
    assert client.get(f"/storyboards/{board_id}/frames/{a}/animate/ai-clip").status_code == 404
    page = client.get(animate_url(board_id, a)).get_data(as_text=True)
    assert "STALE" in page and "Play tape ignores it" in page
    board_page = client.get(f"/storyboards/{board_id}").get_data(as_text=True)
    assert "AI clip stale" in board_page
    resp = client.post(f"/storyboards/{board_id}/frames/{a}/animate/source", data={"source": "ai"})
    assert resp.status_code == 409


def test_replaced_clip_file_is_stale(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    path = next(p for p in (data_dir / board_id / "clips").glob(f"{a}.ai.*.mp4"))
    path.write_bytes(path.read_bytes() + b"tampered")
    assert state(data_dir, board_id, a) == "stale"


def test_badge_states_on_the_storyboard_page(client, data_dir, board_id):
    a = add_frame(client, board_id)
    page = lambda: client.get(f"/storyboards/{board_id}").get_data(as_text=True)  # noqa: E731
    assert '<span class="clip-badge">procedural</span>' in page()
    import_one(client, board_id, a)
    assert '<span class="clip-badge">AI clip</span>' in page()
    client.post(f"/storyboards/{board_id}/frames/{a}/animate/source", data={"source": "procedural"})
    assert '<span class="clip-badge">procedural</span>' in page()
    client.post(f"/storyboards/{board_id}/frames/{a}/animate/source", data={"source": "ai"})
    change_png(data_dir, board_id, a)
    assert '<span class="clip-badge">AI clip stale</span>' in page()


def test_missing_clip_source_means_procedural(client, data_dir, board_id):
    a = add_frame(client, board_id)
    assert "clip_source" not in get_frame(data_dir, board_id, a)
    assert ai.clip_source(get_frame(data_dir, board_id, a)) == "procedural"


def test_source_switch_validation(client, data_dir, board_id):
    a = add_frame(client, board_id)
    url = f"/storyboards/{board_id}/frames/{a}/animate/source"
    assert client.post(url, data={"source": "ai"}).status_code == 409  # nothing imported yet
    assert client.post(url, data={"source": "bogus"}).status_code == 400
    import_one(client, board_id, a)
    assert client.post(url, data={"source": "procedural"}).status_code == 302
    assert get_frame(data_dir, board_id, a)["clip_source"] == "procedural"
    assert client.post(url, data={"source": "ai"}).status_code == 302
    assert get_frame(data_dir, board_id, a)["clip_source"] == "ai"


def test_procedural_render_does_not_delete_the_ai_clip(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    before = [n for n in clip_files(data_dir, board_id) if ".ai." in n]
    assert client.post(animate_url(board_id, a), data={"camera_move": "pan-left"}).status_code == 302
    client.post(animate_url(board_id, a), data={"camera_move": "zoom-out"})
    names = clip_files(data_dir, board_id)
    assert [n for n in names if ".ai." in n] == before
    assert any(n.endswith(".json") and ".ai." not in n for n in names)  # the procedural clip too
    assert state(data_dir, board_id, a) == "fresh"


def test_animate_page_shows_both_clips(client, data_dir, board_id):
    a = add_frame(client, board_id)
    client.post(animate_url(board_id, a), data={})
    import_one(client, board_id, a)
    page = client.get(animate_url(board_id, a)).get_data(as_text=True)
    assert f"/frames/{a}/animate/clip" in page and f"/frames/{a}/animate/ai-clip" in page
    assert "Remove AI clip" in page and "Switch source" in page
    assert client.get(f"/storyboards/{board_id}/frames/{a}/animate/ai-clip").status_code == 200


# ---- Play tape ---------------------------------------------------------------------------

def test_procedural_only_tapes_keep_their_old_fingerprint(client, data_dir, board_id):
    a = add_frame(client, board_id, section="intro")
    b = add_frame(client, board_id, section="verse")
    play(client, board_id)
    board = storage.load_storyboard(data_dir, board_id)
    frames = storage.sorted_frames(board)
    old = fingerprint.tape_fingerprint(
        [clips._frame_fp(clips._png_path(data_dir, board_id, f), f) for f in frames])
    assert storage.read_clip_meta(data_dir, board_id, storage.TAPE_KEY)["fingerprint"] == old
    assert tape_state(data_dir, board_id) == "fresh"


def test_import_and_source_switch_make_the_tape_stale(client, data_dir, board_id):
    a = add_frame(client, board_id, section="intro")
    add_frame(client, board_id, section="verse")
    play(client, board_id)
    assert tape_state(data_dir, board_id) == "fresh"
    import_one(client, board_id, a)  # selects the AI clip
    assert tape_state(data_dir, board_id) == "stale"
    play(client, board_id)
    assert tape_state(data_dir, board_id) == "fresh"
    client.post(f"/storyboards/{board_id}/frames/{a}/animate/source", data={"source": "procedural"})
    assert tape_state(data_dir, board_id) == "stale"
    play(client, board_id)
    assert tape_state(data_dir, board_id) == "fresh"
    client.post(f"/storyboards/{board_id}/frames/{a}/animate/source", data={"source": "ai"})
    assert tape_state(data_dir, board_id) == "stale"


def test_png_change_makes_a_tape_with_ai_clip_stale_and_falls_back(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    play(client, board_id)
    assert tape_state(data_dir, board_id) == "fresh"
    change_png(data_dir, board_id, a)
    assert tape_state(data_dir, board_id) == "stale"


def test_play_tape_mixes_ai_and_procedural_in_sorted_order(client, data_dir, board_id, monkeypatch):
    # Created out of order on purpose; sorted order is intro, verse, hook.
    c = add_frame(client, board_id, section="hook", scene="c")
    a = add_frame(client, board_id, section="intro", scene="a")
    b = add_frame(client, board_id, section="verse", scene="b")
    import_one(client, board_id, b, 12)  # the middle frame has an AI clip
    seen = {}

    def capture(items):
        seen["items"] = list(items)
        return iter(())

    monkeypatch.setattr(render, "tape_sequence", capture)
    play(client, board_id)
    items = seen["items"]
    assert [i[3] for i in items] == [fx.seed_from_frame_id(x) for x in (a, b, c)]
    assert [isinstance(i[0], render.Prerendered) for i in items] == [False, True, False]


def test_play_tape_encodes_variable_length_clips_and_transitions(client, data_dir, board_id, encoder, normalizer):
    a = add_frame(client, board_id, section="intro")
    b = add_frame(client, board_id, section="verse")
    c = add_frame(client, board_id, section="hook")
    import_one(client, board_id, b, 12)
    encoder.frame_counts.clear()
    play(client, board_id)
    expected = settings.FRAMES + 12 + settings.FRAMES + 2 * settings.TRANSITION_FRAMES
    assert encoder.frame_counts == [expected]
    meta = storage.read_clip_meta(data_dir, board_id, storage.TAPE_KEY)
    assert meta["frames"] == expected
    # the AI clip was decoded from its stored file, once, for the tape
    assert any(f".ai." in call[0] for call in normalizer.calls[-1:])
    page = client.get(f"/storyboards/{board_id}/play").get_data(as_text=True)
    assert "<video controls" in page


def test_two_ai_clips_of_different_lengths(client, data_dir, board_id, encoder):
    a = add_frame(client, board_id, section="intro")
    b = add_frame(client, board_id, section="verse")
    import_one(client, board_id, a, 9)
    import_one(client, board_id, b, 31)
    encoder.frame_counts.clear()
    play(client, board_id)
    assert encoder.frame_counts == [9 + 31 + settings.TRANSITION_FRAMES]


def test_stale_ai_clip_is_not_used_by_play_tape(client, data_dir, board_id, monkeypatch):
    a = add_frame(client, board_id)
    import_one(client, board_id, a)
    change_png(data_dir, board_id, a)
    seen = {}
    monkeypatch.setattr(render, "tape_sequence", lambda items: (seen.setdefault("i", list(items)), iter(()))[1])
    play(client, board_id)
    assert not isinstance(seen["i"][0][0], render.Prerendered)


def test_play_page_duration_follows_ai_clip_length(client, data_dir, board_id):
    a = add_frame(client, board_id)
    import_one(client, board_id, a, 30)  # 2.0 s at 15 fps
    assert "2.0 seconds" in client.get(f"/storyboards/{board_id}/play").get_data(as_text=True)
