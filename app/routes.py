import csv
import io

from flask import (Blueprint, Response, abort, current_app, redirect,
                   render_template, request, send_file, url_for)

from PIL import Image

from . import clips, display, fx, motion, presets, storage
from .clips import settings as clip_settings
from .clips.encoders import get_encoder
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


def _title_error(title):
    """Shared by create and rename; title is already stripped."""
    if not title:
        return "Song title is required."
    if len(title) > MAX_TITLE:
        return f"Song title must be {MAX_TITLE} characters or fewer."
    return None


def _render_index(error=None, song_title="", status=200):
    return render_template(
        "index.html",
        storyboards=storage.list_storyboards(_data_dir()),
        error=error,
        song_title=song_title,
        max_title=MAX_TITLE,
    ), status


def direction_id(frame):
    """A frame's direction id; missing or no-longer-existing ids read as 'none'."""
    found = frame.get("direction")
    if presets.get_preset("direction", found) is None:
        return presets.DEFAULT_DIRECTION
    return found


def fx_id(frame):
    """A frame's glitch FX id; missing or no-longer-existing ids read as 'none'."""
    found = frame.get("fx")
    if presets.get_preset("fx", found) is None:
        return presets.DEFAULT_FX
    return found


def _apply_fx(png, fx_name, frame_id):
    """Run a glitch effect over generated PNG bytes; "none" returns them untouched."""
    if fx_name == presets.DEFAULT_FX:
        return png
    with Image.open(io.BytesIO(png)) as source:
        image = source.convert("RGB")
    result = fx.apply_fx(image, fx_name, fx.seed_from_frame_id(frame_id))
    out = io.BytesIO()
    result.save(out, format="PNG")
    return out.getvalue()


def _frame_views(board):
    """Frames in storyboard order, plus the on-screen-display text for each."""
    views = []
    for index, frame in enumerate(storage.sorted_frames(board)):
        section = presets.get_preset("section", frame["section"])
        section_name = section["name"] if section else frame["section"]
        views.append({
            **frame,
            "section_name": section_name,
            "direction": direction_id(frame),
            "fx": fx_id(frame),
            "move_name": motion.MOVE_NAMES[motion.resolve_move(frame.get("camera_move"))],
            "move_explicit": motion.is_valid_move(frame.get("camera_move")),
            "clip_state": clips.frame_state(_data_dir(), board["id"], frame)[0],
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
        "direction": presets.DEFAULT_DIRECTION,
        "fx": presets.DEFAULT_FX,
        "camera_move": "",
    }
    return render_template(
        "storyboard.html",
        board=board,
        frames=_frame_views(board),
        moves=motion.MOVES,
        default_move_name=motion.MOVE_NAMES[motion.DEFAULT_MOVE],
        tape_state=clips.tape_state(_data_dir(), board["id"], board)[0],
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
    error = _title_error(title)
    if error:
        return _render_index(error, title, 400)
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
        # Absent means "none" (older clients); a present but unknown value is rejected.
        "direction": request.form.get("direction", presets.DEFAULT_DIRECTION),
        "fx": request.form.get("fx", presets.DEFAULT_FX),
    }

    # Empty means "default move": nothing is stored unless the user explicitly picks one.
    move = request.form.get("camera_move", "")

    error = None
    if not form["scene"]:
        error = "Scene description is required."
    elif len(form["scene"]) > MAX_SCENE:
        error = f"Scene description must be {MAX_SCENE} characters or fewer."
    else:
        for group in ("section", "camera", "shot", "lighting", "direction", "fx"):
            if presets.get_preset(group, form[group]) is None:
                error = f"Unknown {group} option."
                break
        if error is None and move and not motion.is_valid_move(move):
            error = "Unknown camera move option."
    if error:
        return _render_board(board, error, {**form, "camera_move": move}, 400)

    prompt = build_prompt(form["scene"], form["section"], form["camera"],
                          form["shot"], form["lighting"], form["direction"])
    frame_id = storage.new_id()  # minted first: the fx seed is derived from it
    try:
        png = get_generator(current_app.config).generate(prompt)
        png = _apply_fx(png, form["fx"], frame_id)
    except Exception as exc:  # any generator or config failure; never log the key
        current_app.logger.error("Image generation failed: %s: %s", type(exc).__name__, exc)
        return _render_board(board, GENERATION_FAILED, form, 502)

    fields = {**form, "prompt": prompt}
    if move:
        fields["camera_move"] = move
    storage.add_frame(_data_dir(), storyboard_id, fields, png, frame_id=frame_id)
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
    writer.writerow(["section", "scene", "camera", "shot", "lighting", "direction", "fx", "prompt", "filename"])
    for f in storage.sorted_frames(board):
        writer.writerow([
            f["section"],
            _csv_safe(f["scene"]),
            f["camera"], f["shot"], f["lighting"],
            _csv_safe(direction_id(f)),
            _csv_safe(fx_id(f)),
            _csv_safe(f["prompt"]),
            f["filename"],
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="shotlist.csv"'},
    )


@bp.app_errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="Nothing here. That tape or frame "
                           "does not exist, or it was already deleted."), 404


@bp.route("/storyboards/<storyboard_id>/rename", methods=["GET", "POST"])
def rename_storyboard(storyboard_id):
    board = _get_board_or_404(storyboard_id)
    if request.method == "GET":
        return render_template("rename.html", board=board, title=board["song_title"],
                               error=None, max_title=MAX_TITLE)
    title = request.form.get("song_title", "").strip()
    error = _title_error(title)
    if error:
        return render_template("rename.html", board=board, title=title,
                               error=error, max_title=MAX_TITLE), 400
    if not storage.rename_storyboard(_data_dir(), storyboard_id, title):
        abort(404)
    return redirect(url_for("main.show_storyboard", storyboard_id=storyboard_id))


@bp.route("/storyboards/<storyboard_id>/delete", methods=["GET", "POST"])
def delete_storyboard(storyboard_id):
    board = _get_board_or_404(storyboard_id)
    if request.method == "GET":
        return render_template(
            "confirm.html", heading="Erase tape",
            question=f"Erase tape “{board['song_title']}” and its {len(board['frames'])} frame(s)?",
            action=url_for("main.delete_storyboard", storyboard_id=storyboard_id),
            cancel=url_for("main.show_storyboard", storyboard_id=storyboard_id))
    try:
        trashed = storage.trash_storyboard(_data_dir(), storyboard_id)
    except PermissionError:
        # Windows refuses to rename a folder while a browser holds a clip inside it open.
        return render_template(
            "error.html", message="This tape could not be erased because a video from it "
            "is still open. Close the video tab, then try again."), 409
    if not trashed:
        abort(404)
    return redirect(url_for("main.index"))


@bp.route("/storyboards/<storyboard_id>/frames/<frame_id>/delete", methods=["GET", "POST"])
def delete_frame(storyboard_id, frame_id):
    board = _get_board_or_404(storyboard_id)
    frame = next((f for f in board["frames"]
                  if storage.is_valid_id(frame_id) and f.get("id") == frame_id), None)
    if frame is None:
        abort(404)
    back = url_for("main.show_storyboard", storyboard_id=storyboard_id)
    if request.method == "GET":
        return render_template(
            "confirm.html", heading="Erase frame",
            question=f"Erase this frame? “{frame['scene']}”",
            action=url_for("main.delete_frame", storyboard_id=storyboard_id, frame_id=frame_id),
            cancel=back)
    if not storage.trash_frame(_data_dir(), storyboard_id, frame_id):
        abort(404)
    return redirect(back)


# ---- animated clips ---------------------------------------------------------------

def _frame_or_404(board, frame_id):
    frame = next((f for f in board["frames"]
                  if storage.is_valid_id(frame_id) and f.get("id") == frame_id), None)
    if frame is None:
        abort(404)
    return frame


def _clip_failure(exc):
    """(message, status) for any failure while making a clip; never echoes internals."""
    if isinstance(exc, clips.ClipError):
        if not isinstance(exc, clips.EncodeError):
            return exc.message, exc.status
        current_app.logger.error("Clip encoding failed: %s", exc.message)
    else:
        current_app.logger.error("Clip rendering failed: %s: %s", type(exc).__name__, exc)
    return "Clip rendering failed. Nothing was saved.", 502


def _render_animate(storyboard_id, frame_id, error=None, status=200):
    board = _get_board_or_404(storyboard_id)
    frame = _frame_or_404(board, frame_id)
    state = clips.frame_state(_data_dir(), storyboard_id, frame)[0]
    section = presets.get_preset("section", frame["section"])
    return render_template(
        "animate.html",
        board=board,
        frame=frame,
        section_name=section["name"] if section else frame["section"],
        fx_name=presets.get_preset("fx", fx_id(frame))["name"],
        move_name=motion.MOVE_NAMES[motion.resolve_move(frame.get("camera_move"))],
        move_explicit=motion.is_valid_move(frame.get("camera_move")),
        default_move_name=motion.MOVE_NAMES[motion.DEFAULT_MOVE],
        moves=motion.MOVES,
        state=state,
        error=error,
        duration=clip_settings.DURATION,
    ), status


@bp.route("/storyboards/<storyboard_id>/frames/<frame_id>/animate", methods=["GET", "POST"])
def animate_frame(storyboard_id, frame_id):
    board = _get_board_or_404(storyboard_id)
    _frame_or_404(board, frame_id)
    if request.method == "GET":
        return _render_animate(storyboard_id, frame_id)
    move = request.form.get("camera_move", "")  # empty = keep the frame's current move
    if move and not motion.is_valid_move(move):
        return _render_animate(storyboard_id, frame_id, "Unknown camera move option.", 400)
    try:
        clips.animate_frame(_data_dir(), storyboard_id, frame_id,
                            get_encoder(current_app.config), move or None)
    except Exception as exc:
        message, status = _clip_failure(exc)
        return _render_animate(storyboard_id, frame_id, message, status)
    return redirect(url_for("main.animate_frame", storyboard_id=storyboard_id, frame_id=frame_id))


@bp.post("/storyboards/<storyboard_id>/frames/<frame_id>/move")
def set_move(storyboard_id, frame_id):
    board = _get_board_or_404(storyboard_id)
    _frame_or_404(board, frame_id)
    move = request.form.get("camera_move", "")
    if not motion.is_valid_move(move):
        return _render_animate(storyboard_id, frame_id, "Pick a camera move from the list.", 400)
    storage.set_camera_move(_data_dir(), storyboard_id, frame_id, move)
    return redirect(url_for("main.animate_frame", storyboard_id=storyboard_id, frame_id=frame_id))


@bp.get("/storyboards/<storyboard_id>/frames/<frame_id>/animate/clip")
def frame_clip(storyboard_id, frame_id):
    board = _get_board_or_404(storyboard_id)
    frame = _frame_or_404(board, frame_id)
    state, path = clips.frame_state(_data_dir(), storyboard_id, frame)
    if state != "fresh":
        abort(404)  # never serve a clip that no longer matches the frame
    return send_file(path, mimetype=clip_settings.MIMETYPE, conditional=True)


def _render_play(board, error=None, status=200):
    state = clips.tape_state(_data_dir(), board["id"], board)[0]
    count = len(board["frames"])
    seconds = count * clip_settings.DURATION + max(0, count - 1) * (
        clip_settings.TRANSITION_FRAMES / clip_settings.FPS)
    return render_template("play.html", board=board, state=state, count=count,
                           seconds=round(seconds, 1), error=error), status


@bp.route("/storyboards/<storyboard_id>/play", methods=["GET", "POST"])
def play_tape(storyboard_id):
    board = _get_board_or_404(storyboard_id)
    if request.method == "GET":
        return _render_play(board)
    try:
        clips.export_tape(_data_dir(), storyboard_id, get_encoder(current_app.config))
    except Exception as exc:
        message, status = _clip_failure(exc)
        return _render_play(board, message, status)
    return redirect(url_for("main.play_tape", storyboard_id=storyboard_id))


@bp.get("/storyboards/<storyboard_id>/play/clip")
def tape_clip(storyboard_id):
    board = _get_board_or_404(storyboard_id)
    state, path = clips.tape_state(_data_dir(), storyboard_id, board)
    if state != "fresh":
        abort(404)
    return send_file(path, mimetype=clip_settings.MIMETYPE, conditional=True)
