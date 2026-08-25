from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


_PALETTE = [
    (30, 30, 120), (120, 30, 30), (20, 90, 60), (90, 60, 20), (60, 20, 90),
]


def render_text_slide(
    text: str, output_path: Path, *, index: int = 0, resolution: str = "1280x720",
) -> Path:
    """Fallback slide renderer: no external API, always available offline.
    Real image generation (mcp__image_generate / FAL) is the preferred
    path for anything the caller wants to look production-quality — this
    exists so a scene ALWAYS has a real image, never a missing one, when
    no generated image was supplied."""
    width, height = (int(part) for part in resolution.split("x"))
    color = _PALETTE[index % len(_PALETTE)]
    image = Image.new("RGB", (width, height), color=color)
    draw = ImageDraw.Draw(image)
    font_size = max(int(height * 0.08), 24)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    wrapped = _wrap_text(text, draw, font, max_width=int(width * 0.85))
    line_height = font_size + 12
    total_height = line_height * len(wrapped)
    start_y = (height - total_height) / 2
    for line_index, line in enumerate(wrapped):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        draw.text(((width - line_width) / 2, start_y + line_index * line_height), line, fill="white", font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _wrap_text(text: str, draw, font, *, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]
