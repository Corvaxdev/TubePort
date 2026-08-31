# SPDX-License-Identifier: MIT
# Copyright (c) 2026 nanomicron

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SCALE = 4


def scaled(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [(x * SCALE, y * SCALE) for x, y in points]


def main() -> None:
    size = 512 * SCALE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Layered rounded rectangles approximate the dark diagonal gradient without
    # introducing a runtime SVG dependency.
    draw.rounded_rectangle((16 * SCALE, 16 * SCALE, 496 * SCALE, 496 * SCALE), radius=116 * SCALE, fill="#0A1022")
    draw.rounded_rectangle((25 * SCALE, 25 * SCALE, 470 * SCALE, 470 * SCALE), radius=106 * SCALE, fill="#111B31")
    draw.rounded_rectangle((35 * SCALE, 35 * SCALE, 438 * SCALE, 438 * SCALE), radius=96 * SCALE, fill="#182744")

    portal_box = (112 * SCALE, 106 * SCALE, 400 * SCALE, 394 * SCALE)
    draw.arc(portal_box, start=198, end=342, fill="#F05278", width=42 * SCALE)
    draw.arc(portal_box, start=18, end=162, fill="#FF7A70", width=42 * SCALE)

    draw.line(scaled([(256, 128), (256, 316)]), fill="#FFFFFF", width=42 * SCALE)
    draw.line(scaled([(186, 260), (256, 332), (326, 260)]), fill="#FFFFFF", width=42 * SCALE, joint="curve")
    draw.arc((142 * SCALE, 326 * SCALE, 370 * SCALE, 442 * SCALE), start=28, end=152, fill="#62D5C6", width=34 * SCALE)

    image = image.resize((512, 512), Image.Resampling.LANCZOS)
    png_path = ASSETS / "tubeport.png"
    ico_path = ASSETS / "tubeport.ico"
    image.save(png_path, optimize=True)
    image.save(ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Created {png_path}")
    print(f"Created {ico_path}")


if __name__ == "__main__":
    main()
