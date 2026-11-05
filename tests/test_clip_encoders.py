import sys
import types

import pytest

from app.clips import encoders
from app.clips.errors import EncoderUnavailable
from fake_encoder import FakeEncoder


def test_pinned_imageio_ffmpeg_wins_over_path(monkeypatch):
    fake = types.SimpleNamespace(get_ffmpeg_exe=lambda: "bundled-ffmpeg")
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", fake)
    monkeypatch.setattr(encoders.shutil, "which", lambda name: "path-ffmpeg")
    assert encoders.find_ffmpeg() == "bundled-ffmpeg"


def test_path_ffmpeg_is_only_a_fallback(monkeypatch):
    def boom():
        raise RuntimeError("no binary")

    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", types.SimpleNamespace(get_ffmpeg_exe=boom))
    monkeypatch.setattr(encoders.shutil, "which", lambda name: "path-ffmpeg")
    assert encoders.find_ffmpeg() == "path-ffmpeg"
    monkeypatch.setattr(encoders.shutil, "which", lambda name: None)
    assert encoders.find_ffmpeg() is None


def test_no_ffmpeg_is_unavailable(monkeypatch):
    monkeypatch.setattr(encoders, "find_ffmpeg", lambda: None)
    with pytest.raises(EncoderUnavailable) as err:
        encoders.FfmpegEncoder().check_available()
    assert "pip install -r requirements.txt" in err.value.message


def test_ffmpeg_without_libx264_is_unavailable(monkeypatch):
    monkeypatch.setattr(encoders, "find_ffmpeg", lambda: "some-ffmpeg")
    monkeypatch.setattr(encoders, "_has_libx264", lambda exe: False)
    with pytest.raises(EncoderUnavailable):
        encoders.FfmpegEncoder().check_available()


def test_libx264_probe_is_cached_per_executable(monkeypatch):
    calls = []

    class Result:
        stdout = b" V....D libx264 H.264"

    monkeypatch.setattr(encoders.subprocess, "run", lambda *a, **k: calls.append(a) or Result())
    monkeypatch.setattr(encoders, "_x264_cache", {})
    assert encoders._has_libx264("exe-a") and encoders._has_libx264("exe-a")
    assert len(calls) == 1


def test_get_encoder_selection():
    fake = FakeEncoder()
    assert encoders.get_encoder({"CLIP_ENCODER": fake}) is fake
    assert isinstance(encoders.get_encoder({}), encoders.FfmpegEncoder)
    with pytest.raises(EncoderUnavailable):
        encoders.get_encoder({"CLIP_ENCODER": "nope"})
