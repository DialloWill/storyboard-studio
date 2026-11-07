import io
import zipfile

import pytest

from ai_helpers import (encoder, fake_video, frame_ids, make_zip, normalizer,  # noqa: F401
                        symlink_info, upload)
from fake_encoder import add_frame, app, clip_files  # noqa: F401

from app import ai_import, storage
from app.clips import settings

NO_ID = "f" * 32


def zip_url(board_id):
    return f"/storyboards/{board_id}/ai-clips"


def post_zip(client, board_id, entries):
    return upload(client, zip_url(board_id), "clips_zip", make_zip(entries))


def single_url(board_id, frame_id):
    return f"/storyboards/{board_id}/frames/{frame_id}/animate/ai"


def post_single(client, board_id, frame_id, data, filename="whatever.mp4"):
    return upload(client, single_url(board_id, frame_id), "clip", io.BytesIO(data), filename)


def frame(data_dir, board_id, frame_id):
    board = storage.load_storyboard(data_dir, board_id)
    return next(f for f in board["frames"] if f["id"] == frame_id)


def ai_files(data_dir, board_id):
    return [n for n in clip_files(data_dir, board_id) if ".ai." in n]


def nothing_imported(data_dir, board_id, fid):
    assert ai_files(data_dir, board_id) == []
    assert "clip_source" not in frame(data_dir, board_id, fid)


# ---- zip import -----------------------------------------------------------------------

def test_good_zip_imports_root_and_one_folder_deep(client, data_dir, board_id):
    a = add_frame(client, board_id, section="intro")
    b = add_frame(client, board_id, section="verse")
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video(15)), (f"ai_clips/{b}.mp4", fake_video(25))])
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "2 clip(s) imported" in html
    for fid in (a, b):
        assert frame(data_dir, board_id, fid)["clip_source"] == "ai"
    names = ai_files(data_dir, board_id)
    assert len(names) == 4  # two videos + two markers
    assert not [n for n in clip_files(data_dir, board_id) if n.endswith(".tmp")]


@pytest.mark.parametrize("name", [
    "../{id}.mp4", "x/../{id}.mp4", "/abs/{id}.mp4", "/{id}.mp4", "C:/x/{id}.mp4",
    "C:{id}.mp4", "a\\b\\{id}.mp4", "..\\{id}.mp4", "a/b/{id}.mp4"])
def test_unsafe_or_deep_names_are_skipped_never_extracted(client, data_dir, board_id, name):
    a = add_frame(client, board_id)
    before = sorted(p.relative_to(data_dir.parent).as_posix() for p in data_dir.parent.rglob("*"))
    resp = post_zip(client, board_id, [(name.format(id=a), fake_video())])
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "0 clip(s) imported" in html and "Skipped" in html
    nothing_imported(data_dir, board_id, a)
    after = sorted(p.relative_to(data_dir.parent).as_posix() for p in data_dir.parent.rglob("*"))
    assert after == before  # nothing written anywhere, not even outside the tape


def test_symlink_entry_is_rejected(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_zip(client, board_id, [(symlink_info(f"{a}.mp4"), b"/etc/passwd")])
    assert "Unsafe file name" in resp.get_data(as_text=True)
    nothing_imported(data_dir, board_id, a)


def test_duplicate_ids_are_both_rejected(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video()), (f"dir/{a}.mp4", fake_video())])
    html = resp.get_data(as_text=True)
    assert html.count("More than one entry") == 2
    nothing_imported(data_dir, board_id, a)


def test_unknown_ids_and_other_tapes_frames_are_listed_as_skipped(client, data_dir, board_id):
    from conftest import make_storyboard
    a = add_frame(client, board_id)
    other = make_storyboard(client, "Other")
    foreign = add_frame(client, other)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video()), (f"{NO_ID}.mp4", fake_video()),
                                       (f"{foreign}.mp4", fake_video())])
    html = resp.get_data(as_text=True)
    assert "1 clip(s) imported" in html
    assert html.count("Not a frame in this tape") == 2
    assert NO_ID in html
    assert ai_files(data_dir, other) == []


def test_wrong_names_and_extensions_are_skipped(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_zip(client, board_id, [(f"{a}.txt", b"x"), (f"{a}.mov", fake_video()),
                                       ("notes.mp4", fake_video()), (f"{a.upper()}.mp4", fake_video())])
    assert resp.get_data(as_text=True).count("Not named") == 4
    nothing_imported(data_dir, board_id, a)


def test_non_video_bytes_are_invalid_with_fixed_text(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_zip(client, board_id, [(f"{a}.mp4", b"this is just text, not a video at all" * 20)])
    html = resp.get_data(as_text=True)
    assert "Not a readable MP4 video" in html and "0 clip(s) imported" in html
    nothing_imported(data_dir, board_id, a)
    assert not [n for n in clip_files(data_dir, board_id) if n.endswith(".tmp")]


def test_undecodable_video_reports_fixed_text_and_leaves_nothing(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video(bad=True))])
    html = resp.get_data(as_text=True)
    assert "could not be read as a video" in html and "ffmpeg" not in html.lower()
    nothing_imported(data_dir, board_id, a)
    assert clip_files(data_dir, board_id) == []


def test_too_short_clip_is_rejected(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video(settings.AI_MIN_FRAMES - 1))])
    assert "too short" in resp.get_data(as_text=True)
    nothing_imported(data_dir, board_id, a)
    assert clip_files(data_dir, board_id) == []


def test_minimum_length_clip_is_accepted(client, data_dir, board_id):
    a = add_frame(client, board_id)
    post_zip(client, board_id, [(f"{a}.mp4", fake_video(settings.AI_MIN_FRAMES))])
    assert frame(data_dir, board_id, a)["clip_source"] == "ai"


def test_oversized_declared_entry_is_skipped(client, data_dir, board_id, monkeypatch):
    a = add_frame(client, board_id)
    monkeypatch.setattr(settings, "AI_MAX_ENTRY_BYTES", 2000)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video() + b"x" * 5000)])
    assert "Too large" in resp.get_data(as_text=True)
    nothing_imported(data_dir, board_id, a)


def test_zip_bomb_like_entry_is_skipped_before_extracting(client, data_dir, board_id, monkeypatch):
    a = add_frame(client, board_id)
    monkeypatch.setattr(settings, "AI_MAX_ENTRY_BYTES", 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:  # 8 MB of zeros, a few KB zipped
        zf.writestr(f"{a}.mp4", fake_video()[:12] + bytes(8 * 1024 * 1024))
    buf.seek(0)
    assert len(buf.getvalue()) < 100_000
    resp = upload(client, zip_url(board_id), "clips_zip", buf)
    assert "Too large" in resp.get_data(as_text=True)
    nothing_imported(data_dir, board_id, a)
    assert clip_files(data_dir, board_id) == []  # the clips folder was never even touched


def test_total_size_cap_skips_later_entries(client, data_dir, board_id, monkeypatch):
    a = add_frame(client, board_id, section="intro")
    b = add_frame(client, board_id, section="verse")
    size = len(fake_video())
    monkeypatch.setattr(settings, "AI_MAX_ZIP_BYTES", size + 10)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video()), (f"{b}.mp4", fake_video())])
    html = resp.get_data(as_text=True)
    assert "1 clip(s) imported" in html and "total size limit" in html
    assert frame(data_dir, board_id, a)["clip_source"] == "ai"
    assert "clip_source" not in frame(data_dir, board_id, b)


def test_actual_bytes_are_counted_not_just_declared_sizes():
    class Liar:  # claims nothing, delivers a lot: what a lying zip header would look like
        def __init__(self):
            self.left = 10

        def read(self, n=-1):
            if self.left <= 0:
                return b""
            self.left -= 1
            return b"x" * 65536

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ai_import.TooBig):
            ai_import.copy_limited(Liar(), d + "/out", 100_000)


def test_entry_count_cap_rejects_the_whole_zip(client, data_dir, board_id, monkeypatch):
    a = add_frame(client, board_id)
    monkeypatch.setattr(settings, "AI_MAX_ZIP_ENTRIES", 2)
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video()), ("a.txt", b"1"), ("b.txt", b"2")])
    assert resp.status_code == 400 and "too many entries" in resp.get_data(as_text=True)
    nothing_imported(data_dir, board_id, a)


def test_not_a_zip_and_missing_file(client, board_id):
    resp = upload(client, zip_url(board_id), "clips_zip", io.BytesIO(b"definitely not a zip"))
    assert resp.status_code == 400 and "not a valid zip" in resp.get_data(as_text=True)
    resp = client.post(zip_url(board_id), data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_import_page_and_bad_ids(client, board_id):
    resp = client.get(zip_url(board_id))
    assert resp.status_code == 200 and 'enctype="multipart/form-data"' in resp.get_data(as_text=True)
    for bad in ["nothex", "0" * 32, ("a" * 32) + "\n"]:
        assert client.get(zip_url(bad)).status_code == 404
        assert upload(client, zip_url(bad), "clips_zip", make_zip([])).status_code == 404


def test_import_with_unavailable_encoder_is_503(client, app, board_id):
    from fake_encoder import UnavailableEncoder
    a = add_frame(client, board_id)
    app.config["CLIP_ENCODER"] = UnavailableEncoder()
    resp = post_zip(client, board_id, [(f"{a}.mp4", fake_video())])
    assert resp.status_code == 503


def test_413_page_for_oversized_request(client, app, board_id):
    app.config["MAX_CONTENT_LENGTH"] = 2000
    resp = upload(client, zip_url(board_id), "clips_zip", io.BytesIO(b"x" * 20000))
    html = resp.get_data(as_text=True)
    assert resp.status_code == 413 and "too large" in html and "MB" in html


# ---- single upload on the Animate page ---------------------------------------------------

def test_single_upload_ignores_the_file_name(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_single(client, board_id, a, fake_video(), filename="../../evil name.exe.mov")
    assert resp.status_code == 302
    assert frame(data_dir, board_id, a)["clip_source"] == "ai"
    names = ai_files(data_dir, board_id)
    assert all(n.startswith(a + ".ai.") for n in names) and len(names) == 2
    assert not list(data_dir.parent.rglob("evil*"))


def test_single_upload_garbage_bytes(client, data_dir, board_id):
    a = add_frame(client, board_id)
    resp = post_single(client, board_id, a, b"garbage" * 100)
    assert resp.status_code == 422 and "Not a readable MP4" in resp.get_data(as_text=True)
    nothing_imported(data_dir, board_id, a)
    assert clip_files(data_dir, board_id) == []


def test_single_upload_empty_and_missing(client, data_dir, board_id):
    a = add_frame(client, board_id)
    assert post_single(client, board_id, a, b"").status_code == 422
    resp = client.post(single_url(board_id, a), data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    nothing_imported(data_dir, board_id, a)


def test_single_upload_too_large_is_413(client, data_dir, board_id, monkeypatch):
    a = add_frame(client, board_id)
    monkeypatch.setattr(settings, "AI_MAX_ENTRY_BYTES", 1000)
    monkeypatch.setattr(settings, "MiB", 1000)  # body cap = 2000 bytes
    resp = post_single(client, board_id, a, fake_video() + b"x" * 5000)
    assert resp.status_code == 413
    nothing_imported(data_dir, board_id, a)


def test_single_upload_unknown_frame_is_404(client, board_id):
    assert post_single(client, board_id, NO_ID, fake_video()).status_code == 404
    assert post_single(client, board_id, "nothex", fake_video()).status_code == 404


def test_reimport_replaces_and_cleans_up(client, data_dir, board_id):
    a = add_frame(client, board_id)
    post_single(client, board_id, a, fake_video(15))
    first = ai_files(data_dir, board_id)
    post_single(client, board_id, a, fake_video(30))
    second = ai_files(data_dir, board_id)
    assert len(second) == 2 and set(first) != set(second)
