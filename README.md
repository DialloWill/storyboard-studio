
# Storyboard Studio

An open-source rebuild of Higgsfield's Cinema Studio, aimed at **music videos**. Create a storyboard for a song, add one frame per section (intro, verse, hook, bridge, outro), pick a camera, shot, lighting and direction preset, and get a generated still for each frame. The result is a storyboard row plus a downloadable shot list (CSV). The interface is styled like a 1990s VHS camcorder.

Built for the ComfyUI "Open Source Higgsfield" Build Night. **#OpenSourceHiggsfield**

> Status: generates real frames with **FLUX 3** (`bfl/flux-3-image`) through the **Comfy Router**. A mock generator (placeholder frames) is the default, so the app also runs without an API key.

![Storyboard Studio: the FlowState tape](docs/screenshot.png)

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python -m flask --app app run
```

Then open http://127.0.0.1:5000. You don't need to activate the venv; calling `.venv\Scripts\python` directly avoids PowerShell execution-policy issues.

Dependencies are pinned in `requirements.txt`. That includes **numpy**, which the Glitch FX use for pixel work; it is installed by the command above.

## Direction and Glitch FX

Two optional groups sit beside camera, shot and lighting. Both default to **None**, which leaves a frame exactly as before.

**Direction** adds composition, lighting and mood wording to the prompt, so it shapes what the generator draws:

- **Monumental**: centered subject, huge scale, deep staging, cool muted tones.
- **One-Point Symmetry**: one-point perspective, mirrored composition, still and cold.
- **Warm Intimate**: close framing, warm practical light, rich skin tones.

**Glitch FX** are real pixel post-processing applied to the image *after* it is generated. They never touch the prompt, and each frame's effect is seeded from its id, so a frame always gets the same glitch.

- **Smear and stretch**: Row Smear (sideways bands), Sky Smear (the same, bright areas only), Burst (radial stretch from the center).
- **Color and optics**: Prism Zoom (radial blur with split color channels).
- **Signal and tape**: Signal Drip (bright pixels melt downward), Band Shift (bands slide left and right), Tape Decay (compression blocks, posterize, faint ghost).

## Animated clips and Play tape

Every frame has an **Animate** control. It makes a 3 second clip (640x360, 15 fps, H.264 MP4) from the frame's existing picture, fully offline: nothing is regenerated and the picture is never modified.

- **Camera move**: Static, Slow zoom in, Slow zoom out, Pan left/right, Tilt up/down. Eased, and never shows an edge. Frames with no stored move use Slow zoom in. A move is saved on the frame only when you pick one.
- **Glitch FX** builds in and fades out over the clip, and every clip gets a VHS treatment (scanlines, rolling tracking band, jitter, chroma bleed, noise). All randomness is seeded from the frame id, so a clip is reproducible.
- **Play tape** joins the frames in storyboard order into one video, with a short VHS tracking glitch between frames.
- Clips live in `data/<tape>/clips/`. A clip or export is rebuilt only when something it depends on changed (the picture, its FX, its camera move, or the frame list); until you re-animate, a changed one shows as STALE instead of playing old content. Renaming a tape changes nothing.
- Each rendering takes a few seconds per frame on a laptop CPU; a 10-frame tape takes about a minute.

Encoding uses ffmpeg. `pip install -r requirements.txt` installs **imageio-ffmpeg**, which bundles an ffmpeg binary; that is used first, and an `ffmpeg` on your PATH is only a fallback. The bundled binary is a GPLv3 build (`--enable-gpl`, includes libx264). It is installed from PyPI at setup, not vendored into this repository, so it does not change this project's MIT license.

## AI clips ($0 via Kaggle)

The app never talks to an AI service. Instead it exports a kit, you run it on Kaggle's free GPU, and you import the finished clips. Import accepts MP4 files from any source (Kaggle, ComfyUI, anything else), not just this notebook.

1. On the tape page, click **Export AI kit**. You get `<tape-title>-ai-kit.zip` (the stills, a `manifest.json` with one motion prompt per frame, a Kaggle notebook, and a `README.txt` with the same steps).
2. On kaggle.com, create a **private dataset** from that zip.
3. Create a notebook, import `storyboard_ai_kit.ipynb`, attach the dataset, set the accelerator to **GPU T4 x2** and turn **Internet** on.
4. **Check every prompt first.** Look at each frame's picture next to its `motion_prompt`. The model animates the picture, so if the scene text has an action verb (finds, leaps, battles, uncorks, racing) or describes something the picture does not show, replace the prompt in the notebook's `PROMPT_OVERRIDES`. A mismatch once made the subject walk toward the camera and the face melt.
5. **Run All.** Setup takes about 4 minutes (a 26.5 GB model download), then about 0.6 minutes per frame. Download `ai_clips.zip` from the Output tab, then **stop the session**.
6. Back on the tape page, click **Import AI clips** and upload `ai_clips.zip`. To add one clip by hand, use **Upload an MP4** on a frame's Animate page.

What import does: each MP4 is treated as untrusted, decoded with ffmpeg, scaled to cover 640x360 and center-cropped at 15 fps, given the same VHS look as the other clips, and re-encoded without audio or metadata (0.5 to 10 seconds). Limits: 40 clips per zip, 64 MB per clip, 256 MB per upload. Play tape uses a frame's AI clip when **Play tape uses: AI clip** is selected on its Animate page and the clip is up to date; otherwise it uses the procedural clip. If the frame's picture changes after import, the AI clip shows as stale and is not used. **Remove AI clip** moves its files to `data/_trash`.

Limits of the technique: subtle motion only (lights flicker, glow pulses, slight breathing), clips of about 1.4 seconds, soft fine detail, and a static camera. Big action shots (leaps, fights, chases) are not expected to work.

The notebook uses Lightricks' LTX-Video, whose weights are published under the LTX-Video Open Weights License. Read that license yourself. This project does not distribute any weights; the notebook downloads them from Hugging Face on Kaggle.

## Running tests

```powershell
.venv\Scripts\python -m pytest -v
```

No test touches the network or reads your `.env`. The clip tests use a fake encoder and a fake video reader; the tests that run real ffmpeg skip themselves when no ffmpeg is available.

## Switching to the Comfy generator

You need a Comfy API key from a workspace that has credits (create one at platform.comfy.org). Edit `.env`:

```
GENERATOR=comfy
COMFY_API_KEY=your-key-here
```

The Comfy generator sends each frame's prompt to `bfl/flux-3-image` through the Comfy Router, downloads the result right away, and saves it as a PNG. If a request fails (bad key, no credits, moderation, timeout), the app shows "Image generation failed" and saves nothing. Never commit `.env`.

## Roadmap

- Mux a song under the tape
- Configurable model choice
- Audio analysis

## Project structure

```
app/
  __init__.py      create_app(config=None) factory
  routes.py        thin Flask routes
  storage.py       all file reads/writes and id/filename validation
  presets.py       sections, cameras, shots, lighting, direction, glitch FX
  fx.py            Glitch FX pixel post-processing (numpy)
  motion.py        camera moves (allowlist, easing, crop windows)
  clips/           animated clips: render, VHS pass, encoders and normalizer (ffmpeg), fingerprints, imported AI clips
  ai_kit.py        Export AI kit: motion prompts, manifest, zip
  ai_kit_notebook.py  the Kaggle notebook (nbformat v4 JSON)
  ai_import.py     Import AI clips: safe zip handling and single uploads
  display.py       viewfinder text: timecode, date stamp, channel label
  prompt.py        build_prompt(...) pure function
  generators/      ImageGenerator base, MockGenerator, ComfyGenerator (Comfy Router, FLUX 3)
  templates/       Jinja templates (inline CSS, no JavaScript)
docs/              README screenshot
tests/             pytest suite
workflows/         not used: the Router calls the model directly, so no workflow file is needed
data/              storyboards on disk (created at runtime, git-ignored)
```

## License

MIT. See [LICENSE](LICENSE).