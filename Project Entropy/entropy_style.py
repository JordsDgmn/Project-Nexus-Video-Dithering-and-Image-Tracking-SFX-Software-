"""Looping form, particles, lens accents and exposure treatments."""

from dataclasses import dataclass
from functools import lru_cache
import math

import cv2
import numpy as np


FORMS = ("Flow", "Ribbons", "Vortex", "Radial", "Facets")
LENS_TINTS = {
    "Pearl": (1., .93, .85), "Warm": (1., .63, .37),
    "Ice": (.52, .83, 1.), "Lilac": (.82, .63, 1.),
}
PULSES = ("Soft", "Shutter")


@dataclass(frozen=True)
class Style:
    enabled: bool = True
    form: str = "Flow"
    bend: int = 0
    fluidity: int = 52
    stretch_x: int = 0
    stretch_y: int = 0
    turbulence: int = 0
    detail: int = 45
    flow_speed: int = 1
    seed: int = 19
    specks: int = 0
    glimmer: int = 0
    glitter: int = 0
    density: int = 75
    particle_size: int = 40
    drift: int = 35
    twinkle_cycles: int = 1
    particle_tint: str = "Pearl"
    flare: int = 0
    flare_size: int = 37
    flare_x: int = 32
    flare_y: int = 28
    flare_angle: int = 0
    streaks: int = 43
    ghosts: int = 3
    tint: str = "Pearl"
    strobe: int = 0
    pulse_rate: int = 1
    pulse_width: int = 38
    pulse_shape: str = "Soft"

    def validate(self):
        if (type(self.enabled) is not bool or self.form not in FORMS
                or self.tint not in LENS_TINTS or self.particle_tint not in LENS_TINTS
                or self.pulse_shape not in PULSES):
            raise ValueError("Choose a supported style, lens tint, and pulse shape.")
        for key, low, high in (
            ("bend", 0, 100), ("fluidity", 0, 100), ("stretch_x", -60, 100),
            ("stretch_y", -60, 100), ("turbulence", 0, 100), ("detail", 0, 100),
            ("flow_speed", 0, 4), ("seed", 0, 999999), ("specks", 0, 100),
            ("glimmer", 0, 100), ("glitter", 0, 100), ("density", 1, 240),
            ("particle_size", 0, 100), ("drift", 0, 100), ("twinkle_cycles", 0, 6), ("flare", 0, 100),
            ("flare_size", 0, 100), ("flare_x", 0, 100), ("flare_y", 0, 100),
            ("flare_angle", -180, 180), ("streaks", 0, 100), ("ghosts", 0, 8),
            ("strobe", 0, 100), ("pulse_rate", 1, 3), ("pulse_width", 10, 85),
        ):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must be {low} to {high}.")
        return self

    @property
    def has_form(self):
        return any((self.bend, self.stretch_x, self.stretch_y, self.turbulence))

    @property
    def has_particles(self):
        return any((self.specks, self.glimmer, self.glitter))

    @property
    def has_layers(self):
        return self.enabled and (self.has_form or self.has_particles or self.flare)


@lru_cache(maxsize=12)
def seeded_points(seed):
    return np.random.default_rng(seed + 7207).random((240, 8), dtype=np.float32)


class StyleStack:
    def __init__(self, size):
        self.width, self.height = size
        self.short = min(size)
        scale = min(1, 480 / max(size))
        self.small = tuple(max(2, round(side * scale)) for side in size)
        w, h = self.small
        self.x = ((np.arange(w, dtype=np.float32)[None, :] + .5) / w - .5) * (self.width / self.short)
        self.y = ((np.arange(h, dtype=np.float32)[:, None] + .5) / h - .5) * (self.height / self.short)
        self.px = np.arange(self.width, dtype=np.float32)[None, :]
        self.py = np.arange(self.height, dtype=np.float32)[:, None]
        self.lens_key = None
        self.lens_layer = None

    def form(self, frame, style, t):
        x, y = self.x, self.y
        amount = style.bend / 100
        bias = (style.seed % 10007) * .021
        wave = t * style.flow_speed
        flow = style.fluidity / 100
        dx = x * (2 ** (-style.stretch_x / 75) - 1)
        dy = y * (2 ** (-style.stretch_y / 75) - 1)
        if amount and style.form == "Vortex":
            twist = amount * (4.4 + 1.2 * flow * math.cos(wave + bias)) * np.exp(-4.1 * (x*x + y*y))
            dx = dx + x * (np.cos(twist) - 1) - y * np.sin(twist)
            dy = dy + y * (np.cos(twist) - 1) + x * np.sin(twist)
        elif amount and style.form == "Radial":
            radius = np.hypot(x, y)
            ripple = amount * .35 * np.cos(radius * (11 + 11 * flow) - wave + bias) / (1 + 1.5 * radius)
            dx = dx + x * ripple
            dy = dy + y * ripple
        elif amount and style.form == "Facets":
            # Oblique folds act on large planes before optional smaller-scale turbulence.
            a = np.arcsin(np.sin((x + .58*y) * 13 + (.18 + .9 * flow)*math.sin(wave) + bias))
            b = np.arcsin(np.sin((y - .67*x) * 11 + (.18 + .9 * flow)*math.cos(wave) - bias))
            dx = dx + .11 * amount * (a + .37*b)
            dy = dy + .11 * amount * (b - .3*a)
        elif amount and style.form == "Ribbons":
            dx = dx + .27 * amount * np.sin(y * (8 + flow*8) + .9*np.cos(x*4 + wave) + bias)
            dy = dy + .063 * amount * np.sin(x*9 - wave * 2 + bias)
        elif amount:
            dx = dx + .24 * amount * np.sin(y*8 + flow * 2.2*np.cos(x*5 + wave + bias))
            dy = dy + .22 * amount * np.cos(x*7 + flow * 2.2*np.sin(y*4 - wave + bias))

        if style.turbulence:
            strength = style.turbulence * .0019
            for octave, weight in enumerate((1., .18 + style.detail*.0048, .04 + style.detail*.0032)):
                f = 8 * 2.1**octave
                p = bias + octave * 2.3
                dx = dx + strength * weight * np.sin(y*f + x*f*.31 + p + (octave+1)*wave)
                dy = dy + strength * weight * np.cos(x*f - y*f*.37 - p - (octave+1)*wave)

        size = (self.width, self.height)
        dx, dy = np.broadcast_arrays(dx, dy)
        map_x = self.px + self.short * cv2.resize(dx, size, interpolation=cv2.INTER_LINEAR)
        map_y = self.py + self.short * cv2.resize(dy, size, interpolation=cv2.INTER_LINEAR)
        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    def lights(self, frame, style, t):
        size = (self.width, self.height)
        if style.flare:
            key = (style.flare_size, style.flare_x, style.flare_y, style.flare_angle,
                   style.streaks, style.ghosts, style.tint)
            if key != self.lens_key:
                self.lens_layer = cv2.resize(self.flare(style), size, interpolation=cv2.INTER_LINEAR)
                self.lens_key = key
            frame = cv2.addWeighted(frame, 1, self.lens_layer, style.flare / 100, 0)
        if style.has_particles:
            particles = cv2.resize(self.particles(style, t), size, interpolation=cv2.INTER_LINEAR)
            frame = cv2.add(frame, particles)
        return frame

    def particles(self, style, t):
        width, height = self.small
        short = min(self.small)
        sparks = np.zeros((height, width, 3), np.uint8)
        haze = np.zeros_like(sparks)
        drift = short * .0013 * style.drift
        unit = short * (.0014 + .000074 * style.particle_size)
        tint = LENS_TINTS[style.particle_tint]
        twinkle = t * style.twinkle_cycles

        # Continuous motion and brightness, with persistent point IDs and no per-frame random draws.
        for x, y, scale, phase, amplitude, member, angle, bias in seeded_points(style.seed)[:style.density]:
            angle *= math.tau
            phase *= math.tau
            wobble = t + phase
            cx = round(x * (width-1) + drift * (.3 + .7 * amplitude) * math.sin(wobble))
            cy = round(y * (height-1) + drift * (.3 + .7 * amplitude) * math.cos(wobble + angle))
            center = (cx, cy)
            radius = max(1, round(unit * (.35 + scale * 1.25)))
            beat = .5 + .5 * math.cos((twinkle + phase) * (1 + int(bias * 3)))
            dot = .46 * style.specks * (.55 + .45 * amplitude)
            glow = 1.13 * style.glimmer * beat**3 if member < .55 else 0
            star = 2.2 * style.glitter * beat**7 if member < .36 else 0
            if glow > 1:
                cv2.circle(haze, center, radius * 2, tuple(int(glow*c) for c in tint), -1, cv2.LINE_AA)
            if dot + glow > 1:
                cv2.circle(sparks, center, radius, tuple(int(min(255, (dot+glow)*c)) for c in tint),
                           -1, cv2.LINE_AA)
            if star > 2:
                length = max(2, round(radius * (2 + 2 * beat)))
                color = tuple(int(star*c) for c in tint)
                for axis, reach in ((angle, length), (angle + math.pi/2, max(1, length//2))):
                    h, v = round(math.cos(axis) * reach), round(math.sin(axis) * reach)
                    cv2.line(sparks, (cx-h, cy-v), (cx+h, cy+v), color, 1, cv2.LINE_AA)
                cv2.circle(haze, center, radius * 2, color, -1, cv2.LINE_AA)
        if style.glimmer or style.glitter:
            haze = cv2.GaussianBlur(haze, (0, 0), max(.8, unit*1.9))
            return cv2.add(sparks, haze)
        return sparks

    def flare(self, style):
        center_x = (style.flare_x / 100 - .5) * self.width / self.short
        center_y = (style.flare_y / 100 - .5) * self.height / self.short
        x, y = self.x - center_x, self.y - center_y
        radius = np.hypot(x, y)
        size = .024 + .0028 * style.flare_size
        core = .90 * np.exp(-radius**2 / (size * .125)**2)
        halo = .34 * np.exp(-radius / size) + .105 * np.exp(-((radius/size - .74) * 10)**2)
        angle = math.radians(style.flare_angle)
        u = x * math.cos(angle) + y * math.sin(angle)
        v = -x * math.sin(angle) + y * math.cos(angle)
        rays = (.59 * np.exp(-abs(u)/(size*3.2) - (v/(size*.048))**2)
                + .25 * np.exp(-abs(v)/(size*1.2) - (u/(size*.039))**2))
        tint = np.float32(LENS_TINTS[style.tint])
        layer = (core + halo + rays * style.streaks/100)[:, :, None] * tint
        for index in range(style.ghosts):
            f = .61 - .28 * index
            # At the optical center, keep a halo rather than stacking all ghosts on the glare core.
            if abs(center_x) + abs(center_y) < .03:
                break
            r = np.hypot(self.x - f * center_x, self.y - f * center_y)
            ring_size = size * (.34 + .14 * (index % 3))
            ring = (.16 * np.exp(-((r/ring_size-1)*9)**2) + .09*np.exp(-(r/ring_size)**2))
            color = np.roll(tint, 1 + index % 2)
            layer += ring[:, :, None] * color * (.85 ** index)
        return np.uint8(np.clip(layer * 255, 0, 255))


def pulse_exposure(frame, style, seconds):
    # Integer rates keep clip starts aligned when the duration is a whole number of seconds.
    cycle = (seconds * style.pulse_rate) % 1
    distance = abs(cycle - .5)
    envelope = max(0., 1 - distance / (style.pulse_width / 200))
    if style.pulse_shape == "Soft":
        envelope = envelope * envelope * (3 - 2 * envelope)
    else:
        envelope = min(1., envelope * 3.5)
    boost = envelope * style.strobe / 100
    return cv2.convertScaleAbs(frame, alpha=1 + .59 * boost, beta=24 * boost) if boost else frame
