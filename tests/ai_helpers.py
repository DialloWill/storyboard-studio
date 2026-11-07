"""Shared helpers for the AI clip tests (fake encoder that tags frame counts, zip builders)."""

import io
import stat
import zipfile

import pytest

from fake_encoder import MP4_BYTES, FakeEncoder, app, normalizer  # noqa: F401


@pytest.fixture
def encoder():
    return FakeEncoder(consume=True, tag_frames=True)


def fake_video(frames=20, bad=False):
    """Bytes that pass the magic check; FakeNormalizer reads the frame count from them."""
    body = b"BADVIDEO" if bad else b"FRAMES=%d;" % frames
    return MP4_BYTES[:12] + body + MP4_BYTES[12:]


def make_zip(entries):
    """entries: list of (name, bytes) or (ZipInfo, bytes). Returns a BytesIO ready to upload."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    buf.seek(0)
    return buf


def symlink_info(name):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


def upload(client, url, field, data, filename="x.zip"):
    return client.post(url, data={field: (data, filename)}, content_type="multipart/form-data")


def frame_ids(data_dir, board_id):
    from app import storage
    board = storage.load_storyboard(data_dir, board_id)
    return [f["id"] for f in storage.sorted_frames(board)]
