"""Clip normalizers: decode an untrusted video into RGB frames at the clip spec.

Same shape as ClipEncoder: an ABC, a real ffmpeg implementation, and config-driven
selection (tests pass an instance as app.config["CLIP_NORMALIZER"]). The normalizer
only decodes and rescales; the VHS look and the H.264 encode happen afterwards in
app/clips/ai.py, using the existing encoder.
"""

import tempfile
import threading
import subprocess
from abc import ABC, abstractmethod

import numpy as np

from .encoders import INSTALL_HINT, _popen_flags, find_ffmpeg
from .errors import EncoderUnavailable, InvalidClip

UNREADABLE = "That file could not be read as a video."
TIMED_OUT = "That video took too long to process. Try a shorter or smaller clip."


class ClipNormalizer(ABC):
    def check_available(self):
        """Raise EncoderUnavailable if this normalizer cannot run. Called before any work."""

    @abstractmethod
    def read_frames(self, path, size, fps, max_seconds):
        """Yield uint8 RGB arrays of shape (h, w, 3) for the video at `path`.

        Scaled to cover `size` = (w, h) and center-cropped, resampled to `fps`, audio and
        metadata ignored, cut off after `max_seconds`. Raises InvalidClip when the file
        cannot be decoded (the message is always fixed friendly text).
        """


def decode_command(exe, path, size, fps, max_seconds):
    """The ffmpeg argument list (never a shell string). Each flag is deliberate:

    -nostdin                 never read or wait on our stdin
    -protocol_whitelist file the input can only be a local file, so nothing inside the
                             upload can make ffmpeg open a network or other protocol
    -f mov                   force the mp4/mov demuxer instead of probing, so a crafted
                             file cannot be treated as a playlist or concat script
    -an -sn -dn              no audio, subtitle or data streams
    -map_metadata -1         no container metadata carried over
    -t                       caps the decode work on very long files
    """
    w, h = size
    return [exe, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "file", "-f", "mov", "-i", f"file:{path}",
            "-an", "-sn", "-dn", "-map_metadata", "-1",
            "-vf", f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
            "-t", str(max_seconds),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


class FfmpegNormalizer(ClipNormalizer):
    def __init__(self, timeout=None):
        self.timeout = timeout

    def _exe(self):
        exe = find_ffmpeg()
        if not exe:
            raise EncoderUnavailable(INSTALL_HINT)
        return exe

    def check_available(self):
        self._exe()

    def read_frames(self, path, size, fps, max_seconds):
        from . import settings
        exe = self._exe()
        w, h = size
        frame_bytes = w * h * 3
        timeout = self.timeout if self.timeout is not None else settings.AI_DECODE_TIMEOUT
        cmd = decode_command(exe, path, size, fps, max_seconds)
        timed_out = threading.Event()
        with tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=err, **_popen_flags())
            except OSError as exc:
                raise InvalidClip(UNREADABLE) from exc

            def _expire():
                timed_out.set()
                proc.kill()

            # A watchdog: communicate(timeout=) does not fit a streamed pipe.
            timer = threading.Timer(timeout, _expire)
            timer.daemon = True
            timer.start()
            try:
                while True:
                    buf = proc.stdout.read(frame_bytes)
                    if len(buf) < frame_bytes:  # EOF (a partial last frame is dropped)
                        break
                    yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
                code = proc.wait()
            finally:
                timer.cancel()
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                proc.stdout.close()
            if timed_out.is_set():
                raise InvalidClip(TIMED_OUT)
            if code != 0:  # the detail stays in ffmpeg's stderr; it is never shown
                raise InvalidClip(UNREADABLE)


def get_normalizer(config):
    value = config.get("CLIP_NORMALIZER", "ffmpeg")
    if isinstance(value, ClipNormalizer):
        return value
    if value == "ffmpeg":
        return FfmpegNormalizer()
    raise EncoderUnavailable(f"Unknown clip normalizer: {value!r}")
