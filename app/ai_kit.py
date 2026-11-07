"""Export AI kit: a zip a person uploads to Kaggle as a private dataset.

The app never talks to an AI service and never ships model weights. The kit holds the
frame stills, a manifest with one motion prompt per frame, a notebook that runs the
model on Kaggle's free GPU, and plain instructions. Everything here is pure except
the final zip assembly, which works from bytes handed in.
"""

import io
import json
import re
import unicodedata
import zipfile
from datetime import datetime, timezone

from . import display, motion, presets, storage
from .ai_kit_notebook import build_notebook

SCHEMA_VERSION = 1

# The settings proven on a Kaggle T4 x2. Do not change them without re-testing.
MODEL_ID = "Lightricks/LTX-Video"
MODEL_REVISION = "8984fa25007f376c1a299016d0957a37a2f797bb"
ALLOW_PATTERNS = ["model_index.json", "scheduler/*", "tokenizer/*",
                  "text_encoder/*", "transformer/*", "vae/*"]
WIDTH = 640
HEIGHT = 352
NUM_FRAMES = 33
STEPS = 30
FPS = 24
DTYPE = "float16"
NEGATIVE_PROMPT = ("walking, running, moving toward camera, approaching, zoom in, "
                   "camera movement, face close-up, worst quality, inconsistent motion, "
                   "blurry, jittery, distorted, morphing face, melting")

MAX_PROMPT_WORDS = 90   # LTX truncates at 128 tokens; words average over one token each
STAY_LINE = "The subject stays in place."
CAMERA_LINE = "Static camera, locked-off shot."
DEFAULT_CUE = "Light shifts subtly."
LIGHT_CUES = {
    "neon": "Neon lights flicker softly.",
    "golden-hour": "Warm light shifts gently.",
    "glitch": "Light flickers.",
    "cyberpunk-wave": "Light flickers.",
    "noir": "Shadows and light drift slightly.",
}

KIT_PNG_DIR = "frames"
NOTEBOOK_NAME = "storyboard_ai_kit.ipynb"


def settings_block():
    return {"model": MODEL_ID, "revision": MODEL_REVISION, "allow_patterns": ALLOW_PATTERNS,
            "dtype": DTYPE, "width": WIDTH, "height": HEIGHT, "num_frames": NUM_FRAMES,
            "num_inference_steps": STEPS, "fps": FPS, "max_prompt_words": MAX_PROMPT_WORDS}


def build_motion_prompt(scene, lighting):
    """Scene text + stay-in-place line + a subtle lighting cue + the camera line.

    Deterministic. Capped at MAX_PROMPT_WORDS words by trimming the scene text from the
    end; the fixed lines (and so the camera line) are never trimmed. No gendered pronouns
    in any text this function adds.
    """
    tail = f"{STAY_LINE} {LIGHT_CUES.get(lighting, DEFAULT_CUE)} {CAMERA_LINE}"
    budget = max(0, MAX_PROMPT_WORDS - len(tail.split()))
    head = " ".join(str(scene or "").split()[:budget])
    if head and head[-1] not in ".!?":
        head += "."
    return f"{head} {tail}".strip()


def seed_for(frame_id):
    """Stable seed from the frame id: re-exporting gives the same motion."""
    return int(frame_id, 16) % (2 ** 31 - 1)


def slugify_title(title, fallback):
    """A safe ASCII filename stem: lowercase a-z, 0-9 and single dashes, at most 40 chars."""
    ascii_text = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    slug = "-".join(re.findall(r"[a-z0-9]+", ascii_text.lower()))[:40].strip("-")
    return slug or fallback


def kit_filename(board):
    return f"{slugify_title(board.get('song_title'), board['id'])}-ai-kit.zip"


def _frame_entry(index, frame):
    section = presets.get_preset("section", frame["section"])
    return {
        "frame_id": frame["id"],
        "order": index,
        "section": frame["section"],
        "channel": display.channel_label(frame["section"], section["name"] if section else frame["section"]),
        "scene": frame.get("scene", ""),
        "prompt": frame.get("prompt", ""),
        "presets": {k: frame.get(k) for k in ("camera", "shot", "lighting", "direction", "fx")},
        "camera_move": motion.resolve_move(frame.get("camera_move")),
        "seed": seed_for(frame["id"]),
        "motion_prompt": build_motion_prompt(frame.get("scene", ""), frame.get("lighting")),
    }


def build_manifest(board, created=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "tape_id": board["id"],
        "tape_title": board.get("song_title", ""),
        "created": created or datetime.now(timezone.utc).isoformat(),
        "settings": settings_block(),
        "negative_prompt": NEGATIVE_PROMPT,
        "frames": [_frame_entry(i, f) for i, f in enumerate(storage.sorted_frames(board))],
    }


README_TEXT = """\
STORYBOARD STUDIO - AI KIT
==========================
Turns the stills of one tape into short AI motion clips on Kaggle's free GPU.
Storyboard Studio never contacts any AI service; you run the model yourself.

STEP BY STEP (Kaggle)
---------------------
1. Sign in at kaggle.com. Create > New Dataset. Upload THIS zip file as it is.
   Keep it Private. Give it any name.
2. Create > New Notebook. Click File > Import Notebook and choose
   storyboard_ai_kit.ipynb from this kit (or open the copy inside your dataset).
3. In the notebook sidebar, click Add Input and attach the dataset you just made.
4. Session options: set Accelerator to GPU T4 x2, and turn Internet ON
   (the model is downloaded from Hugging Face; it is about 26.5 GB).
5. BEFORE running, read the section "Check every prompt" below.
6. Run > Run All. Setup takes about 4 minutes, then about 0.6 minutes per frame.
7. When it finishes, open the Output tab and download ai_clips.zip.
8. Stop the session (Session options > Stop session) so you do not burn GPU hours.
9. In Storyboard Studio open the tape and choose "Import AI clips". Upload
   ai_clips.zip. Any MP4 files work, from Kaggle, ComfyUI or anywhere else.

CHECK EVERY PROMPT (important)
------------------------------
Open manifest.json and look at each frame's picture next to its "motion_prompt".
The model animates the PICTURE. If the prompt says something the picture does not
show, it invents it: in one test, a prompt that said "holding a bottle" for a picture
where the bottle sat on a block made the subject walk toward the camera and the
face melt.

Replace the prompt (PROMPT_OVERRIDES in the notebook's CONFIG cell) when the scene
text contains an action verb (finds, leaps, battles, uncorks, racing ...) or
describes something the picture does not show. Example:

    PROMPT_OVERRIDES = {
        "0123456789abcdef0123456789abcdef":
            "A figure stands beside a neon sign. The figure stays in place. "
            "The sign glows and flickers. Static camera, locked-off shot.",
    }

PROMPT RULES THAT WORKED
------------------------
- Describe exactly what is in the picture.
- Keep the subject in place.
- Ask only for subtle motion: lights flicker, glow pulses, slight breathing or
  a small head turn.
- Static, locked-off camera.
- Keep prompts at or under 90 words (the model cuts off at about 128 tokens).

LIMITS
------
Big action shots (leaps, fights, chases) are not expected to work. Expect
subtle motion, about 1.4 second clips and soft fine detail.

LICENSE
-------
The LTX-Video weights are published by Lightricks under the
LTX-Video Open Weights License. You must read and follow that license yourself.
Storyboard Studio does not distribute any weights; the notebook downloads them
from Hugging Face on Kaggle.

FILES IN THIS KIT
-----------------
frames/<frame_id>.png     the stored picture for each frame
manifest.json             settings and one entry per frame (prompt, seed, presets)
storyboard_ai_kit.ipynb   the Kaggle notebook
README.txt                this file
"""


def build_kit_zip(board, pngs, created=None):
    """Zip bytes for a tape. `pngs` maps frame id -> PNG bytes for every frame, stored unchanged."""
    manifest = build_manifest(board, created)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for entry in manifest["frames"]:
            zf.writestr(f"{KIT_PNG_DIR}/{entry['frame_id']}.png", pngs[entry["frame_id"]],
                        compress_type=zipfile.ZIP_STORED)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2),
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(NOTEBOOK_NAME, json.dumps(build_notebook(settings_block(), NEGATIVE_PROMPT), indent=1),
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("README.txt", README_TEXT, compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()
