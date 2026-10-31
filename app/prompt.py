"""Prompt builder. Pure function: no Flask, no I/O."""

from .presets import get_preset


def build_prompt(scene, section, camera, shot, lighting, direction="none"):
    """Combine the scene text with the preset fragments into one image prompt.

    section, camera, shot, lighting and direction are preset ids. An empty
    fragment (direction "none") adds nothing. Unknown ids raise
    ValueError so a bad id can never silently produce a weaker prompt.
    """
    # Trailing punctuation would produce ".," when joined with the fragments.
    parts = [scene.strip().rstrip(".,;:!? \t\r\n")]
    for group, preset_id in (
        ("section", section),
        ("shot", shot),
        ("camera", camera),
        ("lighting", lighting),
        ("direction", direction),
    ):
        preset = get_preset(group, preset_id)
        if preset is None:
            raise ValueError(f"Unknown {group} preset: {preset_id!r}")
        parts.append(preset["fragment"])
    parts.append("cinematic 16:9 music video still frame")
    return ", ".join(p for p in parts if p)
