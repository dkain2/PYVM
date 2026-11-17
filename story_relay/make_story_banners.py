"""
Draws the Story Relay banners, one for each kind of post, in two heights (both 1300 wide):

    pip install pillow
    python3 make_story_banners.py [output folder] [--sizes 80,200]    (default: a banners folder beside this file,
                                                                       both sizes; --sizes 200 draws only the tall set)

        story_new.png     the Sunday post: "A new story starts Monday"                       1300 x 80
        story_daily.png   Monday to Thursday, above each chapter: "Today's chapter is below"
        story_final.png   Friday, above the story the team built

        story_new_200.png, story_daily_200.png, story_final_200.png      the same three, 1300 x 200: the same colours,
                          icon, words and pictures with more room, so everything is larger and the script line sits
                          under the subtitle.

Upload each PNG to Slack (or anywhere public over https) and give the step its link, or the Slack file id
(F...), as the recipe input of the same kind of post: `banner_announce`, `banner_daily`, `banner_final`.
(`banner` alone puts one banner on every post.)

Drawn at four times the size and scaled down, so the edges are smooth. Fonts are macOS's, as in the
leaderboard's make_weekly_banner.py, whose look these follow.
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, S = 1300, 80, 4                      # final size, and the drawing scale
AVENIR_NEXT = "/System/Library/Fonts/Avenir Next.ttc"
SCRIPT = "/System/Library/Fonts/Supplemental/SnellRoundhand.ttc"
HEAVY, MEDIUM = 8, 5                       # faces inside the .ttc

INK = (40, 30, 74)
MUTED = (104, 96, 140)
PURPLE = (96, 76, 190)
PURPLE_SOFT = (222, 216, 248)
AMBER = (240, 183, 38)
CORAL = (226, 100, 90)
PAPER = (255, 255, 255)
LINE = (196, 190, 226)
BORDER = (214, 208, 238)


def font(path, size, index=0):
    return ImageFont.truetype(path, int(size * S), index=index)


def gradient():
    """Pale lavender on the left easing to warm cream on the right."""
    left, right = (236, 232, 251), (253, 245, 231)
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


def sparkle(draw, x, y, r, fill):
    """A four-pointed twinkle."""
    k = 0.26
    poly(draw, [(x, y - r), (x + r * k, y - r * k), (x + r, y), (x + r * k, y + r * k), (x, y + r),
                (x - r * k, y + r * k), (x - r, y), (x - r * k, y - r * k)], fill)


def star(draw, cx, cy, outer, inner, fill):
    points = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = math.radians(-90 + i * 36)
        points.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    poly(draw, points, fill)


def curve(draw, p0, p1, p2, p3, color, width):
    """A cubic curve drawn as a smooth line."""
    points = []
    for i in range(41):
        t = i / 40
        u = 1 - t
        points.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                       u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    draw.line([(x * S, y * S) for x, y in points], fill=color, width=int(width * S), joint="curve")
    for x, y in (points[0], points[-1]):
        circle(draw, x, y, width / 2, color)


def open_book(draw, cx, cy, k=1.0):
    """An open book seen from the front: two pages with lines of text on a purple cover."""
    def pts(*coords):
        return [(cx + x * k, cy + y * k) for x, y in coords]
    poly(draw, pts((-32, -11), (32, -11), (32, 15), (0, 20), (-32, 15)), PURPLE)
    poly(draw, pts((-28, -14), (-2, -9), (-2, 15), (-28, 10)), PAPER)
    poly(draw, pts((2, -9), (28, -14), (28, 10), (2, 15)), PAPER)
    slope = 5 / 26                                  # the pages tilt toward the spine, so their lines do too
    for i in range(4):
        depth = 6 + i * 4.6
        for (x0, x1), top in (((-24, -6), lambda x: -14 + (x + 28) * slope),
                              ((6, 24), lambda x: -9 - (x - 2) * slope)):
            draw.line([((cx + x0 * k) * S, (cy + (top(x0) + depth) * k) * S),
                       ((cx + x1 * k) * S, (cy + (top(x1) + depth) * k) * S)], fill=LINE, width=int(1.6 * k * S))
    draw.line([(cx * S, (cy - 9.5 * k) * S), (cx * S, (cy + 16 * k) * S)], fill=(150, 140, 205), width=int(1.4 * S))


def badge(draw, x, y, r, text, fill, ink=PAPER):
    circle(draw, x, y, r, fill)
    circle(draw, x, y, r, None, (255, 255, 255, 120), 1.4)
    draw.text((x * S, (y + r * 0.04) * S), text, font=font(AVENIR_NEXT, r * 1.15, HEAVY), fill=ink, anchor="mm")


def left_icon(draw, accent):
    circle(draw, 50, 40, 31, PURPLE_SOFT)
    open_book(draw, 50, 41, 0.9)
    if accent == "sparkle":
        sparkle(draw, 74, 17, 6, AMBER)
    elif accent == "star":
        star(draw, 74, 17, 7, 3, AMBER)
    else:
        sparkle(draw, 74, 17, 5, CORAL)


def mapper(ox, oy, cx, cy, k):
    """Where a point of the 80-pixel drawing (centred on cx, cy) goes when the picture is centred on ox, oy and `k`
    times the size. With the defaults of each art function that is no change at all."""
    return lambda x, y: (ox + (x - cx) * k, oy + (y - cy) * k)


def art_new(draw, ox=1186, oy=44, k=1.0):
    """A big open book with twinkles: a story is about to open."""
    m = mapper(ox, oy, 1186, 44, k)
    circle(draw, *m(1186, 44), 40 * k, (252, 226, 150, 130))
    open_book(draw, *m(1186, 44), 1.55 * k)
    for x, y, r, color in ((1118, 22, 7, AMBER), (1250, 18, 6, CORAL), (1262, 56, 5, PURPLE), (1132, 62, 4, AMBER)):
        sparkle(draw, *m(x, y), r * k, color)
    circle(draw, *m(1098, 40), 2 * k, PURPLE + (190,))
    circle(draw, *m(1276, 36), 2 * k, AMBER + (230,))


def art_daily(draw, ox=1186, oy=40, k=1.0):
    """The story forks: two turns to pick from, as the two Plot twist buttons do."""
    m = mapper(ox, oy, 1186, 40, k)
    circle(draw, *m(1186, 40), 40 * k, (252, 226, 150, 110))
    start = m(1096, 40)
    circle(draw, start[0], start[1], 5 * k, INK)
    curve(draw, start, m(1130, 40), m(1140, 20), m(1182, 20), PURPLE, 3.2 * k)
    curve(draw, start, m(1130, 40), m(1140, 60), m(1182, 60), CORAL, 3.2 * k)
    badge(draw, *m(1196, 20), 13 * k, "1", PURPLE)
    badge(draw, *m(1196, 60), 13 * k, "2", CORAL)
    for x, y, r, color in ((1240, 14, 6, AMBER), (1262, 40, 5, PURPLE), (1244, 66, 5, AMBER)):
        sparkle(draw, *m(x, y), r * k, color)


def art_final(draw, ox=1186, oy=40, k=1.0):
    """Four chapters linked into one story, ending in a star."""
    m = mapper(ox, oy, 1186, 40, k)
    circle(draw, *m(1186, 40), 42 * k, (252, 226, 150, 110))
    xs = (1096, 1150, 1204)
    for a, b in zip(xs, xs[1:] + (1258,)):
        curve(draw, m(a, 40), m(a + 20, 30), m(b - 20, 50), m(b, 40), (150, 140, 205), 2.6 * k)
    for number, x in enumerate(xs, 1):
        badge(draw, *m(x, 40), 12 * k, str(number), PURPLE if number % 2 else CORAL)
    circle(draw, *m(1258, 40), 15 * k, AMBER)
    star(draw, *m(1258, 40), 9.5 * k, 4.2 * k, PAPER)
    for x, y, r, color in ((1118, 12, 5, AMBER), (1232, 66, 5, PURPLE), (1280, 16, 4, CORAL)):
        sparkle(draw, *m(x, y), r * k, color)


BANNERS = {
    "story_new": {"title": "A new story starts Monday", "sub": "Four short chapters. You decide what happens next.",
                  "script": "Once upon a Monday…", "accent": "sparkle", "art": art_new},
    "story_daily": {"title": "Story Relay", "sub": "Today's chapter is below. Pick the turn the story takes.",
                    "script": "What happens next?", "accent": "dot", "art": art_daily},
    "story_final": {"title": "The story we built", "sub": "What the team wrote, and how it really ended.",
                    "script": "The end… or is it?", "accent": "star", "art": art_final},
}


def draw_banner(spec, path):
    image = gradient()
    draw = ImageDraw.Draw(image, "RGBA")
    left_icon(draw, spec["accent"])
    draw.text((100 * S, 38 * S), spec["title"], font=font(AVENIR_NEXT, 31, HEAVY), fill=INK, anchor="ls")
    draw.text((101 * S, 58 * S), spec["sub"], font=font(AVENIR_NEXT, 14.5, MEDIUM), fill=MUTED, anchor="ls")
    draw.rounded_rectangle([101 * S, 65 * S, 143 * S, 68 * S], radius=2 * S, fill=PURPLE)
    draw.text((716 * S, 52 * S), spec["script"], font=font(SCRIPT, 30), fill=(92, 74, 170), anchor="ls")
    spec["art"](draw)
    draw.rectangle([0, 0, W * S - 1, H * S - 1], outline=BORDER + (255,), width=2 * S)
    image.convert("RGB").resize((W, H), Image.LANCZOS).save(path, optimize=True)
    print("wrote", path)


TALL_H = 200


def draw_tall(spec, path):
    """The same banner 1300 x 200: the same colours, icon, words and pictures, larger. The script line goes under the
    subtitle (the middle of a banner this size is taken by the bigger title), and the picture is 1.8 times the size."""
    global H
    H = TALL_H
    try:
        image = gradient()
        draw = ImageDraw.Draw(image, "RGBA")
        circle(draw, 96, 100, 58, PURPLE_SOFT)
        open_book(draw, 96, 101, 1.5)
        if spec["accent"] == "sparkle":
            sparkle(draw, 140, 44, 12, AMBER)
        elif spec["accent"] == "star":
            star(draw, 140, 44, 13, 5.5, AMBER)
        else:
            sparkle(draw, 140, 44, 10, CORAL)
        x = 188
        draw.text((x * S, 86 * S), spec["title"], font=font(AVENIR_NEXT, 50, HEAVY), fill=INK, anchor="ls")
        draw.text(((x + 2) * S, 124 * S), spec["sub"], font=font(AVENIR_NEXT, 24, MEDIUM), fill=MUTED, anchor="ls")
        draw.rounded_rectangle([(x + 2) * S, 138 * S, (x + 82) * S, 143 * S], radius=3 * S, fill=PURPLE)
        draw.text((x * S, 184 * S), spec["script"], font=font(SCRIPT, 40), fill=(92, 74, 170), anchor="ls")
        spec["art"](draw, 1108, 100, 1.8)
        draw.rectangle([0, 0, W * S - 1, H * S - 1], outline=BORDER + (255,), width=2 * S)
        image.convert("RGB").resize((W, H), Image.LANCZOS).save(path, optimize=True)
    finally:
        H = 80
    print("wrote", path)


def main(folder, sizes=("80", "200")):
    os.makedirs(folder, exist_ok=True)
    for name, spec in BANNERS.items():
        if "80" in sizes:
            draw_banner(spec, os.path.join(folder, name + ".png"))
        if "200" in sizes:
            draw_tall(spec, os.path.join(folder, name + "_200.png"))


if __name__ == "__main__":
    arguments = sys.argv[1:]
    chosen = ("80", "200")
    if "--sizes" in arguments:
        at = arguments.index("--sizes")
        chosen = tuple(arguments[at + 1].split(","))
        del arguments[at:at + 2]
    main(arguments[0] if arguments else os.path.join(os.path.dirname(os.path.abspath(__file__)), "banners"), chosen)
