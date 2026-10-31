# Storyboard Studio

An open-source rebuild of Higgsfield's Cinema Studio, aimed at **music videos**.
Create a storyboard for a song, add one frame per section (intro, verse, hook,
bridge, outro), pick a camera, shot, lighting and direction preset, and get a generated
still for each frame. The result is a storyboard row plus a downloadable shot
list (CSV).

Built for the ComfyUI "Open Source Higgsfield" Build Night. **#OpenSourceHiggsfield**

> Status: runs end to end against a **mock** image generator (placeholder
> frames). The Comfy Cloud API v2 generator is implemented at build night.

![Screenshot placeholder](docs/screenshot.png)

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python -m flask --app app run
```

Then open http://127.0.0.1:5000. You don't need to activate the venv; calling
`.venv\Scripts\python` directly avoids PowerShell execution-policy issues.

## Running tests

```powershell
.venv\Scripts\python -m pytest -v
```

No test touches the network or reads your `.env`.

## Switching to the Comfy generator

Edit `.env`:

```
GENERATOR=comfy
COMFY_API_KEY=your-key-here
```

Until the integration is written (build night), generating a frame with
`GENERATOR=comfy` shows "Image generation failed" and saves nothing. Never
commit `.env`.

## Project structure

```
app/
  __init__.py      create_app(config=None) factory
  routes.py        thin Flask routes
  storage.py       all file reads/writes and id/filename validation
  presets.py       sections, cameras, shots, lighting, direction
  prompt.py        build_prompt(...) pure function
  generators/      ImageGenerator base, MockGenerator, ComfyGenerator stub
  templates/       Jinja templates (inline CSS, no JavaScript)
tests/             pytest suite
workflows/         ComfyUI workflow JSON (added at build night)
data/              storyboards on disk (created at runtime, git-ignored)
```

## License

MIT. See [LICENSE](LICENSE).
