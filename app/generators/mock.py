"""Mock generator: a 1280x720 camcorder "no signal" test card. No network."""

import io

from PIL import Image, ImageDraw, ImageFont

from .base import ImageGenerator

WIDTH, HEIGHT = 1280, 720
BARS_HEIGHT = HEIGHT * 2 // 3

# SMPTE-style bars: white, yellow, cyan, green, magenta, red, blue
BARS = [
    (192, 192, 192),
    (192, 192, 0),
    (0, 192, 192),
    (0, 192, 0),
    (192, 0, 192),
    (192, 0, 0),
    (0, 0, 192),
]
PROMPT_CHARS = 120


class MockGenerator(ImageGenerator):
    def generate(self, prompt: str) -> bytes:
        image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        edges = [round(i * WIDTH / len(BARS)) for i in range(len(BARS) + 1)]
        for color, left, right in zip(BARS, edges, edges[1:]):
            draw.rectangle([left, 0, right - 1, BARS_HEIGHT - 1], fill=color)

        title_font = ImageFont.load_default(size=40)
        body_font = ImageFont.load_default(size=22)
        draw.text((60, BARS_HEIGHT + 30), "NO SIGNAL — MOCK FRAME",
                  fill=(255, 255, 255), font=title_font)

        snippet = " ".join(prompt.split())[:PROMPT_CHARS]
        if len(prompt) > PROMPT_CHARS:
            snippet = snippet.rstrip() + "..."
        # Wrap by measured width so long unbroken words can't run off the card.
        lines, line = [], ""
        for word in snippet.split(" "):
            trial = f"{line} {word}".strip()
            if line and draw.textlength(trial, font=body_font) > WIDTH - 120:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
        draw.multiline_text((60, BARS_HEIGHT + 95), "\n".join(lines),
                            fill=(255, 255, 255), font=body_font, spacing=8)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
