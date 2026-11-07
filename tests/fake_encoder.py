"""Test doubles for the clip encoder, plus shared fixtures for the clip tests.

Test modules import `app` and `encoder` from here; `app` shadows the conftest
fixture of the same name so every clip test runs with a fake encoder and needs
no ffmpeg. Existing tests keep the original fixture.
"""

import re

import pytest

from app import create_app
import numpy as np

from app.clips.encoders import ClipEncoder
from app.clips.errors import EncodeError, EncoderUnavailable, InvalidClip
from app.clips.normalizer import ClipNormalizer

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 16  # 4 KB, enough for Range tests


class FakeEncoder(ClipEncoder):
    """Writes a small fake MP4. With consume=True it also drains and records the frames."""

    def __init__(self, consume=False, tag_frames=False):
        self.consume = consume
        self.tag_frames = tag_frames  # write "FRAMES=<n>" into the file so FakeNormalizer can read it back
        self.calls = []        # (dest, fps, size) per encode
        self.frame_counts = []
        self.shapes = set()

    def encode(self, frames, dest, fps, size):
        self.calls.append((dest, fps, size))
        if self.consume:
            n = 0
            for frame in frames:
                n += 1
                self.shapes.add((frame.shape, str(frame.dtype)))
            self.frame_counts.append(n)
        if self.consume and self.tag_frames:
            dest.write_bytes(MP4_BYTES[:12] + b"FRAMES=%d;" % n + MP4_BYTES[12:])
        else:
            dest.write_bytes(MP4_BYTES)


class FailingEncoder(ClipEncoder):
    """Leaves a half-written file behind, then fails, like a crashed ffmpeg."""

    def encode(self, frames, dest, fps, size):
        dest.write_bytes(b"half")
        raise EncodeError("boom")


class UnavailableEncoder(ClipEncoder):
    def check_available(self):
        raise EncoderUnavailable("Video encoder not found. test hint")

    def encode(self, frames, dest, fps, size):  # pragma: no cover
        raise AssertionError("must not be called")


class FakeNormalizer(ClipNormalizer):
    """Pretends to decode. "FRAMES=<n>;" in the file sets the length (default 20 frames);
    "BADVIDEO" anywhere makes it fail like an undecodable file."""

    DEFAULT_FRAMES = 20

    def __init__(self):
        self.calls = []

    def read_frames(self, path, size, fps, max_seconds):
        self.calls.append((str(path), size, fps, max_seconds))
        data = open(path, "rb").read()
        if b"BADVIDEO" in data:
            raise InvalidClip("That file could not be read as a video.")
        m = re.search(rb"FRAMES=(\d+);", data)
        n = int(m.group(1)) if m else self.DEFAULT_FRAMES
        w, h = size
        for i in range(n):
            yield np.full((h, w, 3), i % 256, dtype=np.uint8)


class UnavailableNormalizer(ClipNormalizer):
    def check_available(self):
        raise EncoderUnavailable("Video encoder not found. test hint")

    def read_frames(self, path, size, fps, max_seconds):  # pragma: no cover
        raise AssertionError("must not be called")


@pytest.fixture
def encoder():
    return FakeEncoder()


@pytest.fixture
def app(tmp_path, encoder):
    return create_app({"TESTING": True, "DATA_DIR": tmp_path, "GENERATOR": "mock",
                       "CLIP_ENCODER": encoder, "CLIP_NORMALIZER": FakeNormalizer()})


@pytest.fixture
def normalizer(app):
    return app.config["CLIP_NORMALIZER"]


def add_frame(client, board_id, **overrides):
    """POST a frame (mock generator) and return its id."""
    from app import storage
    from conftest import frame_form
    resp = client.post(f"/storyboards/{board_id}/frames", data=frame_form(**overrides))
    assert resp.status_code == 302, resp.get_data(as_text=True)[:300]
    board = storage.load_storyboard(client.application.config["DATA_DIR"], board_id)
    return board["frames"][-1]["id"]


def clip_files(data_dir, board_id):
    folder = data_dir / board_id / "clips"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def frame_clip_url(board_id, frame_id):
    return f"/storyboards/{board_id}/frames/{frame_id}/animate/clip"


def animate_url(board_id, frame_id):
    return f"/storyboards/{board_id}/frames/{frame_id}/animate"


ID32 = re.compile(r"^[0-9a-f]{32}$")
