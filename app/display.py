"""Small pure helpers for the VCR on-screen-display text. No Flask, no I/O."""

from datetime import datetime

from .presets import SECTION_ORDER

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
SECONDS_PER_FRAME = 12
STAMP_YEAR = 1996


def timecode(index):
    """HH:MM:SS:FF for a frame position; each frame sits 12 seconds further along the tape."""
    total = index * SECONDS_PER_FRAME
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:00"


def date_stamp(created_iso):
    """Camcorder date stamp like 'OCT 29 1996': the real month and day, a fixed year."""
    try:
        created = datetime.fromisoformat(created_iso)
    except (TypeError, ValueError):
        return f"--- -- {STAMP_YEAR}"
    return f"{MONTHS[created.month - 1]} {created.day:02d} {STAMP_YEAR}"


def channel_label(section_id, section_name):
    """'CH.01 INTRO' from the section's position in the fixed order."""
    if section_id in SECTION_ORDER:
        number = f"{SECTION_ORDER.index(section_id) + 1:02d}"
    else:
        number = "--"
    return f"CH.{number} {section_name.upper()}"
