#!/usr/bin/env python3
"""Generate original abstract film-and-wave icons for the plugin listing."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "plugins" / "mad-production-toolkit" / "assets"


def make_icon(size: int, *, rounded: bool) -> Image.Image:
    scale = 4
    s = size * scale
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill="#17222B")
    else:
        draw.ellipse((0, 0, s - 1, s - 1), fill="#17222B")

    # Film strip and a distinct waveform are drawn as simple original geometry.
    x0, y0, x1, y1 = (s * 0.17, s * 0.25, s * 0.83, s * 0.75)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=s * 0.055,
                           outline="#EAF1ED", width=s // 38)
    for x in (0.24, 0.76):
        for y in (0.33, 0.5, 0.67):
            cx, cy = int(s * x), int(s * y)
            r = s * 0.015
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill="#EAF1ED")
    heights = [0.10, 0.20, 0.34, 0.17, 0.28, 0.13, 0.08]
    for index, height in enumerate(heights):
        x = int(s * (0.34 + index * 0.054))
        draw.rounded_rectangle((x, s * (0.5 - height / 2),
                                x + s * 0.025, s * (0.5 + height / 2)),
                               radius=s * 0.012, fill="#9FE4C8")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_icon(256, rounded=True).save(ASSETS / "icon.png")
    make_icon(512, rounded=False).save(ASSETS / "logo.png")


if __name__ == "__main__":
    main()
