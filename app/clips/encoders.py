"""Clip encoders. Same shape as the ImageGenerator pattern: an ABC, a real
implementation, and config-driven selection (tests pass an instance instead).

Encoders write to the path they are given and nothing else; the caller owns
the temp-file / atomic-replace dance.
"""

import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod

from .errors import EncodeError, EncoderUnavailable

INSTALL_HINT = ("Video encoder not found. Run `pip install -r requirements.txt` "
                "(installs imageio-ffmpeg) or install ffmpeg with libx264.")


class ClipEncoder(ABC):
    def check_available(self):
        """Raise EncoderUnavailable if this encoder cannot run. Called before any work."""

    @abstractmethod
    def encode(self, frames, dest, fps, size):
        """Write an H.264 MP4 of `frames` (uint8 RGB arrays of `size` = (w, h)) to `dest`."""


_x264_cache = {}


def find_ffmpeg():
    """Pinned imageio-ffmpeg first (reproducible); ffmpeg on PATH only as a fallback."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # not installed, or its binary is missing
        return shutil.which("ffmpeg")


def _has_libx264(exe):
    if exe not in _x264_cache:
        try:
            out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True,
                                 timeout=30, **_popen_flags())
            _x264_cache[exe] = b"libx264" in out.stdout
        except (OSError, subprocess.SubprocessError):
            _x264_cache[exe] = False
    return _x264_cache[exe]


def _popen_flags():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class FfmpegEncoder(ClipEncoder):
    def _exe(self):
        exe = find_ffmpeg()
        if not exe or not _has_libx264(exe):
            raise EncoderUnavailable(INSTALL_HINT)
        return exe

    def check_available(self):
        self._exe()

    def encode(self, frames, dest, fps, size):
        exe = self._exe()
        w, h = size
        cmd = [exe, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-threads", "2",
               "-f", "mp4", str(dest)]
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=err, **_popen_flags())
            try:
                try:
                    for frame in frames:
                        proc.stdin.write(frame.tobytes())
                    proc.stdin.close()
                except BrokenPipeError:
                    pass  # ffmpeg died early; its exit code and stderr explain why
                code = proc.wait(timeout=300)
            except BaseException:
                proc.kill()
                proc.wait()
                raise
            if code != 0:
                err.seek(0)
                detail = err.read().decode("utf-8", "replace").strip()[-300:]
                raise EncodeError(f"Video encoding failed. {detail}".strip())


def get_encoder(config):
    value = config.get("CLIP_ENCODER", "ffmpeg")
    if isinstance(value, ClipEncoder):
        return value
    if value == "ffmpeg":
        return FfmpegEncoder()
    raise EncoderUnavailable(f"Unknown clip encoder: {value!r}")
