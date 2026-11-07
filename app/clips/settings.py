"""Clip constants. Changing any of these changes every fingerprint, so old clips go stale."""

WIDTH = 640
HEIGHT = 360
FPS = 15
DURATION = 3.0                      # seconds per frame clip
FRAMES = int(round(DURATION * FPS))  # 45
PRESCALE = (1280, 720)              # source is scaled to this once; crops resample from it
TRANSITION_FRAMES = 4               # VHS tracking hit between frames in a tape export
MAX_EXPORT_FRAMES = 40
CLIP_VERSION = 1                    # bump when the look of the rendering changes
MIMETYPE = "video/mp4"

# ---- imported AI clips ---------------------------------------------------------------
AI_MIN_FRAMES = 8                   # 0.5 s at 15 fps (7.5, rounded up)
AI_MAX_SECONDS = 10                 # longer uploads are trimmed to this
AI_DECODE_TIMEOUT = 120             # seconds; a 2-CPU laptop is slow at 1080p sources
MiB = 1024 * 1024
AI_MAX_ENTRY_BYTES = 64 * MiB       # one video, whether alone or inside a zip
AI_MAX_ZIP_BYTES = 256 * MiB        # total uncompressed size of a zip (and the request cap)
AI_MAX_ZIP_ENTRIES = 40             # = MAX_EXPORT_FRAMES: one clip per frame of a full tape
