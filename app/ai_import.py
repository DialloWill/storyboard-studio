"""Import AI clips: a zip of MP4s, or one MP4, treated as untrusted from the first byte.

Every upload goes: stream to a temp file inside the tape's clips folder (a name the app
makes, never one the user chose) -> cheap magic check -> decode/normalize/encode through
app/clips/ai.py. Reasons shown to the user are fixed strings; raw ffmpeg output and
exception text are never shown.
"""

import re
import stat
import zipfile

from . import storage
from .clips import ai, settings
from .clips.errors import ClipError, InvalidClip

# One mp4 at the zip root, or one folder level down (a zipped "ai_clips" folder).
ENTRY_RE = re.compile(r"^(?:[^/\\:]+/)?([0-9a-f]{32})\.mp4$")
CHUNK = 64 * 1024
# First atom types real MP4/MOV files start with; ffmpeg still has the final word.
ATOMS = {b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip", b"pnot"}

NOT_VIDEO = "Not a readable MP4 video."
TOO_LARGE = "Too large."
UNSAFE = "Unsafe file name."
NOT_CLIP_NAME = "Not named <frame id>.mp4."
UNKNOWN = "Not a frame in this tape."
DUPLICATE = "More than one entry for this frame."
ENCRYPTED = "Encrypted entries are not supported."
TOTAL_LIMIT = "Skipped: the zip's total size limit was reached."


class TooBig(Exception):
    pass


class BadUpload(ClipError):
    """The whole upload is unusable (not a zip, too many entries). Shown as a form error."""
    status = 400


def mib(n):
    return f"{n // settings.MiB} MB"


def limits_text():
    return (f"Up to {settings.AI_MAX_ZIP_ENTRIES} clips, {mib(settings.AI_MAX_ENTRY_BYTES)} each, "
            f"{mib(settings.AI_MAX_ZIP_BYTES)} in total. Clips between half a second and "
            f"{settings.AI_MAX_SECONDS} seconds.")


def copy_limited(src, dest, limit):
    """Copy a stream to `dest`, counting the bytes actually read (declared sizes lie)."""
    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                return written
            written += len(chunk)
            if written > limit:
                raise TooBig()
            out.write(chunk)


def looks_like_video(path):
    with open(path, "rb") as fh:
        head = fh.read(12)
    return len(head) >= 12 and head[4:8] in ATOMS


def _import_file(data_dir, storyboard_id, frame_id, src_stream, limit, encoder, normalizer):
    """Stream, check and import one video. Returns (status, reason); always cleans up."""
    tmp = storage.new_clip_tmp(data_dir, storyboard_id, frame_id)
    try:
        try:
            size = copy_limited(src_stream, tmp, limit)
        except TooBig:
            return "skipped", TOO_LARGE
        except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError):
            return "invalid", NOT_VIDEO
        if size == 0 or not looks_like_video(tmp):
            return "invalid", NOT_VIDEO
        try:
            ai.import_clip(data_dir, storyboard_id, frame_id, tmp, encoder, normalizer)
        except InvalidClip as exc:
            return "invalid", exc.message
        return "imported", ""
    finally:
        tmp.unlink(missing_ok=True)


def import_single(data_dir, storyboard_id, frame_id, fileobj, encoder, normalizer):
    """One uploaded MP4 for one frame. The upload's file name is ignored. Returns (status, reason)."""
    return _import_file(data_dir, storyboard_id, frame_id, fileobj,
                        settings.AI_MAX_ENTRY_BYTES, encoder, normalizer)


def classify(infos, frame_ids):
    """Decide each entry before reading any bytes. Returns a list of
    (name, frame_id or None, reason or None, info); a reason means skipped."""
    rows = []
    for info in infos:
        name = info.filename
        parts = name.split("/")
        frame_id, reason = None, None
        if info.is_dir():
            continue
        if (name.startswith(("/", "\\")) or "\\" in name or ".." in parts
                or re.match(r"^[A-Za-z]:", name) or stat.S_ISLNK(info.external_attr >> 16)):
            reason = UNSAFE
        elif info.flag_bits & 0x1:
            reason = ENCRYPTED
        else:
            m = ENTRY_RE.fullmatch(name)
            if m is None:
                reason = NOT_CLIP_NAME
            else:
                frame_id = m.group(1)
                if frame_id not in frame_ids:
                    reason = UNKNOWN
        rows.append([name, frame_id, reason, info])
    counts = {}
    for _, frame_id, reason, _ in rows:
        if frame_id and reason is None:
            counts[frame_id] = counts.get(frame_id, 0) + 1
    for row in rows:
        if row[1] and row[2] is None and counts[row[1]] > 1:
            row[2] = DUPLICATE
    return rows


def import_zip(data_dir, storyboard_id, board, fileobj, encoder, normalizer):
    """Import every valid <frame id>.mp4 in the zip. Returns a list of result dicts:
    {"name", "status": "imported" | "skipped" | "invalid", "reason"}.

    The archive's own names are only ever matched against a strict pattern; the temp
    file name and the destination come from the app. Raises BadUpload if the upload as
    a whole is unusable.
    """
    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError):
        raise BadUpload("That file is not a valid zip.")
    with zf:
        infos = zf.infolist()
        if len(infos) > settings.AI_MAX_ZIP_ENTRIES:
            raise BadUpload(f"That zip has too many entries. {limits_text()}")
        frame_ids = {f["id"] for f in board["frames"]}
        results = []
        declared_total = 0
        actual_total = 0
        for name, frame_id, reason, info in classify(infos, frame_ids):
            shown = name[:120]
            if reason is None:
                if info.file_size > settings.AI_MAX_ENTRY_BYTES:
                    reason = TOO_LARGE
                elif declared_total + info.file_size > settings.AI_MAX_ZIP_BYTES:
                    reason = TOTAL_LIMIT
            if reason is not None:
                results.append({"name": shown, "status": "skipped", "reason": reason})
                continue
            declared_total += info.file_size
            allowed = min(settings.AI_MAX_ENTRY_BYTES, settings.AI_MAX_ZIP_BYTES - actual_total)
            counted = None
            try:
                with zf.open(info) as stream:
                    counted = _CountingReader(stream)
                    status, why = _import_file(data_dir, storyboard_id, frame_id, counted,
                                               allowed, encoder, normalizer)
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
                status, why = "invalid", NOT_VIDEO
            if counted is not None:
                actual_total += counted.total
            results.append({"name": shown, "status": status, "reason": why,
                            "frame_id": frame_id})
    return results


class _CountingReader:
    """Wraps a zip member stream, counting the bytes really read for the zip-wide total."""

    def __init__(self, stream):
        self.stream = stream
        self.total = 0

    def read(self, n=-1):
        data = self.stream.read(n)
        self.total += len(data)
        return data
