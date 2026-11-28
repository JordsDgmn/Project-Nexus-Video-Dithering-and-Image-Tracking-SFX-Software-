"""Loop-safe image treatments shared by preview and export."""

from dataclasses import dataclass
from functools import lru_cache
import math

import cv2
import numpy as np


PRINT_STYLES = ("Dots", "Lines", "Crosshatch")


@dataclass(frozen=True)
class Texture:
    grain: int = 0
    grain_size: int = 3
    colored_grain: bool = False
    distort: int = 0
    distort_scale: int = 38
    ripple: int = 0
    ripple_count: int = 7
    tatter: int = 0
    edge_width: int = 9
    roughness: int = 60
    halftone: int = 0
    cell_size: int = 10
    angle: int = 30
    print_style: str = "Dots"
    chromatic: int = 0
    posterize: int = 0
    levels: int = 8
    vignette: int = 0
    enabled: bool = True
    paper: int = 0
    fiber_size: int = 35
    scratches: int = 0
    scratch_count: int = 13
    scanlines: int = 0
    line_spacing: int = 7

    def validate(self):
        for key, low, high in (
            ("grain", 0, 100), ("grain_size", 1, 12), ("distort", 0, 100),
            ("distort_scale", 1, 100), ("ripple", 0, 100), ("ripple_count", 1, 24),
            ("tatter", 0, 100), ("edge_width", 2, 30), ("roughness", 0, 100),
            ("halftone", 0, 100), ("cell_size", 3, 36), ("angle", 0, 180),
            ("chromatic", 0, 100), ("posterize", 0, 100), ("levels", 2, 32),
            ("vignette", 0, 100), ("paper", 0, 100), ("fiber_size", 1, 100),
            ("scratches", 0, 100), ("scratch_count", 1, 40),
            ("scanlines", 0, 100), ("line_spacing", 2, 24),
        ):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must be {low} to {high}.")
        if self.print_style not in PRINT_STYLES or type(self.colored_grain) is not bool or type(self.enabled) is not bool:
            raise ValueError("Unknown print or grain setting.")
        return self

    @property
    def active(self):
        return self.enabled and any((self.grain, self.distort, self.ripple, self.tatter, self.halftone,
                    self.chromatic, self.posterize, self.vignette,
                    self.paper, self.scratches, self.scanlines))


@lru_cache(maxsize=18)
def noise_tile(seed, index, colored):
    generator = np.random.default_rng(np.random.SeedSequence((seed, index, 6503)))
    shape = (192, 192, 3) if colored else (192, 192)
    return generator.normal(0, 1, shape).astype(np.float32)


@lru_cache(maxsize=16)
def posterize_lut(levels):
    return np.rint(np.rint(np.arange(256) * ((levels - 1) / 255))
                   * (255 / (levels - 1))).astype(np.uint8)


@lru_cache(maxsize=12)
def scratch_points(seed):
    return np.random.default_rng(seed ^ 81523).random((40, 6))


class TextureStack:
    def __init__(self, size):
        self.width, self.height = size
        self.short = min(size)
        self.x = np.arange(self.width, dtype=np.float32)[None, :]
        self.y = np.arange(self.height, dtype=np.float32)[:, None]
        self.u = (self.x - (self.width - 1) * .5) / self.short
        self.v = (self.y - (self.height - 1) * .5) / self.short
        self.radius = None
        self.print_key = None
        self.print_dist = None
        self.edge_key = None
        self.edge_traces = None
        self.vignette_mask = None
        self.paper_key = None
        self.paper_field = None

    def apply(self, frame, config, phase, seed, background):
        t = math.tau * phase
        if config.distort or config.ripple:
            frame = self.warp(frame, config, t, seed)
        if config.chromatic:
            offset = max(1, round(self.short * .026 * config.chromatic / 100))
            shifted = frame.copy()
            shifted[:, offset:, 0] = frame[:, :-offset, 0]
            shifted[:, :-offset, 2] = frame[:, offset:, 2]
            shifted[:, :offset, 0] = frame[:, :1, 0]
            shifted[:, -offset:, 2] = frame[:, -1:, 2]
            frame = cv2.addWeighted(frame, 1 - config.chromatic / 100, shifted, config.chromatic / 100, 0)
        if config.posterize:
            amount = config.posterize / 100
            frame = cv2.addWeighted(frame, 1 - amount, cv2.LUT(frame, posterize_lut(config.levels)), amount, 0)
        if config.halftone:
            frame = self.print_screen(frame, config)
        if config.vignette:
            if self.vignette_mask is None:
                radius = (self.u * self.short / self.width * 2) ** 2 + (self.v * self.short / self.height * 2) ** 2
                self.vignette_mask = np.clip((radius - .07) / 1.24, 0, 1)
            frame = np.uint8(np.rint(frame * (1 - .87 * config.vignette / 100 * self.vignette_mask[:, :, None])))
        if config.paper or config.scratches or config.scanlines:
            frame = self.surface(frame, config, t, seed)
        if config.grain:
            frame = self.add_grain(frame, config, phase, seed)
        if config.tatter:
            frame = self.torn_edges(frame, config, background, seed)
        return frame

    def surface(self, frame, config, t, seed):
        if config.paper:
            key = config.fiber_size, seed
            if key != self.paper_key:
                # Two scales make fiber and mottling independently visible in the same paper.
                scale = .024 + config.fiber_size * .0018
                fine_w, fine_h = (max(4, round(side * scale)) for side in (self.width, self.height))
                rng = np.random.default_rng(seed ^ 35903)
                fiber = rng.normal(0, 1, (fine_h, fine_w)).astype(np.float32)
                fiber = cv2.GaussianBlur(fiber, (0, 0), .56, sigmaY=1.5)
                mottle = rng.normal(0, 1, (max(3, fine_h//5), max(3, fine_w//5))).astype(np.float32)
                size = (self.width, self.height)
                self.paper_field = (cv2.resize(fiber, size, interpolation=cv2.INTER_LINEAR) * .82
                                    + cv2.resize(mottle, size, interpolation=cv2.INTER_CUBIC) * .14)
                self.paper_key = key
            # Keep the color of the underlying highlights while picking up darker fibers.
            frame = np.uint8(np.clip(frame + self.paper_field[:, :, None] * (.72 * config.paper), 0, 255))
        if config.scanlines:
            pitch = max(2.0, config.line_spacing * self.short / 540)
            alpha = .68 * config.scanlines / 100
            mask = (1 - alpha * (.5 + .5*np.cos(self.y * (math.tau / pitch)))**3).astype(np.float32)
            frame = np.uint8(np.rint(frame * mask[:, :, None]))
        if config.scratches:
            mask = np.zeros((self.height, self.width), dtype=np.uint8)
            for x, y, length, tilt, opacity, phase in scratch_points(seed)[:config.scratch_count]:
                wobble = t + phase * math.tau
                cx = round(x * self.width + .012 * self.short * math.sin(wobble))
                cy = round(y * self.height)
                end = (cx + round((tilt - .5) * self.short * .032),
                       cy + round(self.short * (.045 + .43 * length)))
                shine = (.32 + .68 * math.cos(wobble)**4) * (.35 + opacity * .65)
                color = round(1.33 * config.scratches * shine)
                cv2.line(mask, (cx, cy), end, color, max(1, round(self.short/650)), cv2.LINE_AA)
            frame = cv2.add(frame, cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB))
        return frame

    def warp(self, frame, config, t, seed):
        dx, dy = np.zeros_like(self.u + self.v), np.zeros_like(self.u + self.v)
        if config.distort:
            scale = 2 + 22 * config.distort_scale / 100
            bias = (seed % 729) * .039
            strength = .14 * self.short * config.distort / 100
            dx += strength * (.72 * np.sin(self.v * scale + .8*np.cos(self.u * scale*.7 + t) + bias - t)
                              + .28 * np.sin((self.u + self.v) * scale * 1.7 + bias + 2*t))
            dy += strength * (.72 * np.cos(self.u * scale + .7*np.sin(self.v * scale*.9 - t) + bias + t)
                              + .28 * np.cos((self.u - self.v) * scale * 1.6 + bias + 2*t))
        if config.ripple:
            if self.radius is None:
                self.radius = np.hypot(self.u, self.v)
            rad = self.radius
            wave = np.sin(rad * math.tau * config.ripple_count - 2*t) * np.exp(-.75*rad)
            wave *= (.088 * self.short * config.ripple / 100) / np.maximum(.12, rad)
            dx += self.u * wave
            dy += self.v * wave
        return cv2.remap(frame, self.x + dx, self.y + dy, cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REFLECT_101)

    def add_grain(self, frame, config, phase, seed):
        moment = phase * 24
        tick = math.floor(moment)
        amount = moment - tick
        amount = amount * amount * (3 - 2 * amount)
        a = noise_tile(seed, tick % 24, config.colored_grain)
        b = noise_tile(seed, (tick + 1) % 24, config.colored_grain)
        tile = cv2.addWeighted(a, 1 - amount, b, amount, 0) if amount else a
        grain_size = max(1.0, config.grain_size * self.short / 540)
        work_w = max(2, round(self.width / grain_size))
        work_h = max(2, round(self.height / grain_size))
        # Tile at the selected scale, rather than stretching the same 192 samples at every setting.
        tiles = np.tile(tile, (math.ceil(work_h / 192), math.ceil(work_w / 192))
                        + ((1,) if config.colored_grain else ()))[:work_h, :work_w]
        field = cv2.resize(tiles, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        if field.ndim == 2:
            field = field[:, :, None]
        return np.uint8(np.clip(frame + field * (.39 * config.grain), 0, 255))

    def print_screen(self, frame, config):
        key = config.cell_size, config.angle, config.print_style
        if self.print_key != key:
            self.print_key = key
            pitch = max(2.1, config.cell_size * self.short / 540)
            turn = math.radians(config.angle)
            a = (self.u * math.cos(turn) + self.v * math.sin(turn)) * (self.short / pitch)
            b = (-self.u * math.sin(turn) + self.v * math.cos(turn)) * (self.short / pitch)
            x = np.abs((a + .5) % 1 - .5)
            y = np.abs((b + .5) % 1 - .5)
            self.print_dist = (np.hypot(x, y) if config.print_style == "Dots" else
                               y if config.print_style == "Lines" else np.minimum(x, y))
        # Build ink density from the local brightness, so the pattern responds to the light.
        light = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32) * (1 / 255)
        radius = .064 + .34 * (1 - light) ** .68
        mask = np.clip((radius - self.print_dist) * 9 + .35, 0, 1)
        ink = 1 - mask[:, :, None] * (.88 * config.halftone / 100)
        return np.uint8(np.rint(frame * ink))

    def torn_edges(self, frame, config, background, seed):
        key = config.edge_width, config.roughness, seed
        if self.edge_key != key:
            self.edge_key = key
            band = config.edge_width / 100
            rough = config.roughness / 100
            generator = np.random.default_rng(seed ^ 314159)
            traces = []
            for extent in (self.height, self.height, self.width, self.width):
                locations = np.linspace(0, 1, extent, dtype=np.float32)
                detail = np.zeros(extent, dtype=np.float32)
                for count, weight in ((7, .51), (31, .31), (113, .18)):
                    profile = generator.uniform(-1, 1, count).astype(np.float32)
                    detail += weight * np.interp(locations, np.linspace(0, 1, count), profile)
                traces.append((band * (.65 + rough * detail)) * self.short)
            self.edge_traces = traces
        left, right, top, bottom = self.edge_traces
        depth = np.minimum(self.x - left[:, None], self.width - 1 - self.x - right[:, None])
        depth = np.minimum(depth, np.minimum(self.y - top[None, :],
                                             self.height - 1 - self.y - bottom[None, :]))
        feather = max(1.7, self.short * .004)
        alpha = np.clip(.5 - depth / feather, 0, 1)[:, :, None] * (config.tatter / 100)
        return np.uint8(np.rint(frame * (1 - alpha) + background * alpha))
