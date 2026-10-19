#!/usr/bin/env python3
"""
Generate the browser-tab icon.

    python3 make_favicon.py

Draws a small mark rather than using an emoji: a descending line over a
baseline, which is what credit deterioration looks like on every chart in this
project. Rendered at 4x and downsampled so the diagonal stays smooth at 32px.

Re-run only if the colours change. The output is committed, so the app does not
depend on Pillow at runtime.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

SIZE = 256          # drawn large, downsampled at the end
SCALE = 4
STEEL = (42, 93, 143)      # --steel, the project's accent
PAPER = (247, 248, 250)    # --paper
ELEVATED = (166, 42, 34)   # --elevated, the "stressed" band colour
OUT = "assets/favicon.png"


def main() -> None:
    s = SIZE * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded square in the accent colour.
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=STEEL)

    pad = int(s * 0.22)
    w = int(s * 0.055)

    # Baseline: the axis the line falls away from.
    d.line([(pad, s - pad), (s - pad, s - pad)],
           fill=PAPER + (90,), width=max(w // 2, 1))

    # The descending line itself -- high on the left, low on the right.
    pts = [(pad, pad + int(s * 0.06)),
           (pad + int(s * 0.18), pad + int(s * 0.20)),
           (pad + int(s * 0.34), pad + int(s * 0.14)),
           (s - pad, s - pad - int(s * 0.07))]
    d.line(pts, fill=PAPER, width=w, joint="curve")

    # End point marked in the stress colour: where the trend is heading.
    r = int(s * 0.055)
    x, y = pts[-1]
    d.ellipse([x - r, y - r, x + r, y + r], fill=ELEVATED)

    img.resize((SIZE, SIZE), Image.LANCZOS).save(OUT)
    print(f"Wrote {OUT} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
