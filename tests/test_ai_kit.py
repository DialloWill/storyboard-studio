import ast
import io
import json
import re
import zipfile

from ai_helpers import encoder, frame_ids, normalizer  # noqa: F401
from fake_encoder import add_frame, app  # noqa: F401

from app import ai_kit, storage
from app.ai_kit import CAMERA_LINE, build_motion_prompt


# ---- build_motion_prompt ------------------------------------------------------------

def test_prompt_structure_and_camera_line_last():
    p = build_motion_prompt("A singer under a streetlight", "neon")
    assert p.startswith("A singer under a streetlight.")
    assert "The subject stays in place." in p
    assert "Neon lights flicker softly." in p
    assert p.endswith(CAMERA_LINE)


def test_prompt_word_cap_trims_scene_never_camera_line():
    long_scene = " ".join(f"word{i}" for i in range(300))
    p = build_motion_prompt(long_scene, "golden-hour")
    assert len(p.split()) <= 90
    assert p.endswith(CAMERA_LINE)
    assert "word0" in p and "word299" not in p
    assert "Warm light shifts gently." in p


def test_prompt_is_deterministic():
    assert build_motion_prompt("a b c", "noir") == build_motion_prompt("a b c", "noir")


def test_prompt_lighting_cues():
    for light, cue in [("neon", "neon lights flicker"), ("golden-hour", "warm light shifts gently"),
                       ("glitch", "light flickers"), ("cyberpunk-wave", "light flickers")]:
        assert cue in build_motion_prompt("x", light).lower()


def test_prompt_unknown_lighting_and_empty_scene():
    p = build_motion_prompt("", "no-such-light")
    assert p == f"The subject stays in place. Light shifts subtly. {CAMERA_LINE}"


def test_prompt_adds_no_gendered_pronouns():
    for light in ["neon", "golden-hour", "glitch", "cyberpunk-wave", "noir", "x"]:
        text = build_motion_prompt("", light).lower()
        assert not re.search(r"\b(he|she|his|her|him|hers)\b", text)


def test_seed_is_stable_and_in_range():
    fid = "0123456789abcdef0123456789abcdef"
    assert ai_kit.seed_for(fid) == ai_kit.seed_for(fid)
    assert 0 <= ai_kit.seed_for(fid) < 2 ** 31


def test_slug_is_safe_ascii_with_fallback():
    assert ai_kit.slugify_title("FlowState: Ronin 96!", "ID") == "flowstate-ronin-96"
    assert ai_kit.slugify_title("../../etc\r\nX", "ID") == "etc-x"
    assert ai_kit.slugify_title("???", "abc123") == "abc123"
    assert ai_kit.slugify_title("Café", "ID") == "cafe"
    assert len(ai_kit.slugify_title("a" * 200, "ID")) <= 40


# ---- the kit download ---------------------------------------------------------------

def _kit(client, board_id):
    resp = client.get(f"/storyboards/{board_id}/ai-kit.zip")
    assert resp.status_code == 200
    return resp, zipfile.ZipFile(io.BytesIO(resp.data))


def test_kit_zip_contents_and_manifest(client, data_dir, board_id):
    a = add_frame(client, board_id, section="outro", scene="Last scene", lighting="golden-hour")
    b = add_frame(client, board_id, section="intro", scene="First scene", lighting="neon")
    resp, zf = _kit(client, board_id)
    assert resp.mimetype == "application/zip"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert re.search(r'filename="?[A-Za-z0-9._-]+-ai-kit\.zip', resp.headers["Content-Disposition"])
    names = set(zf.namelist())
    assert names == {f"frames/{a}.png", f"frames/{b}.png", "manifest.json",
                     "storyboard_ai_kit.ipynb", "README.txt"}
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["schema_version"] == 1
    assert manifest["tape_id"] == board_id
    assert manifest["tape_title"]
    assert manifest["created"]
    assert manifest["negative_prompt"] == ai_kit.NEGATIVE_PROMPT
    s = manifest["settings"]
    assert (s["width"], s["height"], s["num_frames"], s["num_inference_steps"], s["fps"]) == (640, 352, 33, 30, 24)
    assert s["revision"] == "8984fa25007f376c1a299016d0957a37a2f797bb" and s["dtype"] == "float16"
    # sorted_frames order: intro before outro, regardless of creation order
    assert [f["frame_id"] for f in manifest["frames"]] == [b, a]
    first = manifest["frames"][0]
    assert set(first) == {"frame_id", "order", "section", "channel", "scene", "prompt", "presets",
                          "camera_move", "seed", "motion_prompt"}
    assert first["order"] == 0 and manifest["frames"][1]["order"] == 1
    assert first["scene"] == "First scene" and first["presets"]["lighting"] == "neon"
    assert first["seed"] == ai_kit.seed_for(b)
    assert first["motion_prompt"] == build_motion_prompt("First scene", "neon")


def test_kit_pngs_are_the_stored_bytes(client, data_dir, board_id):
    fid = add_frame(client, board_id)
    board = storage.load_storyboard(data_dir, board_id)
    stored = (data_dir / board_id / board["frames"][0]["filename"]).read_bytes()
    _, zf = _kit(client, board_id)
    assert zf.read(f"frames/{fid}.png") == stored


def test_kit_is_deterministic_apart_from_timestamp(client, board_id):
    add_frame(client, board_id)
    m1 = json.loads(_kit(client, board_id)[1].read("manifest.json"))
    m2 = json.loads(_kit(client, board_id)[1].read("manifest.json"))
    m1.pop("created"), m2.pop("created")
    assert m1 == m2


def _notebook_text(zf):
    nb = json.loads(zf.read("storyboard_ai_kit.ipynb"))
    return nb, "\n".join("".join(c["source"]) for c in nb["cells"])


def test_notebook_is_valid_nbformat4_with_proven_settings(client, board_id):
    add_frame(client, board_id)
    nb, text = _notebook_text(_kit(client, board_id)[1])
    assert nb["nbformat"] == 4 and isinstance(nb["cells"], list) and nb["cells"]
    for cell in nb["cells"]:
        assert cell["cell_type"] in ("markdown", "code")
        assert isinstance(cell["source"], list)
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            ast.parse("".join(cell["source"]))  # every code cell is valid Python
    assert "8984fa25007f376c1a299016d0957a37a2f797bb" in text
    assert "torch.float16" in text
    assert "bfloat16" not in text.lower()
    assert "NUM_FRAMES = 33" in text and "num_frames=NUM_FRAMES" in text
    assert "enable_model_cpu_offload(gpu_id=0)" in text and "enable_tiling()" in text
    assert "/tmp/hf" in text and "HF_HUB_DISABLE_TELEMETRY" in text
    assert "Image.LANCZOS" in text and 'device="cpu"' in text
    for name in ("ONLY_FRAMES", "PROMPT_OVERRIDES", "SEED_OVERRIDES"):
        assert name in text
    assert "pip install" not in text and "hf_token" not in text.lower() and "login(" not in text
    assert "/kaggle/working/ai_clips.zip" in text
    assert "manifest_path.parent" in text  # frames are found next to the manifest


def test_notebook_handles_a_zip_dataset_safely(client, board_id):
    add_frame(client, board_id)
    _, text = _notebook_text(_kit(client, board_id)[1])
    assert "/tmp/kit" in text and "S_ISLNK" in text and '".." in parts' in text
    assert "frames/[0-9a-f]{32}" in text


def test_notebook_and_readme_tell_user_to_check_prompts(client, board_id):
    add_frame(client, board_id)
    _, zf = _kit(client, board_id)
    _, nb = _notebook_text(zf)
    readme = zf.read("README.txt").decode()
    for text in (nb, readme):
        assert "motion_prompt" in text and "PROMPT_OVERRIDES" in text
        assert "uncorks" in text and "leaps" in text
    assert "walk toward" in readme


def test_readme_has_steps_limits_and_license(client, board_id):
    add_frame(client, board_id)
    readme = _kit(client, board_id)[1].read("README.txt").decode()
    for needle in ("Private", "GPU T4 x2", "Internet", "Run All", "ai_clips.zip",
                   "Stop the session", "90 words", "Big action", "LTX-Video Open Weights License",
                   "does not distribute any weights"):
        assert needle in readme


def test_kit_for_empty_tape_and_bad_id(client, board_id):
    assert client.get(f"/storyboards/{board_id}/ai-kit.zip").status_code == 400
    for bad in ["nothex", "0" * 32, ("a" * 32) + "\n"]:
        assert client.get(f"/storyboards/{bad}/ai-kit.zip").status_code == 404


def test_kit_refuses_when_a_frame_image_is_missing(client, data_dir, board_id):
    add_frame(client, board_id)
    board = storage.load_storyboard(data_dir, board_id)
    (data_dir / board_id / board["frames"][0]["filename"]).unlink()
    assert client.get(f"/storyboards/{board_id}/ai-kit.zip").status_code == 409
