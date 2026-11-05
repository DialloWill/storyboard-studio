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
