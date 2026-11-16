"""
Draws weekly_banner.png: the thin banner (1300 x 100) above the weekly top three.

    pip install pillow
    python3 make_weekly_banner.py [output.png]

Upload the PNG somewhere public over https and give its link to the leaderboard step as
`weekly_image_url`. Left unset, the weekly board gets a text heading instead.
Drawn at four times the size and scaled down, so the edges are smooth. Fonts are macOS's.
"""

import math
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, S = 1300, 100, 4                     # final size, and the drawing scale
AVENIR_NEXT = "/System/Library/Fonts/Avenir Next.ttc"
SCRIPT = "/System/Library/Fonts/Supplemental/SnellRoundhand.ttc"
HEAVY, MEDIUM = 8, 5                       # faces inside the .ttc

INK = (28, 44, 33)
MUTED = (96, 120, 102)
GREEN = (47, 125, 58)
GREEN_SOFT = (214, 233, 205)
BORDER = (205, 224, 196)


def font(path, size, index=0):
    return ImageFont.truetype(path, int(size * S), index=index)


def gradient():
    """Pale green on the left easing to cream on the right, like the Steps banner."""
    left, right = (226, 241, 219), (250, 246, 228)
    image = Image.new("RGB", (W * S, H * S))
    pixels = ImageDraw.Draw(image)
    for x in range(W * S):
        t = x / (W * S - 1)
        pixels.line([(x, 0), (x, H * S)], fill=tuple(int(a + (b - a) * t) for a, b in zip(left, right)))
    return image.convert("RGBA")


def circle(draw, cx, cy, r, fill, outline=None, width=0):
    draw.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill,
                 outline=outline, width=int(width * S))


def poly(draw, points, fill):
    draw.polygon([(x * S, y * S) for x, y in points], fill=fill)


def leaf(draw, x, y, length, angle, fill):
    """A pointed leaf from (x, y), `length` long, turned `angle` degrees from straight up."""
    a = math.radians(angle)
    ux, uy = math.sin(a), -math.cos(a)                 # along the leaf
    px, py = -uy, ux                                   # across it
    points = []
    for i in range(0, 21):
        t = i / 20
        half = math.sin(math.pi * t) * length * 0.28
        points.append((x + ux * length * t + px * half, y + uy * length * t + py * half))
    for i in range(20, -1, -1):
        t = i / 20
        half = math.sin(math.pi * t) * length * 0.28
        points.append((x + ux * length * t - px * half, y + uy * length * t - py * half))
    poly(draw, points, fill)


def podium_icon(draw, cx, cy):
    """Three steps, the tallest in the middle, and a star over it."""
    circle(draw, cx, cy, 36, GREEN_SOFT)
    base = cy + 17
    for x0, height in ((cx - 21, 15), (cx - 7, 26), (cx + 7, 10)):
        draw.rounded_rectangle([x0 * S, (base - height) * S, (x0 + 14) * S, base * S], radius=2 * S, fill=GREEN)
    star = []
    for i in range(10):
        r = 7 if i % 2 == 0 else 3
        a = math.radians(-90 + i * 36)
        star.append((cx + math.cos(a) * r, cy - 24 + math.sin(a) * r))
    poly(draw, star, (240, 183, 38))


def medal(draw, cx, cy, r, rim, face, number, ribbon):
    left_tail = [(cx - r * 0.55, cy - r * 1.55), (cx - r * 0.05, cy - r * 1.55), (cx + r * 0.15, cy - r * 0.2),
                 (cx - r * 0.45, cy - r * 0.2)]
    right_tail = [(cx + r * 0.05, cy - r * 1.55), (cx + r * 0.55, cy - r * 1.55), (cx + r * 0.45, cy - r * 0.2),
                  (cx - r * 0.15, cy - r * 0.2)]
    poly(draw, left_tail, ribbon[0])
    poly(draw, right_tail, ribbon[1])
    circle(draw, cx, cy, r, rim)
    circle(draw, cx, cy, r * 0.8, face)
    circle(draw, cx, cy, r * 0.8, None, (255, 255, 255, 150), 1.2)
    size = r * 1.05
    f = font(AVENIR_NEXT, size, HEAVY)
    draw.text((cx * S, (cy + r * 0.03) * S), str(number), font=f, fill=rim, anchor="mm")


def main(path):
    image = gradient()
    draw = ImageDraw.Draw(image, "RGBA")

    # a low sun behind the medals, and leaves at the corners
    circle(draw, 1180, 62, 48, (252, 226, 150, 150))
    for x, y, length, angle, fill in ((20, 112, 46, 12, (150, 195, 130, 190)), (40, 112, 38, 38, (120, 176, 108, 190)),
                                      (1285, 112, 44, -14, (150, 195, 130, 190)), (1262, 112, 34, -40, (120, 176, 108, 190))):
        leaf(draw, x, y, length, angle, fill)

    podium_icon(draw, 62, 50)

    draw.text((118 * S, 41 * S), "Weekly Leaders", font=font(AVENIR_NEXT, 38, HEAVY), fill=INK, anchor="ls")
    draw.text((119 * S, 66 * S), "Who added the most in the last seven days", font=font(AVENIR_NEXT, 17, MEDIUM),
              fill=MUTED, anchor="ls")
    draw.rounded_rectangle([119 * S, 77 * S, 163 * S, 80 * S], radius=2 * S, fill=GREEN)

    draw.text((760 * S, 62 * S), "Keep moving, keep climbing", font=font(SCRIPT, 30), fill=(70, 120, 80), anchor="ls")

    # silver, gold, bronze: the gold one in the middle and a little larger
    ribbons = (((214, 69, 65), (62, 99, 190)),) * 3
    medal(draw, 1118, 62, 20, (140, 146, 156), (206, 212, 222), 2, ribbons[0])
    medal(draw, 1180, 58, 25, (196, 140, 20), (247, 205, 70), 1, ribbons[1])
    medal(draw, 1242, 62, 20, (140, 84, 40), (212, 148, 92), 3, ribbons[2])

    # a few specks of confetti
    for x, y, r, color in ((1088, 30, 2.2, (240, 183, 38, 220)), (1150, 22, 2, (214, 69, 65, 200)),
                           (1216, 26, 2.4, (62, 99, 190, 190)), (1272, 40, 2, (47, 125, 58, 200)),
                           (1098, 84, 2, (62, 99, 190, 170)), (1214, 88, 2.2, (240, 183, 38, 220))):
        circle(draw, x, y, r, color)

    draw.rectangle([0, 0, W * S - 1, H * S - 1], outline=BORDER + (255,), width=2 * S)
    image.convert("RGB").resize((W, H), Image.LANCZOS).save(path, optimize=True)
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "weekly_banner.png")
