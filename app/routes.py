import csv
import io

from flask import (Blueprint, Response, abort, current_app, redirect,
                   render_template, request, send_file, url_for)

from . import display, presets, storage
from .generators import get_generator
from .prompt import build_prompt

bp = Blueprint("main", __name__)

MAX_TITLE = 100
MAX_SCENE = 300
GENERATION_FAILED = "Image generation failed. Check the generator configuration or API credits."


def _data_dir():
    return current_app.config["DATA_DIR"]


def _get_board_or_404(storyboard_id):
    board = storage.load_storyboard(_data_dir(), storyboard_id)
    if board is None:
        abort(404)
    return board


def _render_index(error=None, song_title="", status=200):
    return render_template(
        "index.html",
        storyboards=storage.list_storyboards(_data_dir()),
        error=error,
        song_title=song_title,
        max_title=MAX_TITLE,
    ), status


def _frame_views(board):
    """Frames in storyboard order, plus the on-screen-display text for each."""
    views = []
    for index, frame in enumerate(storage.sorted_frames(board)):
        section = presets.get_preset("section", frame["section"])
        section_name = section["name"] if section else frame["section"]
        views.append({
            **frame,
            "section_name": section_name,
            "channel": display.channel_label(frame["section"], section_name),
            "timecode": display.timecode(index),
            "stamp": display.date_stamp(frame["created"]),
        })
    return views


def _render_board(board, error=None, form=None, status=200):
    form = form or {
        "section": presets.DEFAULT_SECTION,
        "scene": "",
        "camera": presets.DEFAULT_CAMERA,
        "shot": presets.DEFAULT_SHOT,
        "lighting": presets.DEFAULT_LIGHTING,
    }
    return render_template(
        "storyboard.html",
        board=board,
        frames=_frame_views(board),
        error=error,
        form=form,
        presets=presets,
        max_scene=MAX_SCENE,
        names={g: {p["id"]: p["name"] for p in presets.GROUPS[g]} for g in presets.GROUPS},
    ), status


@bp.get("/")
def index():
    return _render_index()


@bp.post("/storyboards")
def create_storyboard():
    title = request.form.get("song_title", "").strip()
    if not title:
        return _render_index("Song title is required.", title, 400)
    if len(title) > MAX_TITLE:
        return _render_index(f"Song title must be {MAX_TITLE} characters or fewer.", title, 400)
    board = storage.create_storyboard(_data_dir(), title)
    return redirect(url_for("main.show_storyboard", storyboard_id=board["id"]))


@bp.get("/storyboards/<storyboard_id>")
def show_storyboard(storyboard_id):
    return _render_board(_get_board_or_404(storyboard_id))


@bp.post("/storyboards/<storyboard_id>/frames")
def add_frame(storyboard_id):
    board = _get_board_or_404(storyboard_id)
    form = {
        "section": request.form.get("section", ""),
        "scene": request.form.get("scene", "").strip(),
        "camera": request.form.get("camera", ""),
        "shot": request.form.get("shot", ""),
        "lighting": request.form.get("lighting", ""),
    }

    error = None
    if not form["scene"]:
        error = "Scene description is required."
    elif len(form["scene"]) > MAX_SCENE:
        error = f"Scene description must be {MAX_SCENE} characters or fewer."
    else:
        for group in ("section", "camera", "shot", "lighting"):
            if presets.get_preset(group, form[group]) is None:
                error = f"Unknown {group} option."
                break
    if error:
        return _render_board(board, error, form, 400)

    prompt = build_prompt(form["scene"], form["section"], form["camera"],
                          form["shot"], form["lighting"])
    try:
        png = get_generator(current_app.config).generate(prompt)
    except Exception as exc:  # any generator or config failure; never log the key
        current_app.logger.error("Image generation failed: %s: %s", type(exc).__name__, exc)
        return _render_board(board, GENERATION_FAILED, form, 502)

    storage.add_frame(_data_dir(), storyboard_id, {**form, "prompt": prompt}, png)
    return redirect(url_for("main.show_storyboard", storyboard_id=storyboard_id))


def _frame_file_or_404(storyboard_id, filename):
    path = storage.frame_image_path(_data_dir(), storyboard_id, filename)
    if path is None:
        abort(404)
    return path


@bp.get("/storyboards/<storyboard_id>/frames/<filename>")
def frame_image(storyboard_id, filename):
    path = _frame_file_or_404(storyboard_id, filename)
    return send_file(path, mimetype="image/png")


@bp.get("/storyboards/<storyboard_id>/frames/<filename>/download")
def frame_download(storyboard_id, filename):
    path = _frame_file_or_404(storyboard_id, filename)
    return send_file(path, mimetype="image/png", as_attachment=True, download_name=filename)


def _csv_safe(value):
    """Stop spreadsheets from treating user text as a formula."""
    value = str(value)
    if value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


@bp.get("/storyboards/<storyboard_id>/shotlist.csv")
def shotlist(storyboard_id):
    board = _get_board_or_404(storyboard_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["section", "scene", "camera", "shot", "lighting", "prompt", "filename"])
    for f in storage.sorted_frames(board):
        writer.writerow([
            f["section"],
            _csv_safe(f["scene"]),
            f["camera"], f["shot"], f["lighting"],
            _csv_safe(f["prompt"]),
            f["filename"],
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="shotlist.csv"'},
    )
