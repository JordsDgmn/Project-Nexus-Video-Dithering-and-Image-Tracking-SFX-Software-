"""Seeded, seamless light fields for Project Entropy."""

from dataclasses import dataclass, field
from functools import lru_cache
import math
import re

import cv2
import numpy as np

from entropy_bokeh import LIGHT_COLORS, BokehCamera, BokehSettings, light_points
from entropy_style import Style, StyleStack, pulse_exposure
from entropy_texture import Texture, TextureStack


MAX_EXPORT_SECONDS = 30 * 60
BASE_MOTION_SECONDS = 6
SEAMLESS = "Seamless clip"
EXACT = "Exact speed"
LOOP_FITS = (SEAMLESS, EXACT)
ROTATION_DIRECTIONS = ("Clockwise", "Counterclockwise")


AURA = "Prismatic aura"
OIL = "Iridescent oil"
GLASS = "Glass caustics"
POOL = "Pool reflections"
PRISM = "Prism refraction"
BOKEH = "Cinematic bokeh"
CUSTOM = "Custom palette"
MODES = (AURA, OIL, GLASS, POOL, PRISM, BOKEH)
BLENDS = ("Screen", "Add", "Soft light", "Multiply", "Overlay", "Normal")
RATIOS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5),
          "4:3": (4, 3), "21:9": (21, 9)}
PALETTES = {
    "Full spectrum": ("#FF426D", "#FF8245", "#FFE79B", "#75FFD6", "#29B9FC", "#6B55FF", "#FF62C1", "#FF426D"),
    "Opal": ("#527DFF", "#76E5FF", "#CEFFF0", "#FFF2C5", "#FFC1DB", "#A781FA", "#527DFF"),
    "Lagoon": ("#186482", "#3BBBC8", "#A5FFE9", "#F4FFF1", "#65D7EC", "#186482"),
    "Solar": ("#981C62", "#FF594F", "#FFA13C", "#FFF5C1", "#FFD27A", "#981C62"),
    "Ultraviolet": ("#37118E", "#7147E3", "#B05AFF", "#FFA0EF", "#91ADF9", "#37118E"),
    "Neutral": ("#9FB6CE", "#DDEEF5", "#FFF9EE", "#BFC9DA", "#9FB6CE"),
    "Cinema": ("#FFAA58", "#FFE5B1", "#6EC5CE", "#4987A7", "#F47C67", "#FFAA58"),
}


@dataclass(frozen=True)
class Look:
    mode: str = AURA
    palette: str = "Opal"
    hue: int = 0
    spectrum: int = 100
    saturation: int = 90
    scatter: int = 61
    compact: int = 45
    dispersion: int = 55
    glow: int = 59
    intensity: int = 88
    blend: str = "Screen"
    background: str = "#10091E"
    cycles: int = 1
    seed: int = 17
    colors: tuple = ()
    textures: Texture = field(default_factory=Texture)
    motion_speed: int = 100
    loop_fit: str = SEAMLESS
    rotation_angle: int = 0
    rotation_speed: int = 0
    rotation_direction: str = "Clockwise"
    style: Style = field(default_factory=Style)
    bokeh: BokehSettings = field(default_factory=BokehSettings)

    def validate(self):
        if self.mode not in MODES or self.palette not in (*PALETTES, CUSTOM) or self.blend not in BLENDS:
            raise ValueError("Choose a supported effect, palette and blend mode.")
        if self.loop_fit not in LOOP_FITS or self.rotation_direction not in ROTATION_DIRECTIONS:
            raise ValueError("Choose a supported loop mode and rotation direction.")
        for key, low, high in (
            ("hue", -180, 180), ("spectrum", 1, 200), ("saturation", 0, 150),
            ("scatter", 0, 100), ("compact", 0, 100), ("dispersion", 0, 100),
            ("glow", 0, 100), ("intensity", 0, 150), ("cycles", 0, 5), ("seed", 0, 999999),
            ("motion_speed", 0, 400), ("rotation_angle", -180, 180), ("rotation_speed", 0, 360),
        ):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key.capitalize()} must be {low} to {high}.")
        if not isinstance(self.background, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.background):
            raise ValueError("Background color needs six hexadecimal digits.")
        if self.colors or self.palette == CUSTOM:
            validate_colors(self.colors)
        if not isinstance(self.textures, Texture):
            raise ValueError("Invalid texture settings.")
        self.textures.validate()
        if not isinstance(self.style, Style):
            raise ValueError("Invalid style settings.")
        self.style.validate()
        if not isinstance(self.bokeh, BokehSettings):
            raise ValueError("Invalid bokeh camera settings.")
        self.bokeh.validate()
        return self


@dataclass(frozen=True)
class Timing:
    motion_cycles: float
    rotation_turns: float


def clip_timing(look, seconds):
    base = min(seconds, BASE_MOTION_SECONDS)
    motion = look.cycles * (look.motion_speed / 100) * (seconds / base)
    rotation = look.rotation_speed * seconds / 360
    if look.loop_fit == SEAMLESS:
        # A positive setting still produces motion on very short clips.
        motion = max(1, math.floor(motion + .5)) if motion else 0
        rotation = max(1, math.floor(rotation + .5)) if rotation else 0
    if look.rotation_direction == "Counterclockwise":
        rotation = -rotation
    return Timing(motion, rotation)


def validate_colors(colors):
    if not isinstance(colors, (tuple, list)) or not 1 <= len(colors) <= 10:
        raise ValueError("A palette needs 1 to 10 colors.")
    if any(not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in colors):
        raise ValueError("Use a six-digit color such as #ACCFEF.")
    return tuple(color.upper() for color in colors)


def decode_look(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid look settings.")
    values = dict(data)
    if "colors" in values:
        raw = values["colors"]
        values["colors"] = validate_colors(raw) if raw else ()
    if "textures" in values:
        if not isinstance(values["textures"], dict):
            raise ValueError("Invalid texture settings.")
        values["textures"] = Texture(**values["textures"])
    if "style" in values:
        if not isinstance(values["style"], dict):
            raise ValueError("Invalid style settings.")
        values["style"] = Style(**values["style"])
    if "bokeh" in values:
        if not isinstance(values["bokeh"], dict):
            raise ValueError("Invalid bokeh camera settings.")
        values["bokeh"] = BokehSettings(**values["bokeh"])
    elif values.get("mode") == BOKEH:
        values["bokeh"] = BokehSettings(model="Classic")
    return Look(**values).validate()


PRESETS = {
    AURA: Look(),
    OIL: Look(OIL, "Full spectrum", 24, 117, 118, 72, 56, 65, 38, 108,
              "Screen", "#080814", 1, 63),
    GLASS: Look(GLASS, "Opal", -15, 110, 85, 58, 47, 79, 46, 102,
                "Screen", "#10162E", 1, 42),
    POOL: Look(POOL, "Lagoon", -14, 96, 91, 72, 59, 32, 53, 110,
               "Screen", "#1A7584", 1, 28),
    PRISM: Look(PRISM, "Full spectrum", -9, 112, 108, 78, 60, 84, 34, 104,
                "Screen", "#100D20", 1, 234),
    BOKEH: Look(BOKEH, "Cinema", 0, 106, 97, 55, 43, 62, 52, 130,
                "Screen", "#110E19", 1, 281),
}


@dataclass(frozen=True)
class ExportSpec:
    ratio: str = "16:9"
    pixels: int = 1080
    fps: int = 30
    seconds: int = 6
    quality: str = "Balanced"

    def validate(self):
        if self.ratio not in RATIOS or self.pixels not in (720, 1080, 1440):
            raise ValueError("Choose a supported aspect ratio and resolution.")
        if self.fps not in (24, 30, 60):
            raise ValueError("Choose 24, 30 or 60 fps.")
        if type(self.seconds) is not int or not 1 <= self.seconds <= MAX_EXPORT_SECONDS:
            raise ValueError("Duration must be between 1 second and 30 minutes.")
        if self.quality not in ("Balanced", "Fine", "Native"):
            raise ValueError("Choose Balanced, Fine or Native rendering.")
        return self

    @property
    def size(self):
        w, h = RATIOS[self.ratio]
        scale = self.pixels / min(w, h)
        return even(w * scale), even(h * scale)

    @property
    def frames(self):
        return self.seconds * self.fps

    @property
    def internal(self):
        return capped(self.size, {"Balanced": 960, "Fine": 1600, "Native": 10000}[self.quality])


def even(value):
    return max(2, round(value / 2) * 2)


def capped(size, longest):
    w, h = size
    ratio = min(1, longest / max(w, h))
    return max(2, round(w * ratio)), max(2, round(h * ratio))


def rgb(hex_color):
    return np.frombuffer(bytes.fromhex(hex_color[1:]), dtype=np.uint8).astype(np.float32) / 255


@lru_cache(maxsize=96)
def spectral_lut(palette, saturation):
    if palette[-1] != palette[0] or len(palette) == 1:
        palette = (*palette, palette[0])
    colors = np.float32([rgb(color) for color in palette])
    coordinates = np.linspace(0, 1, len(colors))
    values = np.linspace(0, 1, 2048)
    table = np.column_stack([np.interp(values, coordinates, colors[:, channel]) for channel in range(3)])
    luma = table @ np.float32((.2126, .7152, .0722))
    return np.clip(luma[:, None] + (table - luma[:, None]) * (saturation / 100), 0, 1).astype(np.float32)


def smooth(low, high, field):
    amount = np.clip((field - low) / (high - low), 0, 1)
    return amount * amount * (3 - 2 * amount)


@lru_cache(maxsize=48)
def phases(seed):
    return np.random.default_rng(seed).uniform(0, math.tau, 20).astype(np.float32)


@lru_cache(maxsize=36)
def bokeh_lights(seed):
    lights = np.random.default_rng(np.random.SeedSequence((seed, 117))).random((64, 6), dtype=np.float32)
    lights[:, :2] = lights[:, :2] - .5
    return lights


@lru_cache(maxsize=112)
def bokeh_stamp(radius, blur):
    half = max(4, round(radius * (1.30 + blur*.11)))
    values = np.arange(-half, half+1, dtype=np.float32) / radius
    distance = np.hypot(values[None, :], values[:, None])
    softness = .045 + .082*blur
    disc = .70 * (1 - smooth(1-softness, 1+softness, distance))
    glow = np.exp(-(distance/(.80 + blur*.105))**2) * (.15 + .04*blur)
    rim = np.exp(-((distance - .86) / (.073 + .035*blur))**2)*(.28 - .041*blur)
    feather = 1 - smooth(half/radius-.29, half/radius, distance)
    return (disc * (.48 + .52*np.clip(distance, 0, 1)) + glow + rim) * feather


class Simulator:
    def __init__(self, size):
        self.width, self.height = size
        short = self.short = min(size)
        self.x = (np.arange(self.width, dtype=np.float32)[None, :] + .5 - self.width / 2) / short
        self.y = (np.arange(self.height, dtype=np.float32)[:, None] + .5 - self.height / 2) / short
        self.aspect_x, self.aspect_y = self.width / short, self.height / short
        self.edge = np.exp(-.48 * ((2 * self.x / self.aspect_x) ** 2 + (2 * self.y / self.aspect_y) ** 2))
        self.noise = np.random.default_rng(815).uniform(-.0018, .0018, (self.height, self.width)).astype(np.float32)
        self.textures = None
        self.style = None
        self.camera = None

    def color(self, field, look, palette=None):
        phase = np.remainder(.49 + (field - .49) * (look.spectrum / 100) + look.hue / 360, 1)
        palette = palette or (look.colors if look.palette == CUSTOM else PALETTES[look.palette])
        return spectral_lut(tuple(palette), look.saturation)[np.minimum(2047, (phase * 2048).astype(np.int32))]

    def frame(self, turn, look, seconds=BASE_MOTION_SECONDS):
        timing = clip_timing(look, seconds)
        progress = turn % 1 if look.loop_fit == SEAMLESS else turn
        position = (progress * timing.motion_cycles) % 1
        t = math.tau * position
        phase = phases(look.seed)
        scatter = look.scatter / 100
        density = 2 ** ((look.compact - 48) / 34)
        if look.mode == BOKEH:
            if look.bokeh.model == "Classic":
                emission, ground = self.classic_bokeh(t, look, scatter, density)
            else:
                if self.camera is None:
                    self.camera = BokehCamera((self.width, self.height))
                points = light_points(look.seed, look.bokeh.layout)
                color_phase = .49 + (points[:, 4] - .5) * (.55 + .60*look.dispersion/100)
                colors = self.color(color_phase, look, LIGHT_COLORS[look.bokeh.light_color])
                emission, ground = self.camera.render(look.bokeh, look, t, progress, seconds,
                                                       look.loop_fit == SEAMLESS, colors)
            light = np.clip(emission * 2.1, 0, 1) if look.blend == "Multiply" else None
        else:
            if look.mode == AURA:
                energy, hue, white, ground = self.aura(t, phase, scatter, density)
            elif look.mode == OIL:
                energy, hue, white, ground = self.oil(t, phase, scatter, density)
            elif look.mode == GLASS:
                energy, hue, white, ground = self.glass(t, phase, scatter, density, look.dispersion / 100)
            elif look.mode == PRISM:
                energy, hue, white, ground = self.prism(t, phase, scatter, density, look.dispersion / 100)
            else:
                energy, hue, white, ground = self.pool(t, phase, scatter, density, look.dispersion / 100)
            dispersion = look.dispersion / 100
            if look.mode in (AURA, OIL):
                hue = .49 + (hue - .49) * (.82 + .33 * dispersion)
            light = self.color(hue, look)
            if look.mode in (GLASS, POOL, PRISM):
                # Small wavelength-dependent offsets are drawn from the same light field.
                offset = max(0, min(13, round(min(self.width, self.height) * .011 * dispersion)))
                if offset:
                    r = np.pad(energy[:, :-offset], ((0, 0), (offset, 0)), mode="edge")
                    b = np.pad(energy[:, offset:], ((0, 0), (0, offset)), mode="edge")
                    emission = light * np.stack((r, energy, b), axis=-1)
                    emission = cv2.addWeighted(emission, .55 + .40 * dispersion, light * energy[:, :, None],
                                               .45 - .40 * dispersion, 0)
                else:
                    emission = light * energy[:, :, None]
            else:
                emission = light * energy[:, :, None]
            emission += white[:, :, None] * np.float32((.90, .95, 1.0))
        if look.glow:
            image = self.glow(emission, look.glow / 100)
            emission = cv2.addWeighted(emission, 1, image, look.glow / 75, 0)
        emission *= look.intensity / 100

        base = np.clip(rgb(look.background) * ground[:, :, None], 0, 1)
        if look.blend == "Add":
            result = base + emission
        elif look.blend == "Multiply":
            alpha = np.clip(np.max(emission, axis=2), 0, 1)[:, :, None]
            result = base * (1 - alpha * (1 - light))
        elif look.blend == "Overlay":
            light_value = np.clip(.5 + emission * .65, 0, 1)
            result = np.where(base < .5, 2 * base * light_value, 1 - 2 * (1 - base) * (1 - light_value))
        elif look.blend == "Soft light":
            light_value = np.clip(.5 + emission, 0, 1)
            result = base + (2 * light_value - 1) * (np.sqrt(base) - base)
        elif look.blend == "Normal":
            alpha = np.clip(np.max(emission, axis=2) * .92, 0, 1)[:, :, None]
            result = base * (1 - alpha) + np.minimum(emission * 1.55, 1) * alpha
        else:  # Screen
            result = base + (1 - base) * emission
        result += self.noise[:, :, None]
        np.clip(result, 0, 1, out=result)
        frame = cv2.convertScaleAbs(result, alpha=255)
        style = look.style
        if style.has_layers:
            if self.style is None:
                self.style = StyleStack((self.width, self.height))
            if style.has_form:
                frame = self.style.form(frame, style, t)
        rotation = math.remainder(look.rotation_angle + progress * timing.rotation_turns * 360, 360)
        if abs(rotation) > 1e-8:
            center = ((self.width - 1) / 2, (self.height - 1) / 2)
            transform = cv2.getRotationMatrix2D(center, -rotation, 1)
            frame = cv2.warpAffine(frame, transform, (self.width, self.height),
                                   flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        if style.has_layers and (style.flare or style.has_particles):
            frame = self.style.lights(frame, style, t)
        if look.textures.active:
            if self.textures is None:
                self.textures = TextureStack((self.width, self.height))
            frame = self.textures.apply(frame, look.textures, position, look.seed, rgb(look.background)*255)
        if style.enabled and style.strobe:
            frame = pulse_exposure(frame, style, progress * seconds)
        return frame

    def glow(self, emission, amount):
        width, height = max(2, self.width // 7), max(2, self.height // 7)
        small = cv2.resize(emission, (width, height), interpolation=cv2.INTER_AREA)
        sigma = max(.7, min(width, height) * (.022 + amount * .054))
        blurred = cv2.GaussianBlur(small, (0, 0), sigma)
        return cv2.resize(blurred, (self.width, self.height), interpolation=cv2.INTER_LINEAR)

    def aura(self, t, p, scatter, density):
        x, y = self.x * density, self.y * density
        u = x + .17 * np.sin(2.8 * y + p[0] + t) + scatter * .11 * np.cos(5 * y + x + p[1] - 2 * t)
        v = y + .10 * np.cos(3.8 * x + p[2] - t)
        a = np.sin(3.1 * u + .73 * np.sin(3.7 * v + t + p[3]) + p[4])
        b = np.cos(4.25 * v + 1.7 * u + p[5] - t)
        w = np.sin(6.0 * u - 4.1 * v + p[6] + 2 * t)
        ribbon = (a * .63 + b * .32 + w * scatter * .17)
        envelope = np.exp(-.70 * ((u - .17 * math.cos(t)) ** 2 + (.77 * v + .09) ** 2))
        band = np.exp(-(ribbon * (2.6 - scatter * .7)) ** 2)
        second = np.exp(-((ribbon - .48) * 3.0) ** 2)
        curtains = .74 + .26 * np.sin(5 * u - 2 * v + p[7] + t)
        energy = envelope * (.70 * band * curtains + .25 * second + .10 * (1 - self.edge))
        hue = .49 + ribbon * .44 + u * .105 + .08 * np.sin(2.05 * v + t) + .07 * w
        white = .13 * np.power(band, 5) * envelope * (curtains ** 3)
        ground = .46 + self.edge * (.25 + .47 * np.square(b))
        return energy, hue, white, ground

    def oil(self, t, p, scatter, density):
        x, y = 3.1 * density * self.x, 3.1 * density * self.y
        u = x + (.42 + scatter * .72) * np.sin(1.20 * y + p[0] + .44 * math.sin(t))
        v = y + (.31 + scatter * .74) * np.cos(1.38 * x + p[1] - .48 * math.cos(t))
        q = .57 * np.sin(1.35 * u + .78 * v + p[2] + t) + .43 * np.cos(1.6 * v - .47 * u + p[3] - t)
        r = .62 * np.cos(1.42 * u - 1.18 * v + q * (2.1 + scatter) + p[4])
        r += .38 * np.sin(2.20 * v + q * 1.8 + p[5] + 2 * t)
        fold = .54 * q + .43 * r + .13 * scatter * np.sin(4.2 * u + 2.5 * v + r + p[6])
        hue = .49 + fold * .96 + .055 * np.cos(t + p[7])
        coverage = smooth(-.42, .38, .55 * q - .84 * r + .33 * self.edge)
        sheen = np.power(.50 + .50 * np.cos(fold * 18 + .6), 2.5)
        energy = (.21 + .78 * coverage) * (.57 + .43 * sheen) * (.27 + .73 * self.edge)
        white = np.power(np.maximum(0, .55 + .45 * np.cos(q * 8.7 - r * 3.9 + p[8])), 9) * coverage * .22
        ground = (.50 + .62 * (1 - coverage)) * (.62 + .38 * self.edge)
        return energy, hue, white, ground

    def glass(self, t, p, scatter, density, dispersion):
        x, y = 3.2 * density * self.x, 3.2 * density * self.y
        angle = .42 + .17 * math.sin(t + p[0])
        u = x * math.cos(angle) - y * math.sin(angle)
        v = x * math.sin(angle) + y * math.cos(angle)
        u += (.13 + .42 * scatter) * np.sin(2.5 * v + p[1] + t)
        v += (.09 + .25 * scatter) * np.sin(2.1 * u + p[2] - t)
        cone = 1.2 * u + .52 * v ** 2 + .37 * np.sin(v * 3.2 + p[3] - t)
        crossing = v * 1.43 - .30 * u ** 2 + .25 * np.cos(u * 4 + p[4] + 2 * t)
        g1, g2 = np.sin(cone + p[5]), np.cos(crossing + p[6])
        interface = np.abs(g1 + .32 * g2)
        second = np.abs(g2 - .52 * g1 + .11 * np.cos(v * 7 + p[7]))
        first_fold = np.exp(-interface * (12 + 10 * (1 - scatter)))
        second_fold = np.exp(-second * (15 + 6 * (1 - scatter)))
        spill = np.exp(-2.1 * interface) * .26 + np.exp(-3.7 * second) * .22
        beam = (.30 + .70 * self.edge) * (.72 + .28 * np.sin(cone * .81 - crossing + p[8]))
        energy = np.clip((.82 * first_fold + .70 * second_fold + spill) * beam, 0, 1.22)
        hue = .49 + .21 * np.sin(cone + crossing + p[9]) + (.28 + .25 * dispersion) * (g1 - .5 * g2)
        white = (.21 * first_fold ** 2 + .12 * second_fold ** 2) * beam
        ground = (.46 + .29 * (g1 * .5 + .5) + .32 * (g2 * .5 + .5)) * (.64 + .36 * self.edge)
        return energy, hue, white, ground

    def pool(self, t, p, scatter, density, dispersion):
        x = self.x * (5 + 6 * density)
        y = self.y * (5 + 6 * density)
        u = x + (.07 + scatter*.37) * np.sin(y * .91 + x * .39 + p[0] + t)
        v = y + (.12 + scatter*.41) * np.sin(x * .86 - y * .63 + p[1] - t)
        col, row = np.floor(u).astype(np.int32), np.floor(v).astype(np.int32)
        fx = np.subtract(u, col, dtype=np.float32)
        fy = np.subtract(v, row, dtype=np.float32)
        first = np.full(u.shape, 16., dtype=np.float32)
        second = first.copy()
        left, top = int(col.min()) - 1, int(row.min()) - 1
        xs = np.arange(left, int(col.max()) + 2, dtype=np.int32)[None, :]
        ys = np.arange(top, int(row.max()) + 2, dtype=np.int32)[:, None]
        cell_hash = (xs * np.int32(73471)) ^ (ys * np.int32(19391))
        a = ((cell_hash ^ (cell_hash >> 13)) & 1023).astype(np.float32) * (math.tau / 1024)
        b = (((cell_hash * np.int32(37)) ^ (cell_hash >> 9)) & 1023).astype(np.float32) * (math.tau / 1024)
        drift = .08 + scatter * .18
        centers_x = .50 + scatter * .34 * np.cos(a + p[2]) + drift * np.sin(a + t)
        centers_y = .50 + scatter * .34 * np.cos(b + p[3]) + drift * np.sin(b - t)
        hit_x, hit_y = col - left, row - top
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sx = dx + centers_x[hit_y + dy, hit_x + dx]
                sy = dy + centers_y[hit_y + dy, hit_x + dx]
                distance = (fx - sx) ** 2 + (fy - sy) ** 2
                np.minimum(second, np.maximum(first, distance), out=second)
                np.minimum(first, distance, out=first)
        border = np.sqrt(second) - np.sqrt(first)
        lace = np.exp(-border * (18 + (1 - scatter) * 20))
        halo = np.exp(-border * (5.2 - 2 * scatter))
        refraction = (.36 + .64 * np.square(.57 + .43 * np.cos(u * .85 - v * .48 + t + p[7])))
        energy = (.73 * lace + .30 * halo) * refraction * (.62 + .38 * self.edge)
        hue = .48 + (.20 + .14 * dispersion) * np.sin(u * .31 + v * .39 + p[5] + t)
        hue += .09 * np.cos(v * 1.3 - u * .74 + p[6])
        white = .21 * lace ** 2 * refraction
        ground = .47 + .48 * self.edge + .35 * (1 - np.minimum(first, 1)) * (.45 + .55 * refraction)
        return energy, hue, white, ground

    def prism(self, t, p, scatter, density, dispersion):
        x, y = self.x * density, self.y * density
        a = self.x + .12 * math.sin(t + p[0])
        b = self.y + .14 * math.cos(t + p[1])
        energy = np.zeros_like(x + y)
        hue = np.zeros_like(energy)
        white = np.zeros_like(energy)
        for i in range(3):
            direction = .45 + i * 1.06 + .23 * math.sin(t + p[2+i])
            cx, cy = math.cos(direction), math.sin(direction)
            u = cx*x - cy*y + .2 * math.cos(t + p[5+i])
            v = cy*x + cx*y + .25 * math.sin(t + p[8+i])
            f = 1.28 * u + .64*np.abs(v) + (.08 + scatter*.30)*np.sin(v*6.1+u*3.3+p[11+i]+t)
            g = v*1.36 - .38*np.abs(u) + .17*np.sin(u*4.2 + p[14+i] - t)
            lattice = np.abs(np.sin(f * (4.8 + 1.9*scatter) + p[17+i]))
            split = np.abs(np.sin(g * (3.8 + .54*i) + p[i]))
            lens = np.exp(-((u - .12*i)*(.84 + i*.12))**2 - ((v + .16*i)*1.62)**2)
            facets = np.clip((np.floor((f+.48*g)*3.6)+3.0) * .115, .10, .85)
            colored_fan = np.exp(-lattice*(4.4 + (1-scatter)*3)) * (.38 + .62*split)
            edge = np.exp(-(lattice + split*.26)*(17 - 6*scatter))
            energy += (.49*colored_fan + .21*edge + .10*facets) * lens
            hue += (.10 + .42*dispersion) * (f + .27*g) * lens
            white += .16 * edge * lens
        ground = .25 + .34 * self.edge + .18 * np.sin(7*a + 3*b + t + p[2])**2
        return np.minimum(energy, 1.03), .49 + hue, np.minimum(white, .34), ground

    def classic_bokeh(self, t, look, scatter, density):
        specs = bokeh_lights(look.seed)
        count = min(len(specs), max(10, round(12 + density * 15 + scatter * 12)))
        specs = specs[:count]
        colors = self.color(np.float32(.49 + (specs[:, 4] - .5) * (.43 + .70 * look.dispersion / 100)), look)
        emission = np.zeros((self.height, self.width, 3), np.float32)
        for i, (sx, sy, depth, pulse, _, phase) in enumerate(specs):
            orbit = (.007 + scatter*.060) * (1.0 + depth)
            center_x = round((.5 + sx*(.82 + scatter*.36))*self.width +
                             self.short*orbit*math.sin(t + 6.283*phase))
            center_y = round((.5 + sy*(.77 + scatter*.43))*self.height +
                             self.short*orbit*math.cos(t + 6.283*pulse))
            size = (.018 + .129 * depth**2.5) * self.short / density**.35
            radius = max(3, round(size * (1 + .075 * math.sin(t + 6.283*pulse))))
            blur = min(4, int(depth * 5))
            stamp = bokeh_stamp(radius, blur)
            distance = (stamp.shape[0] - 1) // 2
            left, top = center_x - distance, center_y - distance
            x0, x1 = max(0, left), min(self.width, center_x + distance + 1)
            y0, y1 = max(0, top), min(self.height, center_y + distance + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            optical = .07 + .35*(1-depth*.62) * (.75 + .25*math.sin(t + 6.283*phase))
            color = colors[i] * optical
            mask = stamp[y0-top:y1-top, x0-left:x1-left]
            emission[y0:y1, x0:x1] += mask[:, :, None] * color
        # A low, out-of-focus light behind the individual discs.
        veil = .29 + .52*self.edge + .12*np.sin(self.x*4+self.y*2+t)**2
        return emission, veil

