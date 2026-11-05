"""Clip errors. Each carries a friendly message and the HTTP status the route should use."""


class ClipError(Exception):
    status = 502

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class ClipSourceError(ClipError):
    """A frame's PNG is missing or unreadable."""
    status = 409


class EmptyTape(ClipError):
    status = 400


class TooManyFrames(ClipError):
    status = 400


class EncoderUnavailable(ClipError):
    """No usable ffmpeg/libx264."""
    status = 503


class EncodeError(ClipError):
    status = 502
