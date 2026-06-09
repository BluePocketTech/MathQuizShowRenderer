#!/usr/bin/env python3
import json
import math
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".render-cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

import numpy as np
from matplotlib.font_manager import FontProperties
from matplotlib.mathtext import MathTextParser
from PIL import Image, ImageDraw, ImageFilter, ImageFont


WIDTH = 1080
HEIGHT = 1920
FPS = 30
INTRO_SECONDS = 2.4
REVEAL_SECONDS = 3.8
TRANSITION_SECONDS = 0.65
OUTRO_SECONDS = 5.6

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

COLORS = {
    "ink": (12, 11, 28),
    "panel": (25, 24, 58),
    "navy": (22, 29, 74),
    "graphite": (11, 14, 22),
    "graphite_2": (20, 27, 36),
    "quiz_card": (247, 249, 252),
    "quiz_card_edge": (206, 216, 232),
    "quiz_ink": (18, 22, 32),
    "quiz_muted": (100, 112, 132),
    "quiz_row": (31, 39, 54),
    "quiz_row_alt": (37, 45, 61),
    "quiz_row_edge": (91, 101, 119),
    "quiz_accent": (68, 200, 255),
    "quiz_green": (72, 211, 139),
    "quiz_wrong": (47, 54, 69),
    "stage": (54, 21, 124),
    "stage_dark": (25, 17, 69),
    "violet": (112, 52, 255),
    "blue": (31, 198, 255),
    "cyan": (53, 229, 255),
    "pink": (255, 61, 178),
    "coral": (255, 86, 116),
    "orange": (255, 151, 44),
    "gold": (255, 215, 77),
    "green": (64, 245, 145),
    "lime": (174, 255, 64),
    "white": (255, 249, 235),
    "muted": (209, 221, 255),
    "dim": (58, 61, 102),
    "black": (3, 4, 12),
}

LABELS = ["A", "B", "C", "D"]
STYLE_NAME = "Arcade Quiz Blitz"
MATH_PARSER = MathTextParser("agg")


def font(size, bold=True):
    path = FONT_BOLD if bold else FONT_REGULAR
    return ImageFont.truetype(path, size)


def ease_out_back(t):
    t = max(0, min(1, t))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_in_out(t):
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * max(0, min(1, t))


def mix(a, b, t):
    return tuple(int(lerp(a[i], b[i], t)) for i in range(3))


def visible_text(text):
    text = str(text)
    replacements = {
        "$": "",
        "\\left": "",
        "\\right": "",
        "\\,": " ",
        "\\cdot": "x",
        "\\times": "x",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def fit_size(text, base, long_at, minimum):
    text = visible_text(text)
    if len(text) <= long_at:
        return base
    return max(minimum, base - math.ceil((len(text) - long_at) * 0.7))


def contains_latex(text):
    text = str(text)
    return "$" in text or "\\" in text


def latex_tokens(text):
    tokens = []
    current = []
    in_math = False

    for char in str(text):
        if char == "$":
            current.append(char)
            in_math = not in_math
            continue
        if char.isspace() and not in_math:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)

    if current:
        tokens.append("".join(current))
    return tokens


@lru_cache(maxsize=512)
def latex_alpha(text, size, bold=True):
    properties = FontProperties(
        fname=FONT_BOLD if bold else FONT_REGULAR,
        size=size,
        weight="bold" if bold else "normal",
    )
    parsed = MATH_PARSER.parse(str(text), dpi=72, prop=properties)
    alpha = np.asarray(parsed.image).copy()
    return Image.fromarray(alpha, "L")


def latex_size(text, size, bold=True):
    alpha = latex_alpha(text, size, bold)
    return alpha.size


def draw_latex(draw, xy, text, size, fill, bold=True, stroke_fill=None, stroke_width=0):
    canvas = getattr(draw, "canvas", None)
    if canvas is None:
        draw.text(xy, visible_text(text), font=font(size, bold), fill=fill, stroke_fill=stroke_fill, stroke_width=stroke_width)
        return

    alpha = latex_alpha(text, size, bold)
    x, y = int(xy[0]), int(xy[1])

    if stroke_fill and stroke_width > 0:
        stroke_alpha = alpha.filter(ImageFilter.MaxFilter(stroke_width * 2 + 1))
        stroke_layer = Image.new("RGBA", alpha.size, (*stroke_fill, 255))
        stroke_layer.putalpha(stroke_alpha)
        canvas.alpha_composite(stroke_layer, (x, y))

    text_layer = Image.new("RGBA", alpha.size, (*fill, 255))
    text_layer.putalpha(alpha)
    canvas.alpha_composite(text_layer, (x, y))


def draw_rich_text(draw, xy, text, size, fill, bold=True, stroke_fill=None, stroke_width=0):
    if contains_latex(text):
        draw_latex(draw, xy, text, size, fill, bold, stroke_fill, stroke_width)
    else:
        draw.text(
            xy,
            text,
            font=font(size, bold),
            fill=fill,
            stroke_fill=stroke_fill,
            stroke_width=stroke_width,
        )


def wrap_text(draw, text, font_obj, max_width):
    words = str(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font_obj) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def wrap_latex(text, size, bold, max_width):
    lines = []
    current = ""
    for token in latex_tokens(text):
        candidate = f"{current} {token}".strip()
        width, _ = latex_size(candidate, size, bold)
        if current and width > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def text_center(draw, xy, text, font_obj, fill, stroke_fill=None, stroke_width=0):
    x, y = xy
    if contains_latex(text):
        size = getattr(font_obj, "size", 32)
        width, _ = latex_size(text, size, True)
        draw_latex(draw, (x - width / 2, y), text, size, fill, True, stroke_fill, stroke_width)
        return

    box = draw.textbbox((0, 0), text, font=font_obj)
    draw.text(
        (x - (box[2] - box[0]) / 2, y),
        text,
        font=font_obj,
        fill=fill,
        stroke_fill=stroke_fill,
        stroke_width=stroke_width,
    )


def draw_wrapped(
    draw,
    text,
    box,
    size,
    fill,
    bold=True,
    align="left",
    line_gap=8,
    stroke_fill=None,
    stroke_width=0,
):
    x, y, w, _ = box
    font_obj = font(size, bold)
    if contains_latex(text):
        lines = wrap_latex(text, size, bold, w)
        line_height = int(size * 1.28) + line_gap
        for i, line in enumerate(lines):
            line_y = y + i * line_height
            line_width, _ = latex_size(line, size, bold)
            line_x = x + (w - line_width) / 2 if align == "center" else x
            draw_latex(draw, (line_x, line_y), line, size, fill, bold, stroke_fill, stroke_width)
        return

    lines = wrap_text(draw, text, font_obj, w)
    line_height = int(size * 1.16) + line_gap
    for i, line in enumerate(lines):
        line_y = y + i * line_height
        if align == "center":
            text_center(draw, (x + w / 2, line_y), line, font_obj, fill, stroke_fill, stroke_width)
        else:
            draw.text(
                (x, line_y),
                line,
                font=font_obj,
                fill=fill,
                stroke_fill=stroke_fill,
                stroke_width=stroke_width,
            )


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def glossy_round(draw, box, radius, fill, outline, width=6, shadow=True):
    x1, y1, x2, y2 = box
    if shadow:
        rounded(draw, (x1 + 10, y1 + 14, x2 + 10, y2 + 14), radius, (*COLORS["black"], 120), None, 1)
    rounded(draw, box, radius, (*fill, 245), (*COLORS["black"], 255), width + 5)
    rounded(draw, box, radius, (*fill, 245), (*outline, 255), width)
    shine_h = min(44, max(14, int((y2 - y1) * 0.22)))
    rounded(draw, (x1 + 18, y1 + 14, x2 - 18, y1 + shine_h), max(8, radius // 2), (*COLORS["white"], 54), None, 1)


def flat_round(draw, box, radius, fill, outline=None, width=1, shadow=False):
    x1, y1, x2, y2 = box
    if shadow:
        rounded(draw, (x1 + 8, y1 + 10, x2 + 8, y2 + 10), radius, (*COLORS["black"], 86), None, 1)
    rounded(draw, box, radius, (*fill, 255), (*outline, 255) if outline else None, width)


def draw_star(draw, center, radius, fill):
    cx, cy = center
    points = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * 0.42
        angle = -math.pi / 2 + i * math.pi / 5
        points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
    draw.polygon(points, fill=fill)


def draw_confetti(draw, frame_no):
    accents = [COLORS["cyan"], COLORS["pink"], COLORS["gold"], COLORS["lime"], COLORS["orange"]]
    for i in range(34):
        x = int((97 * i + 23 * math.sin(frame_no * 0.02 + i)) % WIDTH)
        y = int((145 + 53 * i + frame_no * (0.7 + (i % 4) * 0.18)) % (HEIGHT - 250)) + 120
        color = accents[i % len(accents)]
        if i % 3 == 0:
            draw.rectangle((x, y, x + 18, y + 8), fill=(*color, 95))
        elif i % 3 == 1:
            draw.ellipse((x, y, x + 14, y + 14), fill=(*color, 100))
        else:
            draw_star(draw, (x, y), 10, (*color, 90))


def draw_marquee_border(draw, frame_no):
    bulb_colors = [COLORS["gold"], COLORS["cyan"], COLORS["pink"], COLORS["lime"]]
    positions = []
    for x in range(58, WIDTH - 58, 74):
        positions.append((x, 42))
        positions.append((x, HEIGHT - 42))
    for y in range(120, HEIGHT - 120, 86):
        positions.append((42, y))
        positions.append((WIDTH - 42, y))

    for i, (x, y) in enumerate(positions):
        color = bulb_colors[(i + frame_no // 12) % len(bulb_colors)]
        alpha = 150 + int(70 * (0.5 + 0.5 * math.sin(frame_no * 0.18 + i)))
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(*color, alpha))
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(*COLORS["white"], 160))


def loud_background(frame_no):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*COLORS["stage_dark"], 255))
    draw = ImageDraw.Draw(img, "RGBA")

    for y in range(0, HEIGHT, 8):
        t = y / HEIGHT
        draw.rectangle((0, y, WIDTH, y + 8), fill=(*mix(COLORS["stage"], COLORS["ink"], t), 255))

    cx, cy = WIDTH // 2, 820
    for i in range(40):
        angle = (i / 40) * math.tau + frame_no * 0.003
        x = cx + math.cos(angle) * 1160
        y = cy + math.sin(angle) * 1160
        color = [COLORS["cyan"], COLORS["pink"], COLORS["gold"], COLORS["violet"]][i % 4]
        draw.polygon(
            [(cx, cy), (x, y), (cx + math.cos(angle + 0.045) * 1160, cy + math.sin(angle + 0.045) * 1160)],
            fill=(*color, 22),
        )

    for y in range(126, HEIGHT - 126, 42):
        color = COLORS["cyan"] if (y // 42) % 2 == 0 else COLORS["pink"]
        draw.rectangle((24, y, 52, y + 24), fill=(*color, 72))
        draw.rectangle((WIDTH - 52, y + 12, WIDTH - 24, y + 36), fill=(*color, 72))

    draw_confetti(draw, frame_no)
    draw.rectangle((0, 0, WIDTH, 118), fill=(*COLORS["ink"], 168))
    draw.rectangle((0, HEIGHT - 118, WIDTH, HEIGHT), fill=(*COLORS["ink"], 168))
    rounded(draw, (18, 18, WIDTH - 18, HEIGHT - 18), 30, None, (*COLORS["white"], 42), 18)
    rounded(draw, (36, 36, WIDTH - 36, HEIGHT - 36), 22, None, (*COLORS["black"], 180), 7)
    draw_marquee_border(draw, frame_no)
    rounded(draw, (72, 132, WIDTH - 72, HEIGHT - 132), 36, None, (*COLORS["gold"], 180), 5)
    return img


def quiz_background(frame_no):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*COLORS["graphite"], 255))
    draw = ImageDraw.Draw(img, "RGBA")

    for y in range(0, HEIGHT, 8):
        t = y / HEIGHT
        draw.rectangle((0, y, WIDTH, y + 8), fill=(*mix(COLORS["graphite_2"], COLORS["graphite"], t), 255))

    for x in range(72, WIDTH, 72):
        line = (32, 39, 49) if x % 216 else (45, 54, 66)
        draw.line((x, 118, x, HEIGHT - 118), fill=line, width=1)
    for y in range(164, HEIGHT - 118, 72):
        line = (32, 39, 49) if y % 216 else (45, 54, 66)
        draw.line((72, y, WIDTH - 72, y), fill=line, width=1)

    draw.rectangle((0, 0, WIDTH, 118), fill=(*COLORS["black"], 118))
    draw.rectangle((0, HEIGHT - 118, WIDTH, HEIGHT), fill=(*COLORS["black"], 118))
    rounded(draw, (44, 44, WIDTH - 44, HEIGHT - 44), 24, None, (*COLORS["white"], 34), 3)
    rounded(draw, (72, 132, WIDTH - 72, HEIGHT - 132), 24, None, (*COLORS["quiz_accent"], 118), 3)

    pulse = int(24 + 8 * math.sin(frame_no * 0.035))
    draw.rectangle((0, 118, WIDTH, 124), fill=(*COLORS["quiz_accent"], pulse))
    return img


def transition_background(frame_no, local_frame, scene_frames, to_quiz):
    t = ease_in_out(local_frame / max(1, scene_frames - 1))
    first = loud_background(frame_no) if to_quiz else quiz_background(frame_no)
    second = quiz_background(frame_no) if to_quiz else loud_background(frame_no)
    img = Image.blend(first, second, t)
    draw = ImageDraw.Draw(img, "RGBA")

    sweep = int(lerp(-260, WIDTH + 260, t))
    color = COLORS["quiz_accent"] if to_quiz else COLORS["gold"]
    sweep_color = mix(color, COLORS["graphite"], 0.46)
    stripe_color = mix(COLORS["white"], sweep_color, 0.45)
    draw.polygon(
        [
            (sweep - 190, 0),
            (sweep + 34, 0),
            (sweep + 190, HEIGHT),
            (sweep - 34, HEIGHT),
        ],
        fill=sweep_color,
    )
    draw.polygon(
        [
            (sweep - 48, 0),
            (sweep + 8, 0),
            (sweep + 48, HEIGHT),
            (sweep - 8, HEIGHT),
        ],
        fill=stripe_color,
    )
    return img


def pill(draw, text, x, y, color):
    glossy_round(draw, (x, y, x + 390, y + 82), 32, COLORS["panel"], color, 5)
    draw.text(
        (x + 24, y + 18),
        text.upper(),
        font=font(31),
        fill=color,
        stroke_fill=COLORS["black"],
        stroke_width=2,
    )


def small_chip(draw, text, x, y, color):
    glossy_round(draw, (x, y, x + 214, y + 58), 20, COLORS["ink"], color, 4, shadow=False)
    text_center(draw, (x + 107, y + 13), text.upper(), font(22), color, COLORS["black"], 2)


def draw_brand_bug(draw, x, y):
    glossy_round(draw, (x, y, x + 168, y + 62), 20, COLORS["pink"], COLORS["gold"], 4, shadow=True)
    text_center(draw, (x + 84, y + 14), "MCR3U", font(25), COLORS["white"], COLORS["black"], 3)


def quiet_chip(draw, text, box, color=COLORS["quiz_accent"]):
    flat_round(draw, box, 17, COLORS["graphite_2"], color, 2)
    x1, y1, x2, _ = box
    text_center(draw, ((x1 + x2) / 2, y1 + 13), text.upper(), font(22), COLORS["white"])


def draw_quiz_header(draw, question, question_index):
    draw.text((76, 146), "MCR3U FUNCTIONS", font=font(28), fill=COLORS["quiz_accent"])
    draw.text((76, 184), f"Question {question_index + 1} of 3", font=font(24, False), fill=COLORS["quiz_muted"])

    for i in range(3):
        x = 456 + i * 70
        fill = COLORS["quiz_accent"] if i <= question_index else COLORS["quiz_row_edge"]
        flat_round(draw, (x, 168, x + 46, 186), 9, fill, None, 1)

    diff_color = COLORS["coral"] if question["difficulty"] == "Hard" else COLORS["gold"]
    quiet_chip(draw, question["difficulty"], (742, 138, 1008, 194), diff_color)
    quiet_chip(draw, "100 pts", (742, 212, 1008, 268), COLORS["pink"])


def calm_timer(draw, center, seconds_left, total):
    x, y = center
    color = COLORS["coral"] if seconds_left <= 3 else COLORS["quiz_accent"]
    pct = max(0, min(1, seconds_left / total))
    start = -90
    end = start + 360 * pct

    draw.ellipse((x - 122, y - 122, x + 122, y + 122), fill=(*COLORS["black"], 112))
    draw.ellipse((x - 110, y - 110, x + 110, y + 110), fill=(*COLORS["quiz_row"], 255))
    draw.pieslice((x - 110, y - 110, x + 110, y + 110), start=start, end=end, fill=(*color, 255))
    draw.ellipse((x - 78, y - 78, x + 78, y + 78), fill=(*COLORS["graphite"], 255))
    text_center(draw, (x, y - 45), str(max(0, math.ceil(seconds_left))), font(80), color)
    text_center(draw, (x, y + 42), "seconds", font(22, False), COLORS["muted"])


def draw_quiz_choice_button(draw, box, fill, outline, text_color, label_fill, label_text, label, choice, alpha, offset):
    if alpha <= 0:
        return

    x1, y1, x2, y2 = box
    box = (x1 + offset, y1, x2 + offset, y2)
    rgba_alpha = max(0, min(255, alpha))
    rounded(draw, (box[0] + 7, box[1] + 9, box[2] + 7, box[3] + 9), 22, (*COLORS["black"], min(95, rgba_alpha)), None, 1)
    rounded(draw, box, 22, (*fill, rgba_alpha), (*outline, rgba_alpha), 3)
    rounded(
        draw,
        (x1 + offset + 30, y1 + 26, x1 + offset + 92, y1 + 88),
        31,
        (*label_fill, rgba_alpha),
        (*outline, rgba_alpha),
        2,
    )
    text_center(draw, (x1 + offset + 61, y1 + 36), label, font(34), label_text)
    choice_size = fit_size(choice, 48, 18, 36)
    draw_rich_text(draw, (x1 + offset + 126, y1 + 33), choice, choice_size, text_color, True)


def draw_intro(draw, quiz, local_frame):
    scale = 0.86 + 0.14 * ease_out_back(local_frame / 30)
    title_size = fit_size(quiz["title"], 98, 22, 74)
    draw_brand_bug(draw, 72, 138)
    small_chip(draw, "3 Questions", 786, 138, COLORS["cyan"])
    pill(draw, "No hiding", 345, 326, COLORS["lime"])
    draw_star(draw, (190, 470), 42, (*COLORS["gold"], 210))
    draw_star(draw, (898, 506), 34, (*COLORS["pink"], 210))
    draw_star(draw, (858, 1040), 24, (*COLORS["cyan"], 180))

    title_top = int(540 - 30 * (scale - 0.86))
    draw_wrapped(
        draw,
        quiz["title"].upper(),
        (96, title_top, 888, 280),
        title_size,
        COLORS["white"],
        True,
        "center",
        stroke_fill=COLORS["black"],
        stroke_width=6,
    )
    glossy_round(draw, (118, 830, 962, 1018), 34, COLORS["panel"], COLORS["cyan"], 5)
    draw_wrapped(draw, "Pick fast. Then prove it.", (154, 878, 772, 120), 50, COLORS["gold"], True, "center", stroke_fill=COLORS["black"], stroke_width=3)
    small_chip(draw, "Timer on", 196, 1108, COLORS["gold"])
    small_chip(draw, "No fluff", 490, 1108, COLORS["pink"])
    small_chip(draw, "Lock in", 784, 1108, COLORS["lime"])


def timer(draw, center, seconds_left, total):
    x, y = center
    color = COLORS["coral"] if seconds_left <= 3 else COLORS["gold"]
    start = -90
    end = start + 360 * max(0, min(1, seconds_left / total))
    draw.ellipse((x - 122, y - 110, x + 122, y + 134), fill=(*COLORS["black"], 120))
    draw.ellipse((x - 112, y - 112, x + 112, y + 112), fill=(*COLORS["white"], 34))
    draw.pieslice((x - 106, y - 106, x + 106, y + 106), start=start, end=end, fill=(*color, 255))
    draw.ellipse((x - 78, y - 78, x + 78, y + 78), fill=COLORS["ink"])
    text_center(draw, (x, y - 46), str(max(0, math.ceil(seconds_left))), font(82), color, COLORS["black"], 3)
    rounded(draw, (x - 92, y + 84, x + 92, y + 128), 14, (*COLORS["panel"], 235), (*color, 230), 3)
    text_center(draw, (x, y + 93), "SECONDS", font(20), COLORS["white"], COLORS["black"], 1)


def draw_round_pips(draw, active_index):
    for i in range(3):
        x = 424 + i * 92
        color = COLORS["lime"] if i <= active_index else COLORS["dim"]
        rounded(draw, (x, 228, x + 62, 228 + 24), 12, (*color, 255), (*COLORS["black"], 255), 3)


def draw_choice_button(draw, box, fill, outline, text_color, label_fill, label_text, label, choice, alpha, offset):
    x1, y1, x2, y2 = box
    box = (x1 + offset, y1, x2 + offset, y2)
    if alpha < 200:
        rounded(draw, (box[0] + 10, box[1] + 14, box[2] + 10, box[3] + 14), 28, (*COLORS["black"], 80), None, 1)
        rounded(draw, box, 28, (*fill, alpha), (*COLORS["black"], 180), 10)
        rounded(draw, box, 28, (*fill, alpha), (*outline, 105), 5)
    else:
        glossy_round(draw, box, 28, fill, outline, 5)
    draw.rectangle((x1 + offset + 26, y1 + 13, x2 + offset - 26, y1 + 34), fill=(*COLORS["white"], 46 if alpha >= 200 else 24))
    rounded(draw, (x1 + offset + 32, y1 + 25, x1 + offset + 104, y1 + 97), 36, (*label_fill, alpha), (*COLORS["black"], 255), 5)
    text_center(draw, (x1 + offset + 68, y1 + 38), label, font(38), label_text, COLORS["black"], 2)
    choice_size = fit_size(choice, 45, 20, 34)
    draw_rich_text(draw, (x1 + offset + 132, y1 + 34), choice, choice_size, text_color, True, COLORS["black"], 2)


def draw_question(draw, question, question_index, local_frame, reveal=False):
    draw_quiz_header(draw, question, question_index)

    flat_round(draw, (72, 300, 1008, 676), 28, COLORS["quiz_card"], COLORS["quiz_card_edge"], 3, shadow=True)
    rounded(draw, (104, 328, 520, 382), 17, (*COLORS["graphite_2"], 255), (*COLORS["quiz_accent"], 255), 2)
    draw.text((126, 342), question["topic"].upper(), font=font(25), fill=COLORS["white"])
    prompt_size = fit_size(question["prompt"], 64, 48, 46)
    draw_wrapped(
        draw,
        question["prompt"],
        (118, 436, 844, 210),
        prompt_size,
        COLORS["quiz_ink"],
        True,
        stroke_fill=None,
        stroke_width=0,
    )

    for idx, choice in enumerate(question["choices"]):
        y = 750 + idx * 146
        enter = ease_in_out((local_frame - idx * 4) / 18)
        offset = int((1 - enter) * 78)
        is_correct = idx == question["correctIndex"]

        if reveal and is_correct:
            fill, outline, text_color = COLORS["quiz_green"], COLORS["lime"], COLORS["quiz_ink"]
            label_fill, label_text = COLORS["quiz_ink"], COLORS["quiz_green"]
        elif reveal:
            fill, outline, text_color = COLORS["quiz_wrong"], COLORS["quiz_row_edge"], COLORS["quiz_muted"]
            label_fill, label_text = COLORS["graphite_2"], COLORS["quiz_muted"]
        else:
            fill = COLORS["quiz_row"] if idx % 2 == 0 else COLORS["quiz_row_alt"]
            outline = COLORS["quiz_row_edge"]
            text_color = COLORS["white"]
            label_fill, label_text = COLORS["quiz_card"], COLORS["quiz_ink"]

        alpha = 132 if reveal and not is_correct else int(lerp(0, 255, enter))
        draw_quiz_choice_button(
            draw,
            (92, y, 988, y + 116),
            fill,
            outline,
            text_color,
            label_fill,
            label_text,
            LABELS[idx],
            choice,
            alpha,
            offset,
        )

    if reveal:
        text_center(draw, (WIDTH / 2, 692), f"Correct answer: {LABELS[question['correctIndex']]}", font(46), COLORS["quiz_green"])
        flat_round(draw, (96, 1408, 984, 1584), 24, COLORS["quiz_row"], COLORS["quiz_green"], 3, shadow=True)
        explanation_size = fit_size(question["explanation"], 35, 78, 28)
        draw_wrapped(draw, question["explanation"], (132, 1448, 816, 120), explanation_size, COLORS["white"], False, "center")
    else:
        seconds_elapsed = local_frame / FPS
        seconds_left = question["timeLimitSeconds"] - seconds_elapsed
        calm_timer(draw, (WIDTH // 2, 1504), seconds_left, question["timeLimitSeconds"])


def draw_key_summary_row(draw, question, index, y, color):
    glossy_round(draw, (96, y, 984, y + 176), 28, COLORS["panel"], color, 4, shadow=True)
    rounded(draw, (124, y + 28, 210, y + 112), 26, (*color, 255), (*COLORS["black"], 255), 4)
    text_center(draw, (167, y + 48), f"Q{index + 1}", font(28), COLORS["ink"])
    draw.text((238, y + 28), question["topic"].upper(), font=font(27), fill=color, stroke_fill=COLORS["black"], stroke_width=2)

    summary = " ".join(visible_text(question.get("keyConcept") or question["explanation"]).split())
    summary_size = fit_size(summary, 31, 74, 25)
    draw_wrapped(draw, summary, (238, y + 72, 560, 92), summary_size, COLORS["white"], False, "left")

    answer = LABELS[question["correctIndex"]]
    rounded(draw, (846, y + 46, 948, y + 122), 24, (*COLORS["ink"], 255), (*color, 255), 3)
    text_center(draw, (897, y + 60), answer, font(34), color)


def draw_outro(draw, quiz, local_frame):
    scale = 0.9 + 0.1 * ease_out_back(local_frame / 28)
    draw_brand_bug(draw, 72, 138)
    small_chip(draw, "Key recap", 786, 138, COLORS["cyan"])
    pill(draw, "Score check", 345, 292, COLORS["green"])
    draw_star(draw, (188, 516), 42, (*COLORS["gold"], 210))
    draw_star(draw, (900, 548), 38, (*COLORS["pink"], 210))
    draw_star(draw, (858, 1460), 28, (*COLORS["cyan"], 190))
    title_text = "RECAP. NO EXCUSES."
    title_size = fit_size(title_text, 74, 22, 62)
    draw_wrapped(
        draw,
        title_text,
        (96, int(432 - 18 * scale), 888, 170),
        title_size,
        COLORS["white"],
        True,
        "center",
        stroke_fill=COLORS["black"],
        stroke_width=6,
    )
    draw_wrapped(draw, quiz["endPrompt"], (130, 646, 820, 66), 35, COLORS["gold"], True, "center", stroke_fill=COLORS["black"], stroke_width=3)

    row_colors = [COLORS["cyan"], COLORS["gold"], COLORS["lime"]]
    for index, question in enumerate(quiz["questions"]):
        draw_key_summary_row(draw, question, index, 742 + index * 194, row_colors[index % len(row_colors)])

    glossy_round(draw, (118, 1418, 962, 1556), 30, COLORS["panel"], COLORS["pink"], 5)
    draw_wrapped(draw, "Save the recap. Beat your score next round.", (154, 1458, 772, 88), 36, COLORS["white"], True, "center", stroke_fill=COLORS["black"], stroke_width=3)
    small_chip(draw, "Replay", 196, 1642, COLORS["cyan"])
    small_chip(draw, "Share", 490, 1642, COLORS["pink"])
    small_chip(draw, "Review", 784, 1642, COLORS["lime"])


def progress_bar(draw, frame_in_scene, scene_frames, color):
    pct = max(0, min(1, frame_in_scene / max(1, scene_frames)))
    rounded(draw, (72, 1690, 1008, 1718), 14, (*COLORS["black"], 170), (*COLORS["white"], 72), 3)
    rounded(draw, (80, 1698, int(80 + 920 * pct), 1710), 8, (*color, 255), None, 1)
    for x in range(148, 1000, 92):
        draw.rectangle((x, 1692, x + 4, 1716), fill=(*COLORS["white"], 46))


def validate_quiz(quiz):
    questions = quiz.get("questions", [])
    if len(questions) != 3:
        raise ValueError("Quiz JSON must contain exactly 3 questions.")
    for i, question in enumerate(questions, start=1):
        if len(question.get("choices", [])) != 4:
            raise ValueError(f"Question {i} must contain exactly 4 choices.")
        if question.get("correctIndex") not in [0, 1, 2, 3]:
            raise ValueError(f"Question {i} correctIndex must be 0, 1, 2, or 3.")
        if question.get("timeLimitSeconds", 0) < 3:
            raise ValueError(f"Question {i} timeLimitSeconds must be at least 3.")
        validate_math_delimiters(question.get("prompt", ""), f"Question {i} prompt")
        validate_math_delimiters(question.get("explanation", ""), f"Question {i} explanation")
        for choice_index, choice in enumerate(question.get("choices", []), start=1):
            validate_math_delimiters(choice, f"Question {i} choice {choice_index}")


def validate_math_delimiters(text, field_name):
    if str(text).count("$") % 2 != 0:
        raise ValueError(f"{field_name} has unbalanced LaTeX math delimiters.")


def timeline(quiz):
    items = [
        ("intro", None, int(INTRO_SECONDS * FPS)),
        ("transition_to_quiz", None, int(TRANSITION_SECONDS * FPS)),
    ]
    for idx, question in enumerate(quiz["questions"]):
        items.append(("question", idx, int(question["timeLimitSeconds"] * FPS)))
        items.append(("reveal", idx, int(REVEAL_SECONDS * FPS)))
    items.append(("transition_to_outro", None, int(TRANSITION_SECONDS * FPS)))
    items.append(("outro", None, int(OUTRO_SECONDS * FPS)))
    return items


def render_frame(quiz, global_frame, items):
    cursor = 0

    for kind, idx, frames in items:
        if cursor <= global_frame < cursor + frames:
            local = global_frame - cursor
            if kind == "intro":
                img = loud_background(global_frame)
                draw = ImageDraw.Draw(img, "RGBA")
                draw.canvas = img
                draw_intro(draw, quiz, local)
            elif kind == "transition_to_quiz":
                img = transition_background(global_frame, local, frames, True)
            elif kind == "question":
                img = quiz_background(global_frame)
                draw = ImageDraw.Draw(img, "RGBA")
                draw.canvas = img
                question = quiz["questions"][idx]
                draw_question(draw, question, idx, local, False)
                progress_bar(draw, local, frames, COLORS["quiz_accent"])
            elif kind == "reveal":
                img = quiz_background(global_frame)
                draw = ImageDraw.Draw(img, "RGBA")
                draw.canvas = img
                question = quiz["questions"][idx]
                draw_question(draw, question, idx, local, True)
                progress_bar(draw, local, frames, COLORS["quiz_green"])
            elif kind == "transition_to_outro":
                img = transition_background(global_frame, local, frames, False)
            else:
                img = loud_background(global_frame)
                draw = ImageDraw.Draw(img, "RGBA")
                draw.canvas = img
                draw_outro(draw, quiz, local)
            return img.convert("RGB")
        cursor += frames

    return loud_background(global_frame).convert("RGB")


def render_video(quiz, output):
    items = timeline(quiz)
    total_frames = sum(item[2] for item in items)
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s:v",
        f"{WIDTH}x{HEIGHT}",
        "-framerate",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        str(output),
    ]

    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for frame_no in range(total_frames):
            frame = render_frame(quiz, frame_no, items)
            process.stdin.write(frame.tobytes())
            if frame_no % FPS == 0:
                print(f"Rendered frame {frame_no + 1}/{total_frames}", flush=True)
    finally:
        if process.stdin:
            process.stdin.close()

    code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg exited with code {code}")


def render_still(quiz, output, frame_no):
    items = timeline(quiz)
    total_frames = sum(item[2] for item in items)
    safe_frame = max(0, min(frame_no, total_frames - 1))
    output.parent.mkdir(parents=True, exist_ok=True)
    render_frame(quiz, safe_frame, items).save(output)
    print(f"Rendered frame {safe_frame} to {output}")


def main():
    args = sys.argv[1:]
    frame_no = None
    if "--frame" in args:
        frame_arg_index = args.index("--frame")
        try:
            frame_no = int(args[frame_arg_index + 1])
        except (IndexError, ValueError) as exc:
            raise ValueError("--frame must be followed by a frame number") from exc
        args = args[:frame_arg_index] + args[frame_arg_index + 2 :]

    input_path = Path(args[0] if len(args) > 0 else "data/mcr3u-quiz-001.json")
    output_path = Path(args[1] if len(args) > 1 else "out/mcr3u-quiz-001.mp4")

    with input_path.open("r", encoding="utf-8") as file:
        quiz = json.load(file)

    validate_quiz(quiz)
    if frame_no is not None or output_path.suffix.lower() in [".png", ".jpg", ".jpeg"]:
        render_still(quiz, output_path, frame_no if frame_no is not None else 300)
    else:
        render_video(quiz, output_path)
        print(f"Rendered {output_path}")


if __name__ == "__main__":
    main()
