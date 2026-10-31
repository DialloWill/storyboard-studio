"""Preset data for sections, cameras, shots, lighting and direction.

Plain data only. Every preset has an id, a display name and a prompt fragment.
The first entry in CAMERAS, LIGHTING and DIRECTIONS is the default (shots have
an explicit DEFAULT_SHOT); SECTIONS order is the
fixed storyboard order.
"""

SECTIONS = [
    {"id": "intro", "name": "Intro",
     "fragment": "opening moment of a music video, establishing mood, slow build of anticipation"},
    {"id": "verse", "name": "Verse",
     "fragment": "verse of a song, narrative storytelling moment, intimate and observational"},
    {"id": "hook", "name": "Hook",
     "fragment": "the hook of the song, peak energy, the most iconic and memorable image of the video"},
    {"id": "bridge", "name": "Bridge",
     "fragment": "bridge of the song, a shift in tone, surreal and emotionally turning point"},
    {"id": "outro", "name": "Outro",
     "fragment": "closing moment of a music video, fading energy, lingering final image"},
]

CAMERAS = [
    {"id": "vhs-camcorder", "name": "VHS Camcorder",
     "fragment": "shot on a VHS camcorder, analog tape grain, horizontal scan lines, chromatic color bleed, "
                 "soft smeared highlights, tracking noise at the edges"},
    {"id": "16mm-film", "name": "16mm Film",
     "fragment": "shot on 16mm film, visible organic grain, gentle halation around highlights, "
                 "slightly faded blacks, warm imperfect color, subtle gate weave"},
    {"id": "digital-cinema", "name": "Digital Cinema",
     "fragment": "shot on a digital cinema camera, crisp clean detail, wide dynamic range, "
                 "shallow depth of field, anamorphic lens flares, polished color grade"},
]

SHOT_CATEGORIES = ("Framing", "Angle", "Perspective")

# Listed in form display order (grouped by category). Ids are what get stored,
# so the order here never affects existing frames. DEFAULT_SHOT is explicit.
SHOTS = [
    {"id": "extreme-close-up", "name": "Extreme Close-Up", "category": "Framing",
     "fragment": "extreme close-up filling the frame with a single detail such as the eyes or lips, "
                 "razor-thin focus, skin texture and individual lashes visible"},
    {"id": "close-up", "name": "Close-Up", "category": "Framing",
     "fragment": "tight close-up framing on the face, shallow focus, eyes in sharp detail, "
                 "background melting into soft bokeh"},
    {"id": "medium-shot", "name": "Medium Shot", "category": "Framing",
     "fragment": "medium shot framed from the waist up, posture and gestures clear, "
                 "background softly out of focus"},
    {"id": "wide-shot", "name": "Wide Shot", "category": "Framing",
     "fragment": "wide establishing shot, subject small within a vast environment, "
                 "strong leading lines and deep layered space"},
    {"id": "eye-level", "name": "Eye Level", "category": "Angle",
     "fragment": "eye level shot with the camera at the subject's height, flat neutral horizon, "
                 "direct natural perspective"},
    {"id": "high-angle", "name": "High Angle", "category": "Angle",
     "fragment": "high angle shot looking down on the subject from above, subject appearing small "
                 "and vulnerable, floor or ground filling the frame"},
    {"id": "low-angle", "name": "Low Angle", "category": "Angle",
     "fragment": "low angle shot looking up from near the ground, subject towering and heroic, "
                 "dramatic perspective against the sky or ceiling"},
    {"id": "birds-eye", "name": "Bird's-Eye", "category": "Angle",
     "fragment": "bird's-eye top-down view looking straight down at the scene from directly overhead, "
                 "subject seen from above, graphic patterns on the ground"},
    {"id": "dutch-angle", "name": "Dutch Angle", "category": "Angle",
     "fragment": "dutch angle with the camera tilted so the horizon runs diagonally, "
                 "skewed lines creating unease and disorientation"},
    {"id": "over-the-shoulder", "name": "Over-the-Shoulder", "category": "Perspective",
     "fragment": "over-the-shoulder shot, the back of a head and shoulder as a soft out-of-focus "
                 "foreground element, subject sharp in the distance"},
    {"id": "pov", "name": "POV", "category": "Perspective",
     "fragment": "first-person point-of-view shot through the character's own eyes, hands visible "
                 "at the edge of the frame, no character facing the lens"},
]

LIGHTING = [
    {"id": "neon", "name": "Neon",
     "fragment": "saturated neon tube lighting in magenta and cyan, glowing reflections on wet surfaces, "
                 "deep shadows, night-time city glow"},
    {"id": "glitch", "name": "Glitch",
     "fragment": "datamosh artifacts, RGB channel split, digital corruption, torn scan blocks, "
                 "flickering unstable light, pixel smearing"},
    {"id": "cyberpunk-wave", "name": "Cyberpunk Wave",
     "fragment": "synthwave cyberpunk lighting, purple and teal gradient haze, glowing horizon grid, "
                 "volumetric fog lit from behind, retro-futuristic atmosphere"},
    {"id": "golden-hour", "name": "Golden Hour",
     "fragment": "golden hour sunlight, long warm shadows, glowing rim light on hair and shoulders, "
                 "soft amber haze, nostalgic mood"},
    {"id": "noir", "name": "Noir",
     "fragment": "high-contrast black and white noir lighting, hard shadows cut by window blinds, "
                 "a single key light, drifting cigarette-smoke haze"},
]

DIRECTIONS = [
    {"id": "none", "name": "None", "fragment": ""},
    {"id": "monumental", "name": "Monumental",
     "fragment": "subject centered dead-center, extreme wide scale, brutalist architecture, "
                 "far-side key light leaving most of the face in shadow, deep staging with "
                 "foreground, midground and background, cool desaturated large-format film texture"},
    {"id": "one-point-symmetry", "name": "One-Point Symmetry",
     "fragment": "one-point perspective, perfectly symmetrical composition, subject centered at the "
                 "vanishing point, wide-angle lens, cold controlled lighting, eerie stillness"},
    {"id": "warm-intimate", "name": "Warm Intimate",
     "fragment": "rich, carefully lit skin tones, warm motivated practical light from lamps and windows, "
                 "intimate close framing, saturated color, lived-in environment, emotional realism"},
]

GROUPS = {
    "section": SECTIONS,
    "camera": CAMERAS,
    "shot": SHOTS,
    "lighting": LIGHTING,
    "direction": DIRECTIONS,
}

DEFAULT_SECTION = SECTIONS[0]["id"]
DEFAULT_CAMERA = CAMERAS[0]["id"]
DEFAULT_SHOT = "close-up"
DEFAULT_LIGHTING = LIGHTING[0]["id"]
DEFAULT_DIRECTION = "none"

SECTION_ORDER = [s["id"] for s in SECTIONS]


def get_preset(group, preset_id):
    """Return the preset dict for an id within a group, or None if unknown."""
    for preset in GROUPS[group]:
        if preset["id"] == preset_id:
            return preset
    return None
