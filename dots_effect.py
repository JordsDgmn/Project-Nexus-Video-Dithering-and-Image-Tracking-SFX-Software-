"""Soft color halftone with a stable, source-colored circle lattice."""

from dataclasses import dataclass
import re

import cv2
import numpy as np


DOTS = "Soft Dots"
BACKDROPS = ("Blurred image", "Original image", "Solid color", "Dots only")
BLENDS = ("Normal", "Multiply", "Screen", "Overlay", "Soft light", "Hard light",
          "Darken", "Lighten", "Color dodge", "Color burn", "Difference", "Exclusion", "Add")
GRADES = ("None", "B&W", "Sepia", "Warm", "Cool", "Vintage", "Fade", "Cyber")
FILTERS = {
    "None": None, "Warming 85": "#ECAA59", "Warming 81": "#E6AC76",
    "Cooling 80": "#4376CD", "Cooling 82": "#73AECA", "Red": "#EC555A",
    "Orange": "#F29650", "Yellow": "#ECE25B", "Green": "#77D674",
    "Cyan": "#67D7D7", "Blue": "#5C87EC", "Violet": "#AA79E8",
}
GRADIENTS = {
    "None": None, "Silver": ("#14161C", "#FAFAF5"),
    "Sea glass": ("#102333", "#2C8B96", "#F5EDC9"),
    "Amber": ("#2B1022", "#AD5530", "#FFE7A1"),
    "Infrared": ("#110E33", "#9F2182", "#EB5247", "#FFF6A9"),
    "Rose dusk": ("#1C1235", "#9B5982", "#FFD9A8"),
    "Blue ice": ("#0C1839", "#4C9BC3", "#EBF8FF"),
}
BLURS = ("Off", "Gaussian", "Box", "Motion")


@dataclass(frozen=True)
class DotsSettings:
    size: int = 11
    backdrop: str = "Blurred image"
    softness: int = 8
    backdrop_opacity: int = 100
    backdrop_color: str = "#000000"
    dot_blend: str = "Normal"
    dot_opacity: int = 100
    invert_mapping: bool = False
    show_grid: bool = False
    coverage: int = 100
    hide_shadows: int = 42
    brightness: int = 0
    contrast: int = 20
    blur: str = "Off"
    blur_amount: int = 8
    blur_angle: int = 0
    grade: str = "None"
    photo_filter: str = "None"
    filter_strength: int = 25
    tint: str = "#FF0000"
    tint_opacity: int = 0
    tint_blend: str = "Multiply"
    saturation: int = 100
    vibrance: int = 0
    hue: int = 0
    gradient: str = "None"
    grayscale: int = 0
    invert_image: bool = False

    def validate(self):
        choices = {
            "backdrop": BACKDROPS, "dot_blend": BLENDS, "blur": BLURS,
            "grade": GRADES, "photo_filter": FILTERS, "tint_blend": BLENDS,
            "gradient": GRADIENTS,
        }
        for field, options in choices.items():
            value = getattr(self, field)
            if not isinstance(value, str) or value not in options:
                raise ValueError(f"Unknown {field.replace('_', ' ')}: {value}")
        ranges = {
            "size": (3, 80), "softness": (0, 60), "backdrop_opacity": (0, 100),
            "dot_opacity": (0, 100), "coverage": (0, 100), "hide_shadows": (0, 100),
            "brightness": (-100, 100), "contrast": (-100, 100), "blur_amount": (0, 60),
            "blur_angle": (-180, 180), "filter_strength": (0, 100), "tint_opacity": (0, 100),
            "saturation": (0, 200), "vibrance": (-100, 100), "hue": (-180, 180),
            "grayscale": (0, 100),
        }
        for field, (low, high) in ranges.items():
            value = getattr(self, field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{field.replace('_', ' ').capitalize()} must be {low} to {high}.")
        for field in ("backdrop_color", "tint"):
            value = getattr(self, field)
            if not isinstance(value, str) or not re.fullmatch(r"#[\da-fA-F]{6}", value, flags=re.ASCII):
                raise ValueError(f"Use a six-digit hexadecimal color for {field.replace('_', ' ')}.")
        for field in ("invert_mapping", "show_grid", "invert_image"):
            if type(getattr(self, field)) is not bool:
                raise ValueError("Dots switches must be on or off.")
        return self


def bgr(color):
    return np.frombuffer(bytes.fromhex(color[1:])[::-1], dtype=np.uint8)


def blend(base, ink, mode):
    if mode == "Normal":
        return ink
    a, b = base * (1 / 255), ink * (1 / 255)
    if mode == "Multiply":
        value = a * b
    elif mode == "Screen":
        value = 1 - (1 - a) * (1 - b)
    elif mode == "Overlay":
        value = np.where(a <= .5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    elif mode == "Hard light":
        value = np.where(b <= .5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    elif mode == "Soft light":
        lift = np.where(a <= .25, ((16 * a - 12) * a + 4) * a, np.sqrt(a))
        value = np.where(b <= .5, a - (1 - 2 * b) * a * (1 - a), a + (2 * b - 1) * (lift - a))
    elif mode == "Darken":
        value = np.minimum(a, b)
    elif mode == "Lighten":
        value = np.maximum(a, b)
    elif mode == "Color dodge":
        value = a / np.maximum(1 - b, 1 / 255)
    elif mode == "Color burn":
        value = 1 - (1 - a) / np.maximum(b, 1 / 255)
    elif mode == "Difference":
        value = np.abs(a - b)
    elif mode == "Exclusion":
        value = a + b - 2 * a * b
    else:
        value = a + b
    return np.clip(value * 255, 0, 255)


def blur_image(frame, sigma, *, edge=cv2.BORDER_REFLECT_101):
    if sigma < .25:
        return frame.copy()
    height, width = frame.shape[:2]
    # Work at reduced resolution on wide blur kernels, then restore the canvas.
    ratio = min(1., 4 / sigma)
    if ratio < 1:
        target = (max(1, round(width * ratio)), max(1, round(height * ratio)))
        small = cv2.resize(frame, target, interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), sigma * ratio, borderType=edge)
        return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(frame, (0, 0), sigma, borderType=edge)


class DotGrid:
    def __init__(self, width, height, settings):
        # Reference frame: 2560 × 1440, with a 13.2 × 22 pixel lattice at size 11.
        self.scale = height / 1440
        pitch_x = max(2., settings.size * 1.2 * self.scale)
        pitch_y = max(2., settings.size * 2.0 * self.scale)
        self.radius = min(pitch_y, pitch_x) * .44
        x, y = np.arange(width, dtype=np.float32) + .5, np.arange(height, dtype=np.float32) + .5
        col, row = (x / pitch_x).astype(np.int32), (y / pitch_y).astype(np.int32)
        center_x, center_y = (col + .5) * pitch_x, (row + .5) * pitch_y
        self.cols, self.rows = int(col[-1]) + 1, int(row[-1]) + 1
        self.sample_x = np.minimum(width - 1, (np.arange(self.cols) + .5) * pitch_x).astype(np.float32)
        self.sample_y = np.minimum(height - 1, (np.arange(self.rows) + .5) * pitch_y).astype(np.float32)
        self.map_x, self.map_y = np.meshgrid(self.sample_x - .5, self.sample_y - .5)
        dist_x, dist_y = (x - center_x).astype(np.float32), (y - center_y).astype(np.float32)
        nearest = dist_y[:, None] ** 2 + dist_x[None, :] ** 2
        yy, xx = np.nonzero(nearest <= (self.radius + .75) ** 2)
        self.pixels = (yy * width + xx).astype(np.int32)
        self.cell = (row[yy] * self.cols + col[xx]).astype(np.int32)
        self.distance = np.sqrt(nearest[yy, xx])
        ids = np.arange(self.cols * self.rows, dtype=np.uint32)
        hashed = (ids ^ (ids >> 16)) * np.uint32(0x7FEB352D)
        hashed = (hashed ^ (hashed >> 15)) * np.uint32(0x846CA68B)
        hashed ^= hashed >> 16
        self.visible = (hashed % 100) < settings.coverage


class DotsRenderer:
    def __init__(self, settings):
        self.s = settings.validate()
        self.shape = self.grid = None
        self.grade_lut = None
        if settings.gradient != "None":
            stops = [bgr(color) for color in GRADIENTS[settings.gradient]]
            self.grade_lut = np.uint8(np.column_stack([
                np.interp(np.arange(256), np.linspace(0, 255, len(stops)),
                          [rgb[channel] for rgb in stops]) for channel in range(3)
            ]))

    def frame(self, source):
        height, width = source.shape[:2]
        if self.shape != (height, width):
            self.shape = height, width
            self.grid = DotGrid(width, height, self.s)
        grid, s = self.grid, self.s
        result = self.backdrop(source, grid.scale)
        if s.dot_opacity and (s.coverage or s.show_grid):
            samples = cv2.remap(source, grid.map_x, grid.map_y, cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_REPLICATE)
            luma = cv2.cvtColor(samples, cv2.COLOR_BGR2GRAY).ravel().astype(np.float32) / 255
            tone = np.clip((luma - .5) * (1 + s.contrast / 100) + .5 + s.brightness / 100, 0, 1)
            if s.invert_mapping:
                tone = 1 - tone
            threshold = s.hide_shadows / 100
            weight = np.clip((tone - threshold) / max(.001, 1 - threshold), 0, 1)
            weight *= grid.visible
            radius = grid.radius * weight ** .76
            alpha = np.clip(radius[grid.cell] + .55 - grid.distance, 0, 1)
            alpha *= (.86 * weight[grid.cell] ** .78) * (s.dot_opacity / 100)
            if s.show_grid:
                regular = .16 * np.clip(max(.65, grid.radius * .17) + .5 - grid.distance, 0, 1)
                alpha = np.maximum(alpha, regular * (s.dot_opacity / 100))
            active = alpha > 0
            if active.any():
                pixels, cells = grid.pixels[active], grid.cell[active]
                base = result.reshape(-1, 3)
                dot_colors = samples.reshape(-1, 3).astype(np.float32)
                lift = .31 * weight[:, None] ** 1.8
                dot_colors += (255 - dot_colors) * lift
                backing = base[pixels].astype(np.float32)
                ink = blend(backing, dot_colors[cells], s.dot_blend)
                base[pixels] = np.rint(backing + (ink - backing) * alpha[active, None]).astype(np.uint8)
        result = self.color(result)
        return self.finish(result, grid.scale)

    def backdrop(self, source, scale):
        s = self.s
        if s.backdrop == "Blurred image":
            frame = blur_image(source, s.softness * scale, edge=cv2.BORDER_CONSTANT)
        elif s.backdrop == "Original image":
            frame = source.copy()
        else:
            frame = np.empty_like(source)
            frame[:] = bgr(s.backdrop_color) if s.backdrop == "Solid color" else 0
        if s.backdrop_opacity != 100:
            frame = cv2.convertScaleAbs(frame, alpha=s.backdrop_opacity / 100)
        return frame

    def color(self, frame):
        s = self.s
        if s.grade == "B&W":
            frame = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        elif s.grade == "Sepia":
            matrix = np.float32(((.131, .534, .272), (.168, .686, .349), (.189, .769, .393)))
            frame = cv2.transform(frame, matrix)
        elif s.grade != "None":
            scales, shift = {
                "Warm": ((.91, 1.01, 1.1), (0, 1, 5)),
                "Cool": ((1.12, 1.02, .91), (4, 1, 0)),
                "Vintage": ((.80, .93, .96), (14, 18, 27)),
                "Fade": ((.78, .78, .78), (29, 29, 29)),
                "Cyber": ((1.30, 1.02, 1.08), (8, -5, 3)),
            }[s.grade]
            matrix = np.column_stack((np.diag(scales), shift)).astype(np.float32)
            frame = cv2.transform(frame, matrix)
        if s.photo_filter != "None" and s.filter_strength:
            color = bgr(FILTERS[s.photo_filter]).astype(np.float32)
            scales = 1 + (color - 128) / 255 * (s.filter_strength / 100)
            frame = cv2.transform(frame, np.diag(scales).astype(np.float32))
        if s.tint_opacity:
            ratio = s.tint_opacity / 100
            painted = blend(frame.astype(np.float32), bgr(s.tint).astype(np.float32), s.tint_blend)
            painted = np.broadcast_to(painted, frame.shape).astype(np.uint8)
            frame = cv2.addWeighted(frame, 1 - ratio, painted, ratio, 0)
        if s.saturation != 100 or s.vibrance or s.hue:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            sat = hsv[:, :, 1].astype(np.float32)
            sat *= (s.saturation / 100) * (1 + (s.vibrance / 100) * (1 - sat / 255))
            hsv[:, :, 1] = np.clip(sat, 0, 255).astype(np.uint8)
            if s.hue:
                hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + round(s.hue / 2)) % 180
            frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        if self.grade_lut is not None:
            frame = self.grade_lut[cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)]
        if s.grayscale:
            gray = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            ratio = s.grayscale / 100
            frame = cv2.addWeighted(frame, 1 - ratio, gray, ratio, 0)
        return frame

    def finish(self, frame, scale):
        s = self.s
        amount = s.blur_amount * scale
        if s.blur == "Gaussian":
            frame = blur_image(frame, amount)
        elif s.blur == "Box" and amount >= .5:
            radius = round(amount)
            frame = cv2.blur(frame, (2 * radius + 1, 2 * radius + 1))
        elif s.blur == "Motion" and amount >= .5:
            radius = round(amount)
            angle = np.deg2rad(s.blur_angle)
            x, y = round(radius * np.cos(angle)), round(radius * np.sin(angle))
            kernel = np.zeros((2 * radius + 1, 2 * radius + 1), dtype=np.float32)
            cv2.line(kernel, (radius - x, radius - y), (radius + x, radius + y), 1, 1)
            kernel /= kernel.sum()
            frame = cv2.filter2D(frame, -1, kernel)
        return cv2.bitwise_not(frame) if s.invert_image else frame
