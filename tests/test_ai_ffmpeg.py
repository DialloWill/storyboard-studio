"""Real-ffmpeg checks for imported AI clips. Skipped cleanly when ffmpeg with libx264 is missing."""

import io
import re
import subprocess

import pytest

from app import create_app, storage
from app.clips import encoders, settings
from app.clips.errors import InvalidClip
from app.clips.normalizer import FfmpegNormalizer, decode_command
from conftest import make_storyboard
from fake_encoder import add_frame

_exe = encoders.find_ffmpeg()
pytestmark = pytest.mark.skipif(
    _exe is None or not encoders._has_libx264(_exe), reason="ffmpeg with libx264 not available")


def make_video(path, size="320x240", rate=25, seconds=2.0, audio=True, title=None):
    cmd = [_exe, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if title:
        cmd += ["-metadata", f"title={title}"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, **encoders._popen_flags())
    return path


def probe(path):
    out = subprocess.run([_exe, "-hide_banner", "-i", str(path)], capture_output=True,
                         **encoders._popen_flags())
    return out.stderr.decode("utf-8", "replace")


@pytest.fixture
def real(tmp_path):
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path / "data", "GENERATOR": "mock"})
    client = app.test_client()
    board_id = make_storyboard(client)
    return client, board_id, tmp_path / "data"


def post_clip(client, board_id, fid, data, name="clip.mp4"):
    return client.post(f"/storyboards/{board_id}/frames/{fid}/animate/ai",
                       data={"clip": (io.BytesIO(data), name)}, content_type="multipart/form-data")


def ai_clip_path(data_dir, board_id, fid):
    meta = storage.read_clip_meta(data_dir, board_id, storage.ai_key(fid))
    return storage.clip_file_path(data_dir, board_id, storage.ai_key(fid), meta), meta


def test_decode_command_flags():
    cmd = decode_command("ffmpeg", "x.mp4", (640, 360), 15, 10)
    assert isinstance(cmd, list)
    joined = " ".join(cmd)
    for flag in ("-nostdin", "-protocol_whitelist file", "-f mov", "-an", "-sn", "-dn",
                 "-map_metadata -1", "-t 10", "fps=15", "crop=640:360"):
        assert flag in joined


def test_normalizer_yields_frames_at_the_clip_spec(tmp_path):
    src = make_video(tmp_path / "in.mp4", size="320x240", rate=25, seconds=2.0)
    frames = list(FfmpegNormalizer().read_frames(src, (640, 360), 15, 10))
    assert 29 <= len(frames) <= 31
    assert frames[0].shape == (360, 640, 3) and frames[0].dtype.name == "uint8"


def test_real_import_normalizes_size_fps_audio_and_metadata(real, tmp_path):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    src = make_video(tmp_path / "in.mp4", size="480x270", rate=24, seconds=1.5, title="SECRET-TITLE")
    resp = post_clip(client, board_id, fid, src.read_bytes(), "my holiday video.MOV.mp4")
    assert resp.status_code == 302, resp.get_data(as_text=True)[:300]
    path, meta = ai_clip_path(data_dir, board_id, fid)
    info = probe(path)
    assert "Video: h264" in info and "yuv420p" in info
    assert "640x360" in info and re.search(r"\b15 fps\b", info)
    assert "Audio:" not in info
    assert b"SECRET-TITLE" not in path.read_bytes()
    assert 20 <= meta["frames"] <= 24
    assert client.get(f"/storyboards/{board_id}/frames/{fid}/animate/ai-clip").data[4:8] == b"ftyp"


def test_portrait_source_is_scaled_to_cover_then_cropped(real, tmp_path):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    src = make_video(tmp_path / "in.mp4", size="180x320", rate=25, seconds=1.0, audio=False)
    assert post_clip(client, board_id, fid, src.read_bytes()).status_code == 302
    assert "640x360" in probe(ai_clip_path(data_dir, board_id, fid)[0])


def test_long_clip_is_capped_at_ten_seconds(real, tmp_path):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    src = make_video(tmp_path / "in.mp4", size="64x48", rate=10, seconds=14.0, audio=False)
    assert post_clip(client, board_id, fid, src.read_bytes()).status_code == 302
    meta = ai_clip_path(data_dir, board_id, fid)[1]
    assert meta["frames"] == settings.AI_MAX_SECONDS * settings.FPS


def test_too_short_clip_is_rejected(real, tmp_path):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    src = make_video(tmp_path / "in.mp4", size="64x48", rate=25, seconds=0.2, audio=False)
    resp = post_clip(client, board_id, fid, src.read_bytes())
    assert resp.status_code == 422 and "too short" in resp.get_data(as_text=True)
    assert storage.read_clip_meta(data_dir, board_id, storage.ai_key(fid)) is None
    assert not list((data_dir / board_id / "clips").glob("*")) if (data_dir / board_id / "clips").is_dir() else True


def test_text_renamed_to_mp4_is_rejected(real):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    resp = post_clip(client, board_id, fid, b"plain text pretending to be a video" * 50)
    assert resp.status_code == 422 and "Not a readable MP4" in resp.get_data(as_text=True)


def test_mp4_header_with_garbage_body_gets_fixed_text_not_ffmpeg_output(real):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    resp = post_clip(client, board_id, fid, b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 422 and "could not be read as a video" in html
    for leak in ("moov", "Invalid data", "ffmpeg", "Error"):
        assert leak not in html


def test_truncated_video_is_rejected(real, tmp_path):
    client, board_id, data_dir = real
    fid = add_frame(client, board_id)
    src = make_video(tmp_path / "in.mp4", size="320x240", seconds=2.0)
    data = src.read_bytes()
    resp = post_clip(client, board_id, fid, data[: len(data) // 3])
    assert resp.status_code == 422
    assert storage.read_clip_meta(data_dir, board_id, storage.ai_key(fid)) is None


def test_slow_decode_times_out_with_friendly_text(tmp_path):
    src = make_video(tmp_path / "in.mp4", size="1280x720", rate=30, seconds=8.0, audio=False)
    with pytest.raises(InvalidClip) as exc:
        list(FfmpegNormalizer(timeout=0.01).read_frames(src, (640, 360), 15, 10))
    assert exc.value.message == "That video took too long to process. Try a shorter or smaller clip."


def test_real_play_tape_mixes_ai_and_procedural(real, tmp_path):
    client, board_id, data_dir = real
    a = add_frame(client, board_id, section="intro")
    b = add_frame(client, board_id, section="verse")
    src = make_video(tmp_path / "in.mp4", size="320x240", seconds=1.0, audio=False)
    assert post_clip(client, board_id, b, src.read_bytes()).status_code == 302
    assert client.post(f"/storyboards/{board_id}/play").status_code == 302
    resp = client.get(f"/storyboards/{board_id}/play/clip")
    assert resp.status_code == 200 and resp.data[4:8] == b"ftyp"
    meta = storage.read_clip_meta(data_dir, board_id, storage.TAPE_KEY)
    ai_frames = ai_clip_path(data_dir, board_id, b)[1]["frames"]
    assert meta["frames"] == settings.FRAMES + ai_frames + settings.TRANSITION_FRAMES
