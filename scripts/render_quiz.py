#!/usr/bin/env python3
import json
import math
import os
import shutil
import subprocess
import sys
import time
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".render-cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

import numpy as np
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.mathtext import MathTextParser
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


WIDTH = 1080
HEIGHT = 1920
FPS = 30
BACKGROUND_LOOP_FRAMES = 120
INTRO_SECONDS = 8.0
INTRO_STINGER_OFFSET_SECONDS = 4.0
QUESTION_READ_SECONDS = 3.0
CHOICE_POP_START_SECONDS = 0.12
CHOICE_POP_STAGGER_SECONDS = 0.08
CHOICE_POP_ANIMATION_SECONDS = 0.22
REVEAL_SECONDS = 3.8
TRANSITION_SECONDS = 0.65
OUTRO_SECONDS = 5.6
SFX_ROOT = PROJECT_ROOT / "assets" / "sfx"
VISUAL_ROOT = PROJECT_ROOT / "assets" / "visual"
FONT_ROOT = PROJECT_ROOT / "assets" / "fonts"
STAGE_BACKGROUND_ASSET = VISUAL_ROOT / "stage-background.png"
DEFAULT_FONT_REGULAR = FONT_ROOT / "LibreBaskerville-Regular.ttf"
DEFAULT_FONT_BOLD = FONT_ROOT / "LibreBaskerville-Bold.ttf"
SFX_EXTENSIONS = (".wav", ".mp3", ".m4a")
SFX_VOLUME = {
    "intro_stinger": 0.82,
    "ui_pop": 0.58,
    "transition_whoosh": 0.74,
    "choice_pop": 0.48,
    "countdown_tick": 0.36,
    "urgency_tick": 0.48,
    "reveal_hit": 0.72,
    "correct_chime": 0.78,
    "explanation_pop": 0.48,
    "outro_stinger": 0.78,
    "recap_pop": 0.52,
    "cta_pop": 0.56,
}

def resolve_font(weight):
    default_font = DEFAULT_FONT_BOLD if weight == "bold" else DEFAULT_FONT_REGULAR
    candidates = [
        default_font,
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if weight == "bold" else "/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if weight == "bold" else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if weight == "bold" else "C:/Windows/Fonts/calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return findfont(FontProperties(family="Arial", weight=weight), fallback_to_default=True)


def resolve_display_font():
    candidates = [
        DEFAULT_FONT_BOLD,
        Path("/System/Library/Fonts/Supplemental/Bodoni 72.ttc"),
        Path("/System/Library/Fonts/Supplemental/Didot.ttc"),
        Path("/System/Library/Fonts/Supplemental/Baskerville.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return resolve_font("bold")


FONT_REGULAR = resolve_font("normal")
FONT_BOLD = resolve_font("bold")
FONT_DISPLAY = resolve_display_font()

COLORS = {
    "ink": (12, 11, 28),
    "panel": (25, 24, 58),
    "navy": (22, 29, 74),
    "graphite": (11, 14, 22),
    "graphite_2": (20, 27, 36),
    "quiz_card": (247, 249, 252),
    "paper": (255, 244, 220),
    "paper_line": (227, 211, 181),
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
    "hot_pink": (255, 42, 166),
    "coral": (255, 86, 116),
    "red": (218, 19, 28),
    "deep_red": (72, 3, 10),
    "royal": (0, 86, 205),
    "emerald": (48, 155, 33),
    "amber": (255, 151, 0),
    "orange": (255, 151, 44),
    "gold": (255, 215, 77),
    "gold_deep": (166, 82, 0),
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


@dataclass(frozen=True)
class RenderOptions:
    quality: str = "final"
    bloom: bool = True
    grain: bool = True
    workers: int = 1


def default_worker_count():
    return max(1, (os.cpu_count() or 2) - 1)

CHOICE_PALETTE = [
    (COLORS["red"], COLORS["coral"]),
    (COLORS["royal"], COLORS["cyan"]),
    (COLORS["emerald"], COLORS["lime"]),
    (COLORS["amber"], COLORS["gold"]),
]

SIDE_PANELS = [
    ("TRIGONOMETRIC\nFUNCTIONS", ["y = a sin(k(x-d))+c", "y = a cos(k(x-d))+c"]),
    ("ARITHMETIC\nSEQUENCES", ["a_n = a_1 + (n-1)d", "S_n = n/2(a_1+a_n)"]),
    ("EXPONENTIAL\nFUNCTIONS", ["y = b^x", "b > 0, b != 1"]),
    ("QUADRATIC\nFUNCTIONS", ["y = ax^2 + bx + c", "a != 0"]),
]


def font(size, bold=True):
    return ImageFont.truetype(FONT_DISPLAY, size)


def display_font(size):
    return ImageFont.truetype(FONT_DISPLAY, size)


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


def luminance(color):
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def clamp_alpha(value):
    return max(0, min(255, int(value)))


@lru_cache(maxsize=8)
def visual_asset(path):
    asset_path = Path(path)
    if not asset_path.exists():
        return None
    return Image.open(asset_path).convert("RGBA")


def cover_image(img, size):
    target_w, target_h = size
    scale = max(target_w / img.width, target_h / img.height)
    resized = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


@lru_cache(maxsize=1)
def stage_background_plate():
    plate = visual_asset(str(STAGE_BACKGROUND_ASSET))
    if plate is None:
        return None
    return cover_image(plate, (WIDTH, HEIGHT))


def layer_for(img):
    return Image.new("RGBA", img.size, (0, 0, 0, 0))


def screen_glow(img, glow_layer, opacity=1.0):
    if opacity <= 0:
        return
    if opacity < 1:
        alpha = glow_layer.getchannel("A").point(lambda p: clamp_alpha(p * opacity))
        glow_layer = glow_layer.copy()
        glow_layer.putalpha(alpha)

    glow_rgb = Image.new("RGBA", img.size, (0, 0, 0, 255))
    glow_rgb.alpha_composite(glow_layer)
    screened = ImageChops.screen(img.convert("RGB"), glow_rgb.convert("RGB"))
    img.paste(screened.convert("RGBA"))


def draw_soft_ellipse(img, box, color, alpha=110, blur=22):
    x1, y1, x2, y2 = [int(v) for v in box]
    pad = max(2, int(blur * 3))
    lx1, ly1 = max(0, x1 - pad), max(0, y1 - pad)
    lx2, ly2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
    if lx2 <= lx1 or ly2 <= ly1:
        return
    layer = Image.new("RGBA", (lx2 - lx1, ly2 - ly1), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer, "RGBA")
    layer_draw.ellipse((x1 - lx1, y1 - ly1, x2 - lx1, y2 - ly1), fill=(*color, clamp_alpha(alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer, (lx1, ly1))


def draw_soft_round(img, box, radius, color, alpha=110, blur=18, outline_width=0):
    x1, y1, x2, y2 = [int(v) for v in box]
    pad = max(2, int(blur * 3))
    lx1, ly1 = max(0, x1 - pad), max(0, y1 - pad)
    lx2, ly2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
    if lx2 <= lx1 or ly2 <= ly1:
        return
    layer = Image.new("RGBA", (lx2 - lx1, ly2 - ly1), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer, "RGBA")
    local_box = (x1 - lx1, y1 - ly1, x2 - lx1, y2 - ly1)
    if outline_width:
        layer_draw.rounded_rectangle(local_box, radius=radius, outline=(*color, clamp_alpha(alpha)), width=outline_width)
    else:
        layer_draw.rounded_rectangle(local_box, radius=radius, fill=(*color, clamp_alpha(alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer, (lx1, ly1))


def rounded_gradient(draw, box, radius, top, bottom, outline=None, width=1, alpha=255):
    canvas = getattr(draw, "canvas", None)
    if canvas is None:
        return False

    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    gradient = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(gradient, "RGBA")
    for y in range(h):
        color = mix(top, bottom, y / max(1, h - 1))
        gradient_draw.line((0, y, w, y), fill=(*color, clamp_alpha(alpha)))

    mask = Image.new("L", (w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    gradient.putalpha(ImageChops.multiply(gradient.getchannel("A"), mask))
    canvas.alpha_composite(gradient, (x1, y1))

    if outline:
        draw.rounded_rectangle(box, radius=radius, outline=(*outline, 255), width=width)
    return True


@lru_cache(maxsize=24)
def grain_overlay(phase):
    rng = np.random.default_rng(20260610 + phase)
    noise = rng.normal(128, 18, (HEIGHT, WIDTH)).clip(0, 255).astype(np.uint8)
    alpha = np.full((HEIGHT, WIDTH), 12, dtype=np.uint8)
    rgba = np.dstack([noise, noise, noise, alpha])
    return Image.fromarray(rgba, "RGBA")


@lru_cache(maxsize=1)
def vignette_overlay():
    vignette = Image.new("L", (WIDTH, HEIGHT), 0)
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.ellipse((-260, -160, WIDTH + 260, HEIGHT + 120), fill=190)
    vignette = ImageChops.invert(vignette.filter(ImageFilter.GaussianBlur(90)))
    dark = Image.new("RGBA", (WIDTH, HEIGHT), (*COLORS["black"], 64))
    dark.putalpha(vignette.point(lambda p: int(p * 0.55)))
    return dark


def finish_frame(img, frame_no, bloom=True, grain=True, quality="final"):
    img = img.convert("RGBA")
    if bloom:
        downscale = 4 if quality == "draft" else 2
        blur_radius = 4 if quality == "draft" else 6
        bloom_size = (WIDTH // downscale, HEIGHT // downscale)
        bloom_source = img.resize(bloom_size, Image.Resampling.BILINEAR)
        bright_mask = bloom_source.convert("L").point(lambda p: 0 if p < 174 else min(150, int((p - 174) * 2.35)))
        glow = bloom_source.copy()
        glow.putalpha(bright_mask)
        glow = glow.filter(ImageFilter.GaussianBlur(blur_radius)).resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR)
        img.alpha_composite(glow)

    if grain:
        overlay = grain_overlay(frame_no % 24)
        img = Image.blend(img, Image.alpha_composite(img, overlay), 0.34)

    img.alpha_composite(vignette_overlay())
    return img


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


def render_as_latex(text):
    text = str(text).strip()
    return text.startswith("$") and text.endswith("$") and text.count("$") == 2


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


def rich_text_size(text, size, bold=True):
    if render_as_latex(text):
        return latex_size(text, size, bold)

    bbox = font(size, bold).getbbox(visible_text(text))
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def fit_rich_text_width(text, base, max_width, minimum, bold=True):
    size = fit_size(text, base, 18, minimum)
    while size > minimum and rich_text_size(text, size, bold)[0] > max_width:
        size -= 2
    return max(minimum, size)


def line_height_for(size, contains_math, line_gap):
    multiplier = 1.28 if contains_math else 1.16
    return int(size * multiplier) + line_gap


def wrapped_lines(draw, text, size, bold, max_width):
    if render_as_latex(text):
        return wrap_latex(text, size, bold, max_width)
    return wrap_text(draw, text, font(size, bold), max_width)


def wrapped_text_bounds(draw, text, size, bold, max_width, line_gap):
    lines = wrapped_lines(draw, text, size, bold, max_width)
    contains_math = render_as_latex(text)
    line_height = line_height_for(size, contains_math, line_gap)
    if not lines:
        return lines, 0, 0, line_height

    max_line_width = 0
    for line in lines:
        line_width, _ = rich_text_size(line, size, bold)
        max_line_width = max(max_line_width, line_width)

    total_height = line_height * (len(lines) - 1) + rich_text_size(lines[-1], size, bold)[1]
    return lines, max_line_width, total_height, line_height


def fit_wrapped_text_box(draw, text, base, box, minimum, bold=True, line_gap=8):
    _, _, w, h = box
    size = base
    while size > minimum:
        _, max_line_width, total_height, _ = wrapped_text_bounds(draw, text, size, bold, w, line_gap)
        if max_line_width <= w and total_height <= h:
            return size
        size -= 2

    while size > 12:
        _, max_line_width, total_height, _ = wrapped_text_bounds(draw, text, size, bold, w, line_gap)
        if max_line_width <= w and total_height <= h:
            return size
        size -= 1

    return max(8, size)


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
    if render_as_latex(text):
        draw_latex(draw, xy, text, size, fill, bold, stroke_fill, stroke_width)
    else:
        draw.text(
            xy,
            visible_text(text),
            font=font(size, bold),
            fill=fill,
            stroke_fill=stroke_fill,
            stroke_width=stroke_width,
        )


def draw_choice_text(draw, box, choice, text_color, alpha, base_size=52, minimum_size=36):
    x1, y1, x2, y2 = box
    text_alpha = max(0, min(255, alpha))
    inner_box = (x1, y1, x2, y2)
    dark_text = luminance(text_color) < 90
    inner_fill = COLORS["black"]
    inner_outline = COLORS["white"]
    inner_fill_alpha = 0
    inner_outline_alpha = int(text_alpha * (0.14 if dark_text else 0.10))
    stroke_fill = COLORS["white"] if dark_text else COLORS["black"]
    stroke_width = 1 if dark_text else 3
    rounded(draw, inner_box, 14, (*inner_fill, inner_fill_alpha), (*inner_outline, inner_outline_alpha), 2)

    content_x = x1 + 24
    content_y = y1 + 9
    content_w = x2 - x1 - 48
    content_h = y2 - y1 - 18
    line_gap = -2
    size = fit_wrapped_text_box(draw, choice, base_size, (content_x, content_y, content_w, content_h), minimum_size, True, line_gap)
    lines, _, text_height, line_height = wrapped_text_bounds(draw, choice, size, True, content_w, line_gap)
    text_x = x1 + 24
    text_y = y1 + (y2 - y1 - text_height) / 2 - (3 if render_as_latex(choice) else 2)
    for i, line in enumerate(lines):
        draw_rich_text(draw, (text_x, text_y + i * line_height), line, size, text_color, True, stroke_fill, stroke_width)


def wrap_text(draw, text, font_obj, max_width):
    words = visible_text(text).split()
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
    if render_as_latex(text):
        size = getattr(font_obj, "size", 32)
        width, _ = latex_size(text, size, True)
        draw_latex(draw, (x - width / 2, y), text, size, fill, True, stroke_fill, stroke_width)
        return

    text = visible_text(text)
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
    minimum_size=12,
):
    x, y, w, h = box
    size = fit_wrapped_text_box(draw, text, size, box, minimum_size, bold, line_gap)
    font_obj = font(size, bold)
    if render_as_latex(text):
        lines, _, _, line_height = wrapped_text_bounds(draw, text, size, bold, w, line_gap)
        for i, line in enumerate(lines):
            line_y = y + i * line_height
            line_width, _ = latex_size(line, size, bold)
            line_x = x + (w - line_width) / 2 if align == "center" else x
            draw_latex(draw, (line_x, line_y), line, size, fill, bold, stroke_fill, stroke_width)
        return

    lines, _, _, line_height = wrapped_text_bounds(draw, text, size, bold, w, line_gap)
    for i, line in enumerate(lines):
        line_y = y + i * line_height
        if align == "center":
            text_center(draw, (x + w / 2, line_y), line, font_obj, fill, stroke_fill, stroke_width)
        else:
            draw.text(
                (x, line_y),
                visible_text(line),
                font=font_obj,
                fill=fill,
                stroke_fill=stroke_fill,
                stroke_width=stroke_width,
            )


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def glossy_round(draw, box, radius, fill, outline, width=6, shadow=True):
    x1, y1, x2, y2 = box
    canvas = getattr(draw, "canvas", None)
    if canvas is not None:
        if shadow:
            draw_soft_round(canvas, (x1 + 10, y1 + 14, x2 + 10, y2 + 14), radius, COLORS["black"], 155, 12)
            draw_soft_round(canvas, (x1 - 3, y1 - 3, x2 + 3, y2 + 3), radius + 4, outline, 78, 10, 5)

        top = mix(fill, COLORS["white"], 0.34)
        mid = fill
        bottom = mix(fill, COLORS["black"], 0.36)
        rounded_gradient(draw, box, radius, top, bottom, COLORS["black"], width + 5, 248)
        rounded(draw, box, radius, None, (*outline, 255), width)

        h = max(1, y2 - y1)
        shine_h = min(44, max(14, int(h * 0.24)))
        shine_box = (x1 + 18, y1 + 13, x2 - 18, y1 + shine_h)
        rounded(draw, shine_box, max(8, radius // 2), (*COLORS["white"], 72), None, 1)
        draw.line((x1 + 22, y2 - 16, x2 - 22, y2 - 16), fill=(*bottom, 150), width=3)
        rounded(draw, (x1 + 7, y1 + 7, x2 - 7, y2 - 7), max(8, radius - 6), None, (*COLORS["white"], 40), 2)
        return

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


def draw_marquee_border(draw, frame_no, animate=True):
    bulb_colors = [COLORS["gold"], COLORS["cyan"], COLORS["pink"], COLORS["lime"]]
    positions = []
    for x in range(58, WIDTH - 58, 74):
        positions.append((x, 42))
        positions.append((x, HEIGHT - 42))
    for y in range(120, HEIGHT - 120, 86):
        positions.append((42, y))
        positions.append((WIDTH - 42, y))

    for i, (x, y) in enumerate(positions):
        color_shift = frame_no // 12 if animate else 0
        color = bulb_colors[(i + color_shift) % len(bulb_colors)]
        alpha = 150 + int(70 * (0.5 + 0.5 * math.sin(frame_no * 0.18 + i))) if animate else 210
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(*color, alpha))
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(*COLORS["white"], 160))


def draw_theatre_curtains(draw):
    left = [(0, 0), (284, 0), (218, 182), (176, 398), (104, 672), (0, 842)]
    right = [(WIDTH, 0), (WIDTH - 284, 0), (WIDTH - 218, 182), (WIDTH - 176, 398), (WIDTH - 104, 672), (WIDTH, 842)]
    draw.polygon(left, fill=(*COLORS["deep_red"], 255))
    draw.polygon(right, fill=(*COLORS["deep_red"], 255))

    for side in [-1, 1]:
        anchor_x = 0 if side == -1 else WIDTH
        for i in range(11):
            t = i / 10
            offset = int(22 + t * 242)
            color = mix((150, 6, 18), COLORS["black"], 0.25 + 0.38 * (i % 2))
            if side == -1:
                points = [
                    (anchor_x + offset - 26, 0),
                    (anchor_x + offset + 18, 0),
                    (anchor_x + int(offset * 0.62), 780),
                    (anchor_x + int(offset * 0.35), 864),
                ]
            else:
                points = [
                    (anchor_x - offset + 26, 0),
                    (anchor_x - offset - 18, 0),
                    (anchor_x - int(offset * 0.62), 780),
                    (anchor_x - int(offset * 0.35), 864),
                ]
            draw.polygon(points, fill=(*color, 178))

    for x in range(0, WIDTH, 54):
        color = mix(COLORS["red"], COLORS["black"], 0.22 if (x // 54) % 2 == 0 else 0.48)
        draw.rectangle((x, 0, x + 38, 116), fill=(*color, 228))
    draw.rectangle((0, 106, WIDTH, 138), fill=(*COLORS["black"], 145))
    draw.line((0, 138, WIDTH, 138), fill=(*COLORS["gold"], 120), width=4)


def draw_spotlights(draw, frame_no, animate=True):
    lights = [
        (250, COLORS["blue"], -86),
        (408, COLORS["pink"], -34),
        (540, COLORS["blue"], 0),
        (672, COLORS["pink"], 34),
        (830, COLORS["blue"], 86),
    ]
    for index, (x, color, spread) in enumerate(lights):
        sway = math.sin(frame_no * 0.028 + index) * 20 if animate else 0
        target_x = WIDTH / 2 + spread + sway
        draw.polygon(
            [(x - 18, 50), (x + 18, 50), (target_x + 190, 910), (target_x - 190, 910)],
            fill=(*color, 34),
        )
        draw.ellipse((x - 24, 32, x + 24, 80), fill=(*COLORS["white"], 225))
        draw.ellipse((x - 38, 22, x + 38, 92), outline=(*color, 150), width=6)


def draw_stage_floor(draw):
    draw.rectangle((0, HEIGHT - 348, WIDTH, HEIGHT), fill=(*COLORS["black"], 210))
    for i in range(10):
        y = HEIGHT - 314 + i * 34
        color = COLORS["blue"] if i % 2 == 0 else COLORS["pink"]
        draw.arc((-220, y - 118, WIDTH + 220, y + 236), 184, 356, fill=(*color, 58), width=5)
    draw.ellipse((82, HEIGHT - 304, WIDTH - 82, HEIGHT - 72), outline=(*COLORS["cyan"], 150), width=8)
    draw.ellipse((144, HEIGHT - 262, WIDTH - 144, HEIGHT - 104), outline=(*COLORS["pink"], 120), width=4)
    for x in range(48, WIDTH, 86):
        draw.line((x, HEIGHT - 306, x - 74, HEIGHT), fill=(*COLORS["white"], 22), width=2)


def draw_formula_panel(draw, box, title, lines, accent):
    x1, y1, x2, y2 = box
    canvas = getattr(draw, "canvas", None)
    if canvas is not None:
        draw_soft_round(canvas, (x1 - 5, y1 - 5, x2 + 5, y2 + 5), 22, accent, 94, 12, 4)
    rounded(draw, (x1 + 8, y1 + 10, x2 + 8, y2 + 10), 18, (*COLORS["black"], 150), None, 1)
    if not rounded_gradient(draw, box, 18, mix(COLORS["ink"], accent, 0.10), COLORS["black"], accent, 4, 238):
        rounded(draw, box, 18, (*COLORS["ink"], 236), (*accent, 230), 4)
    rounded(draw, (x1 + 8, y1 + 8, x2 - 8, y2 - 8), 14, None, (*COLORS["hot_pink"], 120), 2)
    rounded(draw, (x1 + 14, y1 + 12, x2 - 14, y1 + 38), 10, (*COLORS["white"], 24), None, 1)

    title_lines = title.split("\n")
    for i, line in enumerate(title_lines):
        text_center(draw, ((x1 + x2) / 2, y1 + 26 + i * 30), line, font(20), COLORS["gold"], COLORS["black"], 2)

    y = y1 + 104
    for line in lines:
        size = fit_rich_text_width(line, 24, x2 - x1 - 24, 15, False)
        text_center(draw, ((x1 + x2) / 2, y), line, font(size, False), COLORS["white"], COLORS["black"], 1)
        y += 48

    if y2 - y1 > 220:
        graph_y = y2 - 76
        draw.line((x1 + 36, graph_y, x2 - 30, graph_y), fill=(*COLORS["white"], 150), width=2)
        draw.line((x1 + 70, graph_y + 34, x1 + 70, graph_y - 44), fill=(*COLORS["white"], 150), width=2)
        points = []
        for step in range(48):
            px = x1 + 36 + step * ((x2 - x1 - 66) / 47)
            py = graph_y - math.sin(step / 47 * math.tau * 1.5) * 28
            points.append((px, py))
        draw.line(points, fill=(*accent, 220), width=4)


def draw_side_formula_panels(draw):
    draw_formula_panel(draw, (28, 334, 192, 626), *SIDE_PANELS[0], COLORS["blue"])
    draw_formula_panel(draw, (28, 664, 192, 910), *SIDE_PANELS[1], COLORS["cyan"])
    draw_formula_panel(draw, (888, 334, 1052, 626), *SIDE_PANELS[2], COLORS["blue"])
    draw_formula_panel(draw, (888, 664, 1052, 910), *SIDE_PANELS[3], COLORS["hot_pink"])


def draw_marquee_frame(
    draw,
    box,
    radius,
    fill,
    accent,
    frame_no=0,
    animate_lights=True,
    bulb_spacing=52,
    alternate_colors=False,
):
    x1, y1, x2, y2 = box
    canvas = getattr(draw, "canvas", None)
    if canvas is not None:
        draw_soft_round(canvas, (x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius + 8, accent, 82, 16, 6)
        draw_soft_round(canvas, (x1 + 18, y1 + 18, x2 - 18, y2 - 18), max(8, radius - 12), COLORS["gold"], 44, 10, 4)
    rounded(draw, (x1 + 14, y1 + 16, x2 + 14, y2 + 16), radius, (*COLORS["black"], 148), None, 1)
    rounded(draw, box, radius, (*fill, 245), (*COLORS["black"], 255), 10)
    rounded(draw, (x1 + 8, y1 + 8, x2 - 8, y2 - 8), max(8, radius - 8), None, (*accent, 245), 6)
    rounded(draw, (x1 + 22, y1 + 22, x2 - 22, y2 - 22), max(8, radius - 16), None, (*COLORS["gold"], 210), 4)

    positions = []
    for x in range(x1 + 58, x2 - 54, bulb_spacing):
        positions.append((x, y1 + 28))
        positions.append((x, y2 - 28))
    for y in range(y1 + 70, y2 - 64, bulb_spacing):
        positions.append((x1 + 28, y))
        positions.append((x2 - 28, y))

    for i, (x, y) in enumerate(positions):
        if animate_lights:
            glow = 150 + int(70 * (0.5 + 0.5 * math.sin(frame_no * 0.22 + i * 0.7)))
        else:
            glow = 216
        if alternate_colors and animate_lights:
            palette = [COLORS["gold"], COLORS["cyan"], COLORS["hot_pink"], COLORS["lime"]]
            bulb_color = palette[(i + frame_no // 8) % len(palette)]
        else:
            bulb_color = COLORS["gold"] if i % 3 else accent
        if canvas is not None:
            draw_soft_ellipse(canvas, (x - 25, y - 25, x + 25, y + 25), bulb_color, glow * 0.42, 9)
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=(*bulb_color, glow))
        draw.ellipse((x - 12, y - 13, x + 10, y + 9), fill=(*mix(bulb_color, COLORS["white"], 0.42), min(245, glow + 16)))
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(*COLORS["white"], min(210, glow + 20)))


def draw_paper_grid(draw, box):
    x1, y1, x2, y2 = box
    canvas = getattr(draw, "canvas", None)
    if canvas is not None:
        draw_soft_round(canvas, (x1 + 7, y1 + 10, x2 + 7, y2 + 10), 18, COLORS["black"], 120, 10)
    if not rounded_gradient(draw, box, 18, COLORS["white"], COLORS["paper"], COLORS["gold_deep"], 4, 255):
        rounded(draw, box, 18, (*COLORS["paper"], 255), (*COLORS["gold_deep"], 210), 4)
    for x in range(x1 + 24, x2 - 18, 32):
        draw.line((x, y1 + 10, x, y2 - 10), fill=(*COLORS["paper_line"], 110), width=1)
    for y in range(y1 + 24, y2 - 18, 32):
        draw.line((x1 + 10, y, x2 - 10, y), fill=(*COLORS["paper_line"], 110), width=1)


def draw_animated_stage_lights(img, frame_no):
    overlay = layer_for(img)
    draw = ImageDraw.Draw(overlay, "RGBA")
    edge_pulse = 0.5 + 0.5 * math.sin(frame_no * 0.075)
    edge_alpha = 126 + 84 * edge_pulse
    draw.line((28, 34, WIDTH - 28, 34), fill=(*COLORS["gold"], int(edge_alpha)), width=52)
    draw.line((28, HEIGHT - 38, WIDTH - 28, HEIGHT - 38), fill=(*COLORS["gold"], int(edge_alpha * 0.94)), width=52)
    draw.line((28, 34, 28, HEIGHT - 38), fill=(*COLORS["orange"], int(edge_alpha * 0.98)), width=52)
    draw.line((WIDTH - 28, 34, WIDTH - 28, HEIGHT - 38), fill=(*COLORS["orange"], int(edge_alpha * 0.98)), width=52)

    for side, x in enumerate([30, WIDTH - 30]):
        for i in range(6):
            y = 136 + ((frame_no * 8 + i * 278 + side * 96) % (HEIGHT - 260))
            draw.ellipse((x - 96, y - 132, x + 96, y + 132), fill=(*COLORS["white"], 58))

    top_glint_x = 82 + ((frame_no * 7) % (WIDTH - 164))
    bottom_glint_x = WIDTH - 82 - ((frame_no * 6) % (WIDTH - 164))
    draw.ellipse((top_glint_x - 164, -22, top_glint_x + 164, 112), fill=(*COLORS["white"], 74))
    draw.ellipse((bottom_glint_x - 184, HEIGHT - 116, bottom_glint_x + 184, HEIGHT + 18), fill=(*COLORS["white"], 64))

    wide_glare = overlay.filter(ImageFilter.GaussianBlur(34))
    screen_glow(img, wide_glare, 0.95)
    hot_glare = overlay.filter(ImageFilter.GaussianBlur(10))
    screen_glow(img, hot_glare, 0.78)

    streaks = layer_for(img)
    streak_draw = ImageDraw.Draw(streaks, "RGBA")
    flare_points = [
        (top_glint_x, 38, COLORS["white"]),
        (bottom_glint_x, HEIGHT - 40, COLORS["white"]),
        (30, 148 + ((frame_no * 11) % (HEIGHT - 300)), COLORS["gold"]),
        (WIDTH - 30, 214 + ((frame_no * 9) % (HEIGHT - 360)), COLORS["gold"]),
    ]
    for x, y, color in flare_points:
        streak_draw.line((x - 130, y, x + 130, y), fill=(*color, 130), width=5)
        streak_draw.line((x, y - 130, x, y + 130), fill=(*color, 96), width=4)
        streak_draw.line((x - 82, y - 82, x + 82, y + 82), fill=(*color, 82), width=3)
        streak_draw.line((x - 82, y + 82, x + 82, y - 82), fill=(*color, 82), width=3)
        streak_draw.ellipse((x - 22, y - 22, x + 22, y + 22), fill=(*COLORS["white"], 150))
    screen_glow(img, streaks.filter(ImageFilter.GaussianBlur(2)), 0.86)

    beams = [
        (COLORS["blue"], 218, -120, 0.032),
        (COLORS["pink"], 862, 120, 0.037),
        (COLORS["cyan"], 540, 0, 0.024),
    ]
    for index, (color, source_x, spread, speed) in enumerate(beams):
        sway = math.sin(frame_no * speed + index * 1.7) * 150
        target_x = WIDTH / 2 + spread + sway
        draw.polygon(
            [
                (source_x - 36, 74),
                (source_x + 36, 74),
                (target_x + 230, HEIGHT - 260),
                (target_x - 230, HEIGHT - 260),
            ],
            fill=(*color, 32),
        )
        draw_soft_ellipse(img, (source_x - 58, 44, source_x + 58, 160), color, 52, 18)

    floor_sweep_x = int((frame_no * 5) % (WIDTH + 520)) - 260
    draw.polygon(
        [
            (floor_sweep_x - 90, HEIGHT - 430),
            (floor_sweep_x + 70, HEIGHT - 430),
            (floor_sweep_x + 280, HEIGHT),
            (floor_sweep_x + 40, HEIGHT),
        ],
        fill=(*COLORS["white"], 26),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(18))
    screen_glow(img, overlay, 0.42)


def draw_showtime_background(frame_no, animate_lights=True, side_panels=False, confetti=False):
    effective_frame = frame_no if animate_lights else 0
    plate = stage_background_plate()
    if plate is not None:
        img = plate.copy()
        draw = ImageDraw.Draw(img, "RGBA")
        draw.canvas = img

        # Keep generated stage detail, but reserve a calm center for dynamic math UI.
        readability = layer_for(img)
        readability_draw = ImageDraw.Draw(readability, "RGBA")
        readability_draw.rounded_rectangle((128, 126, 952, 1782), radius=34, fill=(*COLORS["black"], 58))
        readability_draw.rounded_rectangle((206, 304, 874, 1516), radius=32, fill=(*COLORS["black"], 42))
        readability = readability.filter(ImageFilter.GaussianBlur(10))
        img.alpha_composite(readability)

        if animate_lights:
            pulse = 0.5 + 0.5 * math.sin(effective_frame * 0.045)
            draw_soft_ellipse(img, (184, -82, 438, 436), COLORS["blue"], 42 + 28 * pulse, 26)
            draw_soft_ellipse(img, (642, -70, 896, 436), COLORS["pink"], 38 + 24 * (1 - pulse), 28)
            draw_soft_ellipse(img, (142, HEIGHT - 458, WIDTH - 142, HEIGHT - 82), COLORS["cyan"], 30 + 16 * pulse, 34)
            draw_animated_stage_lights(img, effective_frame)

        if confetti:
            draw_confetti(draw, effective_frame)

        return img

    img = Image.new("RGBA", (WIDTH, HEIGHT), (*COLORS["black"], 255))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.canvas = img

    for y in range(0, HEIGHT, 8):
        t = y / HEIGHT
        draw.rectangle((0, y, WIDTH, y + 8), fill=(*mix((24, 10, 64), COLORS["black"], t), 255))

    draw_spotlights(draw, effective_frame, animate_lights)
    for i in range(16):
        y = 180 + i * 82
        draw.line((0, y, 186, y - 82), fill=(*COLORS["blue"], 54), width=4)
        draw.line((WIDTH, y, WIDTH - 186, y - 82), fill=(*COLORS["pink"], 54), width=4)

    if confetti:
        draw_confetti(draw, effective_frame)

    draw_stage_floor(draw)
    if side_panels:
        draw_side_formula_panels(draw)
    draw_theatre_curtains(draw)
    draw.rectangle((0, 0, WIDTH, 118), fill=(*COLORS["black"], 112))
    rounded(draw, (18, 18, WIDTH - 18, HEIGHT - 18), 30, None, (*COLORS["white"], 44), 14)
    rounded(draw, (38, 38, WIDTH - 38, HEIGHT - 38), 24, None, (*COLORS["black"], 188), 6)
    draw_marquee_border(draw, effective_frame, animate_lights)
    return img


def loud_background(frame_no):
    return loud_background_cached(frame_no % BACKGROUND_LOOP_FRAMES).copy()


@lru_cache(maxsize=BACKGROUND_LOOP_FRAMES)
def loud_background_cached(loop_frame):
    return draw_showtime_background(loop_frame, animate_lights=True, side_panels=False, confetti=True)


@lru_cache(maxsize=1)
def quiz_background_base():
    return draw_showtime_background(0, animate_lights=False, side_panels=False, confetti=False)


def quiz_background(frame_no):
    return quiz_background_base().copy()


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


def draw_stage_title_sign(draw, frame_no, kicker, title, subtitle=None, animate_lights=True):
    draw_marquee_frame(
        draw,
        (150, 148, 930, 626),
        46,
        COLORS["black"],
        COLORS["hot_pink"],
        frame_no,
        animate_lights,
        bulb_spacing=50,
        alternate_colors=True,
    )
    draw_star(draw, (WIDTH / 2, 175), 26, (*COLORS["gold"], 240))
    text_center(draw, (WIDTH / 2, 214), kicker.upper(), display_font(116), COLORS["gold"], COLORS["black"], 7)
    text_center(draw, (WIDTH / 2, 344), title.upper(), display_font(110), COLORS["white"], COLORS["black"], 6)

    if subtitle:
        draw_marquee_frame(
            draw,
            (188, 662, 892, 914),
            34,
            COLORS["deep_red"],
            COLORS["hot_pink"],
            frame_no,
            animate_lights,
            bulb_spacing=48,
            alternate_colors=True,
        )
        text_center(draw, (WIDTH / 2, 724), subtitle.upper(), font(88), COLORS["hot_pink"], COLORS["black"], 8)
        text_center(draw, (WIDTH / 2, 824), "OR YOU'RE COOKED", font(54), COLORS["gold"], COLORS["black"], 5)


def draw_bottom_slogan(draw, text, y, accent=COLORS["cyan"]):
    draw_marquee_frame(draw, (190, y, 890, y + 126), 26, COLORS["ink"], accent, 0, False, bulb_spacing=54)
    text_center(draw, (WIDTH / 2, y + 30), text.upper(), font(43), COLORS["gold"], COLORS["black"], 4)
    draw_star(draw, (242, y + 63), 22, (*COLORS["gold"], 240))
    draw_star(draw, (838, y + 63), 22, (*COLORS["gold"], 240))


def quiet_chip(draw, text, box, color=COLORS["quiz_accent"]):
    flat_round(draw, box, 17, COLORS["graphite_2"], color, 2)
    x1, y1, x2, _ = box
    text_center(draw, ((x1 + x2) / 2, y1 + 13), text.upper(), font(22), COLORS["white"])


def draw_quiz_header(draw, question, question_index):
    draw_brand_bug(draw, 74, 130)
    draw_marquee_frame(draw, (264, 126, 816, 238), 24, COLORS["navy"], COLORS["gold"], 0, False, 48)
    draw_star(draw, (320, 182), 20, (*COLORS["gold"], 240))
    draw_star(draw, (760, 182), 20, (*COLORS["gold"], 240))
    text_center(draw, (WIDTH / 2, 154), f"QUESTION {question_index + 1}", font(45), COLORS["white"], COLORS["black"], 4)

    for i in range(3):
        x = 438 + i * 76
        fill = COLORS["gold"] if i <= question_index else COLORS["dim"]
        rounded(draw, (x, 258, x + 52, 278), 10, (*fill, 255), (*COLORS["black"], 255), 2)


def calm_timer(draw, center, seconds_left, total):
    x, y = center
    color = COLORS["coral"] if seconds_left <= 3 else COLORS["gold"]
    pct = max(0, min(1, seconds_left / total))
    active_bulbs = math.ceil(28 * pct)
    canvas = getattr(draw, "canvas", None)

    if canvas is not None:
        draw_soft_ellipse(canvas, (x - 154, y - 154, x + 154, y + 154), color, 58, 14)
    draw.ellipse((x - 142, y - 142, x + 142, y + 142), fill=(*COLORS["black"], 180))
    draw.ellipse((x - 128, y - 128, x + 128, y + 128), outline=(*COLORS["gold_deep"], 255), width=10)
    draw.ellipse((x - 106, y - 106, x + 106, y + 106), fill=(*COLORS["ink"], 255), outline=(*color, 245), width=5)

    for i in range(28):
        angle = -math.pi / 2 + i / 28 * math.tau
        bx = x + math.cos(angle) * 126
        by = y + math.sin(angle) * 126
        bulb_on = i < active_bulbs
        bulb_color = color if bulb_on else COLORS["dim"]
        alpha = 245 if bulb_on else 126
        if bulb_on and canvas is not None:
            draw_soft_ellipse(canvas, (bx - 16, by - 16, bx + 16, by + 16), bulb_color, 62, 5)
        draw.ellipse((bx - 9, by - 9, bx + 9, by + 9), fill=(*bulb_color, alpha))
        if bulb_on:
            draw.ellipse((bx - 4, by - 4, bx + 4, by + 4), fill=(*COLORS["white"], 190))

    text_center(draw, (x, y - 58), str(max(0, math.ceil(seconds_left))), font(92), color, COLORS["black"], 4)
    rounded(draw, (x - 96, y + 72, x + 96, y + 118), 14, (*COLORS["deep_red"], 245), (*color, 230), 3)
    text_center(draw, (x, y + 83), "SECONDS", font(22), COLORS["white"], COLORS["black"], 1)


def draw_quiz_choice_button(draw, box, fill, outline, text_color, label_fill, label_text, label, choice, alpha, offset):
    if alpha <= 0:
        return

    x1, y1, x2, y2 = box
    box = (x1 + offset, y1, x2 + offset, y2)
    rgba_alpha = max(0, min(255, alpha))
    canvas = getattr(draw, "canvas", None)
    if canvas is not None:
        draw_soft_round(canvas, (box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), 24, outline, rgba_alpha * 0.40, 10, 5)
    rounded(draw, (box[0] + 9, box[1] + 12, box[2] + 9, box[3] + 12), 20, (*COLORS["black"], min(140, rgba_alpha)), None, 1)
    rounded(draw, box, 20, (*COLORS["black"], rgba_alpha), (*COLORS["black"], rgba_alpha), 7)
    inner = (box[0] + 6, box[1] + 6, box[2] - 6, box[3] - 6)
    if not rounded_gradient(draw, inner, 16, mix(fill, COLORS["white"], 0.24), mix(fill, COLORS["black"], 0.08), outline, 4, rgba_alpha):
        rounded(draw, inner, 16, (*fill, rgba_alpha), (*outline, rgba_alpha), 4)
    rounded(
        draw,
        (box[0] + 18, box[1] + 15, box[2] - 18, box[3] - 15),
        14,
        (*COLORS["white"], int(rgba_alpha * 0.06)),
        (*COLORS["white"], int(rgba_alpha * 0.18)),
        2,
    )
    draw.rectangle((box[0] + 28, box[1] + 17, box[2] - 28, box[1] + 32), fill=(*COLORS["white"], int(rgba_alpha * 0.28)))
    rounded(
        draw,
        (x1 + offset + 28, y1 + 24, x1 + offset + 94, y1 + 90),
        33,
        (*label_fill, rgba_alpha),
        (*COLORS["black"], rgba_alpha),
        5,
    )
    text_center(draw, (x1 + offset + 61, y1 + 37), label, font(34), label_text, COLORS["black"], 1)
    draw_choice_text(draw, (x1 + offset + 122, y1 + 24, x2 + offset - 28, y2 - 22), choice, text_color, rgba_alpha)


def question_cache_key(question):
    return json.dumps(question, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def question_from_key(question_key):
    return json.loads(question_key)


def draw_question_prompt(draw, question, question_index):
    draw_quiz_header(draw, question, question_index)
    draw_marquee_frame(draw, (198, 318, 882, 728), 34, COLORS["ink"], COLORS["gold"], 0, False, 48)
    draw_paper_grid(draw, (232, 384, 848, 694))
    prompt_size = fit_size(question["prompt"], 54, 44, 38)
    draw_wrapped(
        draw,
        question["prompt"],
        (262, 462, 556, 170),
        prompt_size,
        COLORS["black"],
        True,
        "center",
        stroke_fill=None,
        stroke_width=0,
    )


def draw_question_choices(draw, question, local_seconds, reveal=False):
    for idx, choice in enumerate(question["choices"]):
        y = 794 + idx * 132
        offset = 0
        is_correct = idx == question["correctIndex"]
        base_fill, base_outline = CHOICE_PALETTE[idx]

        if reveal and is_correct:
            fill, outline, text_color = COLORS["green"], COLORS["lime"], COLORS["white"]
            label_fill, label_text = COLORS["black"], COLORS["green"]
        elif reveal:
            fill, outline, text_color = COLORS["quiz_wrong"], COLORS["quiz_row_edge"], COLORS["quiz_muted"]
            label_fill, label_text = COLORS["black"], COLORS["quiz_muted"]
        else:
            fill = base_fill
            outline = base_outline
            text_color = COLORS["white"]
            label_fill, label_text = COLORS["black"], COLORS["white"]

        if reveal:
            alpha = 126 if not is_correct else 255
        else:
            pop_start = CHOICE_POP_START_SECONDS + idx * CHOICE_POP_STAGGER_SECONDS
            pop_t = (local_seconds - pop_start) / CHOICE_POP_ANIMATION_SECONDS
            if pop_t <= 0:
                alpha = 0
                offset = 56
            else:
                eased = ease_out_back(pop_t)
                alpha = int(255 * ease_in_out(pop_t))
                offset = max(0, int((1 - min(1, eased)) * 56))

        draw_quiz_choice_button(
            draw,
            (204, y, 876, y + 108),
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


def draw_reveal_details(draw, question):
    text_center(draw, (WIDTH / 2, 1346), f"CORRECT ANSWER: {LABELS[question['correctIndex']]}", font(38), COLORS["green"], COLORS["black"], 3)
    draw_marquee_frame(draw, (198, 1398, 882, 1558), 26, COLORS["ink"], COLORS["green"], 0, False, 52)
    explanation_size = fit_size(question["explanation"], 34, 70, 27)
    draw_wrapped(draw, question["explanation"], (238, 1442, 604, 92), explanation_size, COLORS["white"], False, "center")
    draw_marquee_frame(draw, (218, 1604, 862, 1732), 28, COLORS["deep_red"], COLORS["gold"], 0, False, 48)
    text_center(draw, (WIDTH / 2, 1626), "CORRECT!", font(76), COLORS["gold"], COLORS["black"], 6)


@lru_cache(maxsize=12)
def question_prompt_plate(question_key, question_index):
    question = question_from_key(question_key)
    img = quiz_background(0)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.canvas = img
    draw_question_prompt(draw, question, question_index)
    return img


@lru_cache(maxsize=12)
def question_choices_plate(question_key, question_index):
    question = question_from_key(question_key)
    img = question_prompt_plate(question_key, question_index).copy()
    draw = ImageDraw.Draw(img, "RGBA")
    draw.canvas = img
    draw_question_choices(draw, question, 999, False)
    return img


@lru_cache(maxsize=6)
def reveal_plate(question_key, question_index):
    question = question_from_key(question_key)
    img = question_prompt_plate(question_key, question_index).copy()
    draw = ImageDraw.Draw(img, "RGBA")
    draw.canvas = img
    draw_question_choices(draw, question, 0, True)
    draw_reveal_details(draw, question)
    return img


def render_question_scene(question, question_index, local_frame):
    question_key = question_cache_key(question)
    local_seconds = local_frame / FPS
    final_pop_time = (
        CHOICE_POP_START_SECONDS
        + (len(question["choices"]) - 1) * CHOICE_POP_STAGGER_SECONDS
        + CHOICE_POP_ANIMATION_SECONDS
    )
    if local_seconds >= final_pop_time:
        img = question_choices_plate(question_key, question_index).copy()
    else:
        img = question_prompt_plate(question_key, question_index).copy()
        draw = ImageDraw.Draw(img, "RGBA")
        draw.canvas = img
        draw_question_choices(draw, question, local_seconds, False)

    draw = ImageDraw.Draw(img, "RGBA")
    draw.canvas = img
    countdown_elapsed = max(0, local_seconds - QUESTION_READ_SECONDS)
    seconds_left = min(question["timeLimitSeconds"], question["timeLimitSeconds"] - countdown_elapsed)
    calm_timer(draw, (WIDTH // 2, 1532), seconds_left, question["timeLimitSeconds"])
    return img


def render_reveal_scene(question, question_index):
    return reveal_plate(question_cache_key(question), question_index).copy()


def draw_intro(draw, quiz, local_frame):
    scale = 0.92 + 0.08 * ease_out_back(local_frame / 28)
    draw_stage_title_sign(draw, local_frame, "Grade 11", "Functions", "3 Questions", True)
    draw_brand_bug(draw, 74, 146)
    small_chip(draw, "3 Questions", 790, 146, COLORS["cyan"])

    y_shift = int((1 - scale) * 70)
    draw_marquee_frame(draw, (226, 992 + y_shift, 854, 1218 + y_shift), 30, COLORS["ink"], COLORS["gold"], local_frame, True, 48)
    draw_wrapped(
        draw,
        quiz.get("subtitle", "Pick before the timer hits zero.").upper(),
        (260, 1048 + y_shift, 560, 112),
        42,
        COLORS["white"],
        True,
        "center",
        stroke_fill=COLORS["black"],
        stroke_width=4,
    )

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
    draw_choice_text(draw, (x1 + offset + 132, y1 + 26, x2 + offset - 28, y2 - 22), choice, text_color, alpha, 50, 36)


def draw_question(draw, question, question_index, local_frame, reveal=False):
    draw_quiz_header(draw, question, question_index)
    local_seconds = local_frame / FPS

    draw_marquee_frame(draw, (198, 318, 882, 728), 34, COLORS["ink"], COLORS["gold"], 0, False, 48)

    draw_paper_grid(draw, (232, 384, 848, 694))
    prompt_size = fit_size(question["prompt"], 54, 44, 38)
    draw_wrapped(
        draw,
        question["prompt"],
        (262, 462, 556, 170),
        prompt_size,
        COLORS["black"],
        True,
        "center",
        stroke_fill=None,
        stroke_width=0,
    )

    for idx, choice in enumerate(question["choices"]):
        y = 794 + idx * 132
        offset = 0
        is_correct = idx == question["correctIndex"]
        base_fill, base_outline = CHOICE_PALETTE[idx]

        if reveal and is_correct:
            fill, outline, text_color = COLORS["green"], COLORS["lime"], COLORS["white"]
            label_fill, label_text = COLORS["black"], COLORS["green"]
        elif reveal:
            fill, outline, text_color = COLORS["quiz_wrong"], COLORS["quiz_row_edge"], COLORS["quiz_muted"]
            label_fill, label_text = COLORS["black"], COLORS["quiz_muted"]
        else:
            fill = base_fill
            outline = base_outline
            text_color = COLORS["white"]
            label_fill, label_text = COLORS["black"], COLORS["white"]

        if reveal:
            alpha = 126 if not is_correct else 255
        else:
            pop_start = CHOICE_POP_START_SECONDS + idx * CHOICE_POP_STAGGER_SECONDS
            pop_t = (local_seconds - pop_start) / CHOICE_POP_ANIMATION_SECONDS
            if pop_t <= 0:
                alpha = 0
                offset = 56
            else:
                eased = ease_out_back(pop_t)
                alpha = int(255 * ease_in_out(pop_t))
                offset = max(0, int((1 - min(1, eased)) * 56))
        draw_quiz_choice_button(
            draw,
            (204, y, 876, y + 108),
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
        text_center(draw, (WIDTH / 2, 1346), f"CORRECT ANSWER: {LABELS[question['correctIndex']]}", font(38), COLORS["green"], COLORS["black"], 3)
        draw_marquee_frame(draw, (198, 1398, 882, 1558), 26, COLORS["ink"], COLORS["green"], 0, False, 52)
        explanation_size = fit_size(question["explanation"], 34, 70, 27)
        draw_wrapped(draw, question["explanation"], (238, 1442, 604, 92), explanation_size, COLORS["white"], False, "center")
        draw_marquee_frame(draw, (218, 1604, 862, 1732), 28, COLORS["deep_red"], COLORS["gold"], 0, False, 48)
        text_center(draw, (WIDTH / 2, 1626), "CORRECT!", font(76), COLORS["gold"], COLORS["black"], 6)
    else:
        countdown_elapsed = max(0, local_seconds - QUESTION_READ_SECONDS)
        seconds_left = min(question["timeLimitSeconds"], question["timeLimitSeconds"] - countdown_elapsed)
        calm_timer(draw, (WIDTH // 2, 1532), seconds_left, question["timeLimitSeconds"])


def draw_key_summary_row(draw, question, index, y, color):
    glossy_round(draw, (144, y, 936, y + 172), 24, COLORS["panel"], color, 4, shadow=True)
    rounded(draw, (176, y + 26, 258, y + 108), 24, (*color, 255), (*COLORS["black"], 255), 4)
    text_center(draw, (217, y + 47), f"Q{index + 1}", font(26), COLORS["ink"])

    summary = " ".join(str(question.get("keyConcept") or question["explanation"]).split())
    summary_size = fit_rich_text_width(summary, 28, 478, 21, False)
    rounded(draw, (286, y + 34, 804, y + 148), 14, (*COLORS["black"], 172), (*COLORS["white"], 42), 2)
    draw_wrapped(draw, summary, (306, y + 50, 478, 88), summary_size, COLORS["white"], False, "left", line_gap=0)

    answer = LABELS[question["correctIndex"]]
    rounded(draw, (820, y + 46, 898, y + 116), 22, (*COLORS["ink"], 255), (*color, 255), 3)
    text_center(draw, (859, y + 61), answer, font(34), color)


def draw_outro(draw, quiz, local_frame):
    draw_marquee_frame(draw, (150, 166, 930, 492), 42, COLORS["black"], COLORS["hot_pink"], local_frame, True, 50)
    draw_star(draw, (WIDTH / 2, 196), 24, (*COLORS["gold"], 240))
    text_center(draw, (WIDTH / 2, 236), "GRADE 11 FUNCTIONS", display_font(66), COLORS["gold"], COLORS["black"], 5)
    text_center(draw, (WIDTH / 2, 324), "RECAP", display_font(108), COLORS["white"], COLORS["black"], 7)
    text_center(draw, (WIDTH / 2, 426), quiz["endPrompt"].upper(), font(33), COLORS["hot_pink"], COLORS["black"], 4)
    draw_brand_bug(draw, 72, 138)
    small_chip(draw, "Key recap", 786, 138, COLORS["cyan"])

    row_colors = [COLORS["cyan"], COLORS["gold"], COLORS["lime"]]
    for index, question in enumerate(quiz["questions"]):
        draw_key_summary_row(draw, question, index, 596 + index * 190, row_colors[index % len(row_colors)])

    draw_marquee_frame(draw, (218, 1248, 862, 1390), 28, COLORS["deep_red"], COLORS["gold"], local_frame, True, 48)
    draw_wrapped(draw, "Save the recap. Beat your score next round.", (260, 1288, 560, 80), 34, COLORS["white"], True, "center", stroke_fill=COLORS["black"], stroke_width=3)

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
        items.append(("question", idx, int((QUESTION_READ_SECONDS + question["timeLimitSeconds"]) * FPS)))
        items.append(("reveal", idx, int(REVEAL_SECONDS * FPS)))
    items.append(("transition_to_outro", None, int(TRANSITION_SECONDS * FPS)))
    items.append(("outro", None, int(OUTRO_SECONDS * FPS)))
    return items


def add_sfx_cue(cues, name, start_frame, offset_seconds=0.0):
    cues.append(
        {
            "name": name,
            "time": start_frame / FPS + offset_seconds,
            "volume": SFX_VOLUME.get(name, 0.65),
        }
    )


def sound_cue_events(quiz, items):
    cues = []
    cursor = 0

    for kind, idx, frames in items:
        if kind == "intro":
            add_sfx_cue(cues, "intro_stinger", cursor, INTRO_STINGER_OFFSET_SECONDS)
            for offset in [0.18, 1.28, 1.42, 1.56]:
                add_sfx_cue(cues, "ui_pop", cursor, offset)
        elif kind == "transition_to_quiz":
            add_sfx_cue(cues, "transition_whoosh", cursor)
        elif kind == "question":
            duration_seconds = quiz["questions"][idx]["timeLimitSeconds"]
            for choice_index in range(4):
                add_sfx_cue(cues, "choice_pop", cursor, CHOICE_POP_START_SECONDS + choice_index * CHOICE_POP_STAGGER_SECONDS)
            for tick_second in range(1, int(math.ceil(duration_seconds))):
                seconds_left = duration_seconds - tick_second
                cue_name = "urgency_tick" if seconds_left <= 3 else "countdown_tick"
                add_sfx_cue(cues, cue_name, cursor, QUESTION_READ_SECONDS + tick_second)
        elif kind == "reveal":
            add_sfx_cue(cues, "reveal_hit", cursor)
            add_sfx_cue(cues, "correct_chime", cursor, 0.18)
            add_sfx_cue(cues, "explanation_pop", cursor, 0.72)
        elif kind == "transition_to_outro":
            add_sfx_cue(cues, "transition_whoosh", cursor)
        elif kind == "outro":
            add_sfx_cue(cues, "outro_stinger", cursor)
            for offset in [0.35, 0.55, 0.75]:
                add_sfx_cue(cues, "recap_pop", cursor, offset)
            for offset in [1.45, 1.65, 1.85]:
                add_sfx_cue(cues, "cta_pop", cursor, offset)
        cursor += frames

    return cues


def resolve_sfx_asset(name):
    for extension in SFX_EXTENSIONS:
        path = SFX_ROOT / f"{name}{extension}"
        if path.exists():
            return path
    return None


def resolve_sfx_cues(cues):
    if not cues:
        return []

    if not SFX_ROOT.exists():
        print(f"Warning: SFX folder not found at {SFX_ROOT}; rendering without sound effects.", flush=True)
        cue_names = sorted({cue["name"] for cue in cues})
        expected = ", ".join(f"{name}.wav" for name in cue_names)
        print(f"Expected SFX filenames: {expected}", flush=True)
        return []

    resolved = []
    missing = {}
    asset_cache = {}

    for cue in cues:
        name = cue["name"]
        if name not in asset_cache:
            asset_cache[name] = resolve_sfx_asset(name)
        path = asset_cache[name]
        if path:
            resolved.append({**cue, "path": path})
        else:
            missing[name] = missing.get(name, 0) + 1

    for name in sorted(missing):
        extensions = "|".join(SFX_EXTENSIONS)
        print(
            f"Warning: missing SFX asset {SFX_ROOT / name}{extensions}; skipped {missing[name]} cue(s).",
            flush=True,
        )

    if resolved:
        print(f"Using {len(resolved)} sound-effect cue(s) from {SFX_ROOT}.", flush=True)
    else:
        print("Warning: no sound-effect files were found; rendering without sound effects.", flush=True)
    return resolved


def audio_mix_args(cues, duration_seconds):
    if not cues:
        return ["-an"]

    input_args = []
    filters = [
        f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration_seconds:.3f}[silence]"
    ]
    labels = ["[silence]"]

    for index, cue in enumerate(cues, start=1):
        delay_ms = max(0, int(round(cue["time"] * 1000)))
        label = f"sfx{index}"
        volume = max(0, cue["volume"])
        input_args.extend(["-i", str(cue["path"])])
        filters.append(
            f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={volume:.3f},adelay={delay_ms}|{delay_ms}[{label}]"
        )
        labels.append(f"[{label}]")

    mix_filter = (
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"atrim=0:{duration_seconds:.3f},asetpts=N/SR/TB[aout]"
    )
    filter_complex = ";".join([*filters, mix_filter])
    return [
        *input_args,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
    ]


def render_frame(quiz, global_frame, items, options=None):
    options = options or RenderOptions()
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
                question = quiz["questions"][idx]
                img = render_question_scene(question, idx, local)
            elif kind == "reveal":
                question = quiz["questions"][idx]
                img = render_reveal_scene(question, idx)
            elif kind == "transition_to_outro":
                img = transition_background(global_frame, local, frames, False)
            else:
                img = loud_background(global_frame)
                draw = ImageDraw.Draw(img, "RGBA")
                draw.canvas = img
                draw_outro(draw, quiz, local)
            return finish_frame(img, global_frame, options.bloom, options.grain, options.quality).convert("RGB")
        cursor += frames

    return finish_frame(loud_background(global_frame), global_frame, options.bloom, options.grain, options.quality).convert("RGB")


def render_frame_bytes_job(job):
    quiz, frame_no, items, options = job
    return render_frame(quiz, frame_no, items, options).tobytes()


def render_video(quiz, output, options):
    items = timeline(quiz)
    total_frames = sum(item[2] for item in items)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg is required to render MP4 output, but `ffmpeg` was not found on PATH.")

    audio_cues = resolve_sfx_cues(sound_cue_events(quiz, items))
    audio_args = audio_mix_args(audio_cues, total_frames / FPS)

    command = [
        ffmpeg_path,
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
        *audio_args,
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
        if options.workers > 1:
            jobs = ((quiz, frame_no, items, options) for frame_no in range(total_frames))
            chunksize = max(1, min(FPS, total_frames // (options.workers * 8) if options.workers else 1))
            with ProcessPoolExecutor(max_workers=options.workers) as executor:
                for frame_no, frame_bytes in enumerate(executor.map(render_frame_bytes_job, jobs, chunksize=chunksize)):
                    process.stdin.write(frame_bytes)
                    if frame_no % FPS == 0:
                        print(f"Rendered frame {frame_no + 1}/{total_frames}", flush=True)
        else:
            for frame_no in range(total_frames):
                frame = render_frame(quiz, frame_no, items, options)
                process.stdin.write(frame.tobytes())
                if frame_no % FPS == 0:
                    print(f"Rendered frame {frame_no + 1}/{total_frames}", flush=True)
    finally:
        if process.stdin:
            process.stdin.close()

    code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg exited with code {code}")


def render_still(quiz, output, frame_no, options):
    items = timeline(quiz)
    total_frames = sum(item[2] for item in items)
    safe_frame = max(0, min(frame_no, total_frames - 1))
    output.parent.mkdir(parents=True, exist_ok=True)
    render_frame(quiz, safe_frame, items, options).save(output)
    print(f"Rendered frame {safe_frame} to {output}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Render a vertical MCR3U quiz video.")
    parser.add_argument("input", nargs="?", default="data/mcr3u-quiz-001.json")
    parser.add_argument("output", nargs="?", default="out/mcr3u-quiz-001.mp4")
    parser.add_argument("--frame", type=int, help="Render a single still frame instead of a video.")
    parser.add_argument("--quality", choices=["final", "draft", "preview"], default="final")
    parser.add_argument("--workers", type=int, default=None, help="Worker processes for video rendering.")
    parser.add_argument("--no-bloom", action="store_true", help="Disable final bloom pass.")
    parser.add_argument("--no-grain", action="store_true", help="Disable final grain pass.")
    return parser.parse_args(argv)


def render_options_from_args(args):
    if args.quality == "preview":
        bloom = False
        grain = False
    elif args.quality == "draft":
        bloom = True
        grain = False
    else:
        bloom = True
        grain = True

    if args.no_bloom:
        bloom = False
    if args.no_grain:
        grain = False

    workers = args.workers if args.workers is not None else default_worker_count()
    return RenderOptions(args.quality, bloom, grain, max(1, workers))


def main():
    start_time = time.perf_counter()
    args = parse_args(sys.argv[1:])
    options = render_options_from_args(args)
    input_path = Path(args.input)
    output_path = Path(args.output)

    with input_path.open("r", encoding="utf-8") as file:
        quiz = json.load(file)

    validate_quiz(quiz)
    if args.frame is not None or output_path.suffix.lower() in [".png", ".jpg", ".jpeg"]:
        render_still(quiz, output_path, args.frame if args.frame is not None else 300, options)
    else:
        render_video(quiz, output_path, options)
        print(f"Rendered {output_path}")

    elapsed = time.perf_counter() - start_time
    print(f"Render completed in {elapsed:.2f} seconds.")


if __name__ == "__main__":
    main()
