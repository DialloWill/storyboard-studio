"""Preset data for sections, cameras, shots and lighting.

Plain data only. Every preset has an id, a display name and a prompt fragment.
The first entry in CAMERAS and LIGHTING is the default; SECTIONS order is the
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

SHOTS = [
    {"id": "close-up", "name": "Close-Up",
     "fragment": "tight close-up framing on the face, shallow focus, eyes in sharp detail, "
                 "background melting into soft bokeh"},
    {"id": "wide-shot", "name": "Wide Shot",
     "fragment": "wide establishing shot, subject small within a vast environment, "
                 "strong leading lines and deep layered space"},
    {"id": "low-angle", "name": "Low Angle",
     "fragment": "low angle shot looking up from near the ground, subject towering and heroic, "
                 "dramatic perspective against the sky or ceiling"},
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

GROUPS = {
    "section": SECTIONS,
    "camera": CAMERAS,
    "shot": SHOTS,
    "lighting": LIGHTING,
}

DEFAULT_SECTION = SECTIONS[0]["id"]
DEFAULT_CAMERA = CAMERAS[0]["id"]
DEFAULT_SHOT = SHOTS[0]["id"]
DEFAULT_LIGHTING = LIGHTING[0]["id"]

SECTION_ORDER = [s["id"] for s in SECTIONS]


def get_preset(group, preset_id):
    """Return the preset dict for an id within a group, or None if unknown."""
    for preset in GROUPS[group]:
        if preset["id"] == preset_id:
            return preset
    return None
