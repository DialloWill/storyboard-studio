"""Real-ffmpeg checks. Skipped cleanly when no ffmpeg with libx264 is available."""

import numpy as np
import pytest

from app import create_app
from app.clips import encoders
from conftest import make_storyboard
from fake_encoder import add_frame, animate_url

_exe = encoders.find_ffmpeg()
pytestmark = pytest.mark.skipif(
    _exe is None or not encoders._has_libx264(_exe), reason="ffmpeg with libx264 not available")


def test_ffmpeg_encoder_writes_a_playable_mp4_header(tmp_path):
    frames = (np.full((36, 64, 3), 40 * i % 255, dtype=np.uint8) for i in range(8))
    dest = tmp_path / "x.tmp"
    encoders.FfmpegEncoder().encode(frames, dest, 15, (64, 36))
    data = dest.read_bytes()
    assert data[4:8] == b"ftyp" and len(data) > 500


def test_full_route_with_real_ffmpeg(tmp_path):
    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock"})
    c = app.test_client()
    board_id = make_storyboard(c)
    fid = add_frame(c, board_id, section="intro")
    assert c.post(animate_url(board_id, fid)).status_code == 302
    resp = c.get(f"/storyboards/{board_id}/frames/{fid}/animate/clip")
    assert resp.status_code == 200 and resp.data[4:8] == b"ftyp"
    assert c.post(f"/storyboards/{board_id}/play").status_code == 302
    assert c.get(f"/storyboards/{board_id}/play/clip").data[4:8] == b"ftyp"
