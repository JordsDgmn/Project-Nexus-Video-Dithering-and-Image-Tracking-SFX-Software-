"""Composable scene graphics and a source-sampled ASCII renderer."""

from functools import lru_cache
from math import hypot
import os
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from dither import BAYER
from graphics_settings import ASCII, VECTORS


FONTS = {"Plain": "segoeui.ttf", "Chip": "segoeuib.ttf", "Outline": "segoeui.ttf",
         "Serif italic": "georgiai.ttf", "Mono": "consola.ttf"}


@lru_cache(maxsize=32)
def font(style, pixels):
    path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / FONTS[style]
    try:
        return ImageFont.truetype(str(path), pixels)
    except OSError:
        return ImageFont.load_default(size=pixels)


@lru_cache(maxsize=32)
def snippets(text, split):
    if split == "Words":
        items = text.split()
    elif split == "Phrases":
        items = re.split(r"[\n,;.!?…]+", text)
    else:
        items = text.splitlines()
    return tuple(item.strip()[:85] for item in items if item.strip())[:3000]


@lru_cache(maxsize=768)
def label_mask(text, style, pixels):
    face = font(style, pixels)
    stroke = 1 if style == "Outline" else 0
    bounds = face.getbbox(text, stroke_width=stroke)
    left, top, right, bottom = bounds
    w, h = max(1, right-left), max(1, bottom-top)
    padding = 3 if style == "Chip" else 2
    blank = Image.new("L", (w+2*padding, h+2*padding))
    canvas = ImageDraw.Draw(blank)
    at = (padding-left, padding-top)
    canvas.text(at, text, font=face, fill=255, stroke_width=stroke)
    shadow = blank.filter(ImageFilter.MaxFilter(3))
    return np.asarray(blank), np.asarray(shadow)


def mix_mask(region, mask, color):
    weight = mask[:, :, None].astype(np.float32) / 255
    region[:] = region * (1 - weight) + np.asarray(color) * weight


def put_label(image, text, style, pixels, point, tint, occupied):
    if not text:
        return
    mask, shadow = label_mask(text, style, pixels)
    height, width = image.shape[:2]
    h, w = mask.shape
    if h > height or w > width:
        return
    x = max(0, min(point[0], width-w))
    y = max(0, min(point[1], height-h))
    for left, top, right, bottom in occupied:
        if x < right and x+w > left and y < bottom and y+h > top:
            return
    occupied.append((x, y, x+w, y+h))
    roi = image[y:y+h, x:x+w]
    if style == "Chip":
        roi[:] = tint
        mix_mask(roi, mask, (15, 21, 23))
    else:
        if style in ("Outline", "Mono"):
            mix_mask(roi, shadow, (12, 19, 23))
        mix_mask(roi, mask, tint)


def connect(tracks, density, distance):
    if not density or distance <= 0 or len(tracks) < 2:
        return ()
    centers = np.float32([track.position for track in tracks])
    pairs = []
    for i, center in enumerate(centers):
        distances = np.linalg.norm(centers[i+1:] - center, axis=1)
        pairs.extend((float(value), i, i+1+j) for j, value in enumerate(distances)
                     if 0 < value <= distance)
    counts = [0] * len(tracks)
    result = []
    for _, i, j in sorted(pairs):
        if counts[i] < density and counts[j] < density:
            counts[i] += 1
            counts[j] += 1
            result.append((i, j))
    return result


def integer(point):
    return tuple(np.rint(point).astype(int))


def draw_link(image, start, end, color, style, weight, phase):
    if style == "Straight":
        cv2.line(image, integer(start), integer(end), color, weight, cv2.LINE_AA)
    elif style == "Step":
        points = np.int32([integer(start), integer((end[0], start[1])), integer(end)])
        cv2.polylines(image, [points], False, color, weight, cv2.LINE_AA)
    elif style == "Curved":
        t = np.linspace(0, 1, 11, dtype=np.float32)[:, None]
        control = (start + end) / 2 + (end-start)[::-1] * (.19, -.19)
        points = (1-t)**2 * start + 2*t*(1-t)*control + t**2*end
        cv2.polylines(image, [np.rint(points).astype(np.int32)], False, color, weight, cv2.LINE_AA)
    else:
        length = max(1., float(np.linalg.norm(end-start)))
        spacing = 9 + weight * 3
        for step in range(phase % spacing, int(length), spacing):
            a = start + (end-start) * (step / length)
            b = start + (end-start) * min(1, (step + spacing*.48) / length)
            cv2.line(image, integer(a), integer(b), color, weight, cv2.LINE_AA)


def draw_shape(image, center, size, tint, shape, weight):
    x, y = center
    w, h = size
    if shape == "Rectangle":
        cv2.rectangle(image, (x-w, y-h), (x+w, y+h), tint, weight, cv2.LINE_AA)
    elif shape == "Circle":
        cv2.ellipse(image, center, (w, h), 0, 0, 360, tint, weight, cv2.LINE_AA)
    elif shape == "Crosshair":
        cv2.drawMarker(image, center, tint, cv2.MARKER_CROSS, max(w, h)*2, weight, cv2.LINE_AA)
    else:
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            a, b = x+sx*w, y+sy*h
            cv2.line(image, (a, b), (a-sx*max(2, w//2), b), tint, weight, cv2.LINE_AA)
            cv2.line(image, (a, b), (a, b-sy*max(2, h//2)), tint, weight, cv2.LINE_AA)


@lru_cache(maxsize=24)
def alphabet(ramp):
    face = font("Mono", 12)
    cells = []
    for char in ramp:
        tile = Image.new("L", (9, 15))
        draw = ImageDraw.Draw(tile)
        box = face.getbbox(char)
        at = ((9 - (box[2]-box[0])) // 2 - box[0], 1)
        draw.text(at, char, font=face, fill=255)
        cells.append(np.array(tile))
    return np.stack(cells)


def ascii_frame(frame, config, tint):
    height, width = frame.shape[:2]
    size = max(4, config.ascii_size * min(height, width) / 540)
    columns, rows = max(1, round(width/(size * .61))), max(1, round(height/size))
    samples = cv2.resize(frame, (columns, rows), interpolation=cv2.INTER_AREA)
    level = cv2.cvtColor(samples, cv2.COLOR_BGR2GRAY).astype(np.float32)
    level *= (len(config.ascii_ramp)-1) / 255
    if config.ascii_dither:
        offsets = BAYER[np.arange(rows)[:, None] % 4, np.arange(columns) % 4]
        level += .5 - offsets.astype(np.float32)/255
    indexes = np.clip(np.rint(level), 0, len(config.ascii_ramp)-1).astype(np.intp)
    stamps = alphabet(config.ascii_ramp)[indexes]
    mask = cv2.resize(stamps.transpose(0, 2, 1, 3).reshape(rows*15, columns*9),
                      (width, height), interpolation=cv2.INTER_AREA)
    if config.ascii_color == "Source color":
        colors = cv2.resize(cv2.addWeighted(samples, .67, np.full_like(samples, 255), .33, 0),
                            (width, height), interpolation=cv2.INTER_NEAREST)
    else:
        colors = (237, 245, 249) if config.ascii_color == "Monochrome" else tint
    backing = frame.copy() if config.ascii_backdrop == "Original" else np.zeros_like(frame)
    mix_mask(backing, mask, colors)
    return backing


def paint_graphics(frame, tracks, look, index):
    config = look.graphics
    tint = tuple(bytes.fromhex(look.tint[1:])[::-1])
    height, width = frame.shape[:2]
    weight = max(1, round(config.stroke * min(height, width)/600))
    if look.mode == ASCII:
        image = ascii_frame(frame, config, tint)
    else:
        image = frame.copy()
    if look.links:
        limit = hypot(height, width) * config.link_range/100
        phase = round(index * look.animation_speed / 100)
        for a, b in connect(tracks, config.link_density, limit):
            draw_link(image, tracks[a].position, tracks[b].position, tint, config.line_style, weight, phase)

    text = snippets(config.custom_text, config.text_split) if config.label_source == "Custom" else ()
    occupied = []
    font_size = min(80, max(8, round(min(height, width) * .024 * config.label_size / 100)))
    for track in tracks:
        center = integer(track.position)
        half = tuple(max(3, round(value * config.box_scale / 200)) for value in track.extent)
        if look.mode == VECTORS and len(track.trail) > 2 and config.vector_gain:
            delta = (track.trail[-1] - track.trail[-3]) * (config.vector_gain / 45)
            if np.linalg.norm(delta) > 1.5:
                cv2.arrowedLine(image, center, integer(track.position + delta), tint,
                                weight, cv2.LINE_AA, tipLength=.25)
            if look.trails:
                cv2.polylines(image, [np.rint(track.trail).astype(np.int32)], False, tint,
                              weight, cv2.LINE_AA)
        if config.marks in ("Boxes + text", "Boxes"):
            draw_shape(image, center, half, tint, config.shape, weight)
        if look.labels and config.marks in ("Boxes + text", "Text") and (track.id*37) % 100 < config.label_density:
            if config.label_source == "Coordinates":
                caption = f"{center[0]} / {center[1]}"
            elif config.label_source == "Custom" and text:
                caption = text[(track.id-1) % len(text)]
            else:
                caption = f"{track.id:03d}"
            anchor = (center[0]+4, center[1]-font_size) if config.marks == "Text" else (
                center[0]-half[0], center[1]-half[1]-font_size-2)
            put_label(image, caption, config.label_style, font_size, anchor, tint, occupied)

    return image if look.opacity == 100 else cv2.addWeighted(image, look.opacity/100, frame, 1-look.opacity/100, 0)
