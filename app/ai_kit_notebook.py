"""The Kaggle notebook inside the AI kit, written as nbformat v4 JSON with the json module.

build_notebook() takes the proven render settings as plain values (from ai_kit) so there
is one source of truth. Cell source is plain Python with __TOKENS__ replaced below.
"""

import json


def _lines(text):
    text = text.strip("\n") + "\n"
    return text.splitlines(keepends=True)


def _md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def _code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": _lines(text)}


INTRO = """
# Storyboard Studio - AI clips

Turns each still in this kit into a short AI motion clip with LTX-Video (diffusers, fp16).
**Before you run:** open `manifest.json` and look at each frame's picture next to its
`motion_prompt` (see the CONFIG cell). Then use **Run All**. Download `ai_clips.zip` from the
Output tab when it finishes and **stop the session**.

The model weights are downloaded from Hugging Face and are under the Lightricks LTX-Video
Open Weights License, which you must read. This notebook needs Internet ON and a GPU T4 x2.
"""

CONFIG = """
# ===== CONFIG: the only cell you normally need to edit =====

# Which frames to animate. Leave it empty to animate every frame in the kit.
# Example: ONLY_FRAMES = ["0123456789abcdef0123456789abcdef"]
ONLY_FRAMES = []

# Replace the automatic motion prompt for a frame. Format: frame id -> your prompt.
# LOOK at each frame's picture next to its motion_prompt in manifest.json first.
# The model animates the PICTURE. Use an override whenever the scene text contains an
# action verb (finds, leaps, battles, uncorks, racing ...) or describes something the
# picture does not show. A prompt that contradicted the picture once made the subject
# walk toward the camera and the face melt.
# Rules: describe only what is visible, keep the subject in place, ask only for subtle
# motion (lights flicker, glow pulses, slight breathing), static camera, 90 words or fewer.
# Example:
# PROMPT_OVERRIDES = {
#     "0123456789abcdef0123456789abcdef":
#         "A figure stands beside a neon sign. The figure stays in place. "
#         "The sign glows and flickers. Static camera, locked-off shot.",
# }
PROMPT_OVERRIDES = {}

# Use a different random seed for a frame to get different motion from the same prompt.
# Format: frame id -> whole number. Example: SEED_OVERRIDES = {"0123...": 7}
SEED_OVERRIDES = {}
"""

SETUP = """
import os

# Weights go to /tmp (about 26.5 GB); /kaggle/working only has about 19.5 GB.
os.environ["HF_HOME"] = "/tmp/hf"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import gc
import glob
import json
import re
import shutil
import stat
import time
import zipfile
from pathlib import Path

MODEL_ID = __MODEL_ID__
REVISION = __REVISION__
ALLOW_PATTERNS = __ALLOW_PATTERNS__
WIDTH = __WIDTH__
HEIGHT = __HEIGHT__
NUM_FRAMES = __NUM_FRAMES__
NUM_INFERENCE_STEPS = __STEPS__
FPS = __FPS__
MAX_PROMPT_WORDS = __MAX_WORDS__
NEGATIVE_PROMPT = __NEGATIVE__
ID_RE = re.compile(r"[0-9a-f]{32}")
"""

GPU = """
import torch

if not torch.cuda.is_available():
    raise RuntimeError(
        "No CUDA GPU is attached. Open Session options, set Accelerator to GPU T4 x2, "
        "then Run All again.")
print("GPU:", torch.cuda.get_device_name(0))
"""

LOCATE = """
INPUT_ROOT = "/kaggle/input"
KIT_TMP = Path("/tmp/kit")
ALLOWED_TOP = re.compile(r"manifest\\.json|README\\.txt|[A-Za-z0-9_.-]+\\.ipynb")
ALLOWED_FRAME = re.compile(r"frames/[0-9a-f]{32}\\.png")
MAX_ENTRY_BYTES = 64 * 1024 * 1024


def extract_kit(zip_path, dest):
    # Same safety rules as the app: refuse absolute paths, "..", and symlinks; only
    # extract manifest.json, README.txt, the notebook and frames/<32 hex>.png.
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir():
                continue
            parts = name.split("/")
            if (name.startswith(("/", "\\\\")) or "\\\\" in name or ":" in name
                    or ".." in parts or stat.S_ISLNK(info.external_attr >> 16)):
                raise RuntimeError(f"Unsafe entry in {zip_path}: {name!r}")
            if not (ALLOWED_TOP.fullmatch(name) or ALLOWED_FRAME.fullmatch(name)):
                print("Skipping unexpected entry:", name)
                continue
            if info.file_size > MAX_ENTRY_BYTES:
                raise RuntimeError(f"Entry too large: {name!r}")
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                written = 0
                for chunk in iter(lambda: src.read(1 << 16), b""):
                    written += len(chunk)
                    if written > MAX_ENTRY_BYTES:
                        raise RuntimeError(f"Entry too large: {name!r}")
                    out.write(chunk)


manifests = sorted(glob.glob(f"{INPUT_ROOT}/**/manifest.json", recursive=True))
if len(manifests) > 1:
    raise RuntimeError("More than one manifest.json under /kaggle/input. Attach only one "
                       "AI kit dataset to this notebook. Found: " + ", ".join(manifests))
if len(manifests) == 1:
    manifest_path = Path(manifests[0])
else:
    zips = sorted(glob.glob(f"{INPUT_ROOT}/**/*.zip", recursive=True))
    if not zips:
        raise RuntimeError("No manifest.json and no .zip found under /kaggle/input. Click Add "
                           "Input and attach the dataset made from the AI kit zip.")
    if len(zips) > 1:
        raise RuntimeError("No manifest.json, and more than one .zip under /kaggle/input. "
                           "Attach only one AI kit dataset. Found: " + ", ".join(zips))
    print("Kaggle did not unpack the zip; extracting", zips[0])
    extract_kit(zips[0], KIT_TMP)
    manifest_path = KIT_TMP / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("The zip has no manifest.json at its top level. Upload the AI kit "
                           "zip exactly as downloaded from Storyboard Studio.")

# Every frame PNG is found next to the manifest, wherever the dataset was mounted.
KIT_DIR = manifest_path.parent
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
print("Kit:", KIT_DIR, "-", len(manifest["frames"]), "frame(s) in tape", manifest["tape_title"])
"""

DOWNLOAD = """
from huggingface_hub import snapshot_download

# About 26.5 GB; takes a few minutes. The revision is pinned so results are repeatable.
MODEL_DIR = snapshot_download(MODEL_ID, revision=REVISION, allow_patterns=ALLOW_PATTERNS)
print("Model files:", MODEL_DIR)
"""

LOAD = """
from diffusers import LTXImageToVideoPipeline
from diffusers.utils import export_to_video
from PIL import Image

# fp16 is required: the T4 GPU does not support the other half-precision type well.
pipe = LTXImageToVideoPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.float16)
pipe.enable_model_cpu_offload(gpu_id=0)
pipe.vae.enable_tiling()
print("Pipeline ready.")
"""

HELPERS = """
def prepare_image(path):
    # Center-crop to the 640:352 aspect, then resize with LANCZOS.
    img = Image.open(path).convert("RGB")
    target = WIDTH / HEIGHT
    w, h = img.size
    if w / h > target:
        new_w = round(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = round(w / target)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return img.resize((WIDTH, HEIGHT), Image.LANCZOS)
"""

LOOP = """
OUT_DIR = Path("/kaggle/working/ai_clips")
OUT_DIR.mkdir(parents=True, exist_ok=True)

entries = manifest["frames"]
if ONLY_FRAMES:
    known = {e["frame_id"] for e in entries}
    for fid in ONLY_FRAMES:
        if fid not in known:
            print("WARNING: ONLY_FRAMES lists an id that is not in the kit:", fid)
    entries = [e for e in entries if e["frame_id"] in ONLY_FRAMES]

done, skipped, failed = [], [], []
for number, entry in enumerate(entries, 1):
    fid = entry["frame_id"]
    label = f"[{number}/{len(entries)}] {fid}"
    if not ID_RE.fullmatch(fid):
        failed.append((fid, "bad frame id in manifest"))
        print(label, "FAILED: bad frame id in manifest")
        continue
    out = OUT_DIR / f"{fid}.mp4"
    if out.exists():
        skipped.append(fid)
        print(label, "skipped (already done)")
        continue
    prompt = PROMPT_OVERRIDES.get(fid, entry["motion_prompt"])
    seed = SEED_OVERRIDES.get(fid, entry["seed"])
    words = len(prompt.split())
    if words > MAX_PROMPT_WORDS:
        print(label, f"WARNING: prompt is {words} words; the model cuts it off. Keep it to {MAX_PROMPT_WORDS} or fewer.")
    partial = OUT_DIR / f"{fid}.partial.mp4"
    try:
        started = time.time()
        torch.cuda.reset_peak_memory_stats()
        image = prepare_image(KIT_DIR / "frames" / f"{fid}.png")
        result = pipe(
            image=image,
            prompt=prompt,
            negative_prompt=NEGATIVE_PROMPT,
            width=WIDTH,
            height=HEIGHT,
            num_frames=NUM_FRAMES,
            num_inference_steps=NUM_INFERENCE_STEPS,
            generator=torch.Generator(device="cpu").manual_seed(int(seed)),
        )
        export_to_video(result.frames[0], str(partial), fps=FPS)
        os.replace(partial, out)
        done.append(fid)
        minutes = (time.time() - started) / 60
        peak = torch.cuda.max_memory_allocated() / 1024 ** 3
        print(label, f"done in {minutes:.1f} min, peak VRAM {peak:.1f} GB")
    except Exception as exc:
        failed.append((fid, repr(exc)))
        print(label, "FAILED:", repr(exc))
    finally:
        partial.unlink(missing_ok=True)
        gc.collect()
        torch.cuda.empty_cache()
"""

PACK = """
ZIP_PATH = Path("/kaggle/working/ai_clips.zip")
if ZIP_PATH.exists():
    ZIP_PATH.unlink()
clips = sorted(p for p in OUT_DIR.glob("*.mp4") if ID_RE.fullmatch(p.stem))
with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_STORED) as zf:
    for clip in clips:
        zf.write(clip, arcname=clip.name)  # MP4s only, at the zip root

print(f"Summary: {len(done)} done, {len(skipped)} skipped, {len(failed)} failed.")
for fid, why in failed:
    print("  failed:", fid, why)
print(f"{len(clips)} clip(s) packed in {ZIP_PATH}")
print("Download ai_clips.zip from the Output tab, then STOP THE SESSION")
print("(Session options > Stop session) so you do not use up GPU hours.")
"""


def build_notebook(settings, negative_prompt):
    tokens = {
        "__MODEL_ID__": settings["model"], "__REVISION__": settings["revision"],
        "__ALLOW_PATTERNS__": settings["allow_patterns"], "__WIDTH__": settings["width"],
        "__HEIGHT__": settings["height"], "__NUM_FRAMES__": settings["num_frames"],
        "__STEPS__": settings["num_inference_steps"], "__FPS__": settings["fps"],
        "__MAX_WORDS__": settings["max_prompt_words"], "__NEGATIVE__": negative_prompt,
    }
    setup = SETUP
    for token, value in tokens.items():
        setup = setup.replace(token, json.dumps(value) if isinstance(value, (str, list)) else str(value))
    cells = [
        _md(INTRO), _code(CONFIG), _code(setup), _code(GPU), _code(LOCATE),
        _code(DOWNLOAD), _code(LOAD), _code(HELPERS), _code(LOOP), _code(PACK),
    ]
    return {
        "nbformat": 4,
        "nbformat_minor": 4,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }
