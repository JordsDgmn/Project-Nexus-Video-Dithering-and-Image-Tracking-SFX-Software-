"""Procedural light sources and an aperture-based camera for Cinematic bokeh."""

from dataclasses import dataclass
from functools import lru_cache
import math

import cv2
import numpy as np

from entropy_bokeh_animation import ANIMATION_RANGES, FADE_PATTERNS, LAYER_PATHS, LightAnimation


INDEPENDENT = "Independent lights"
MODELS = ("Camera", INDEPENDENT, "Classic")
APERTURES = ("Round", "Blades", "Ring")
LAYOUTS = ("Scattered", "Light clusters", "Light strings")
MOVEMENTS = ("Still", "Float", "Sway", "Dolly", "Handheld")
BACKDROPS = ("Black", "Solid", "Gradient", "Haze")
LENS_COLORS = {"From lights": None, "Cold blue": (.19, .57, 1.),
               "Warm gold": (1., .62, .27), "Neutral": (1., .96, .91)}
LIGHT_COLORS = {
    "Project palette": (),
    "Tungsten": ("#FF992F", "#FFC24C", "#FFE89F", "#FFCE6A", "#FFE8AD", "#6DBEFF"),
    "Festival": ("#FF4762", "#FFB839", "#FFE766", "#31EAB3", "#53A3FF", "#FB6FD1"),
    "Cool glass": ("#A4EEFF", "#5BD8FF", "#6C87F1", "#AE9DFF", "#EFF8FF"),
}
RANGES = {
    "count": (1, 96), "brightness": (0, 150), "source_size": (0, 100),
    "size_spread": (0, 100), "max_size": (2, 28), "pulse_amount": (0, 100),
    "pulse_share": (1, 100), "pulse_rate": (1, 3), "blades": (3, 11),
    "roundness": (0, 100), "aperture_angle": (-180, 180), "obstruction": (15, 80),
    "edge_softness": (0, 100), "rim": (0, 100), "onion_rings": (0, 100),
    "opening": (0, 100), "focus": (0, 100), "depth": (0, 100),
    "focus_range": (0, 100), "breathing": (0, 40), "speed": (0, 4),
    "travel_x": (0, 35), "travel_y": (0, 35), "parallax": (0, 100),
    "wander": (0, 100), "backdrop_strength": (0, 100), "far_lights": (0, 100),
    "haze": (0, 100), "squeeze": (100, 300), "cat_eye": (0, 100),
    "streaks": (0, 100), "streak_length": (5, 100), "streak_angle": (-180, 180),
    "prism": (0, 100), "fringe": (0, 100), "flare": (0, 100), "ghosts": (0, 6),
}


@dataclass(frozen=True)
class BokehSettings:
    model: str = "Camera"
    layout: str = "Light clusters"
    light_color: str = "Project palette"
    count: int = 38
    brightness: int = 82
    source_size: int = 25
    size_spread: int = 62
    max_size: int = 19
    pulse_amount: int = 0
    pulse_share: int = 20
    pulse_rate: int = 1
    aperture: str = "Round"
    blades: int = 7
    roundness: int = 24
    aperture_angle: int = 0
    obstruction: int = 40
    edge_softness: int = 26
    rim: int = 44
    onion_rings: int = 10
    opening: int = 66
    focus: int = 64
    depth: int = 87
    focus_range: int = 14
    breathing: int = 3
    movement: str = "Float"
    speed: int = 1
    travel_x: int = 8
    travel_y: int = 6
    parallax: int = 60
    wander: int = 31
    backdrop: str = "Gradient"
    backdrop_strength: int = 50
    far_lights: int = 23
    haze: int = 21
    squeeze: int = 100
    cat_eye: int = 42
    streaks: int = 20
    streak_length: int = 43
    streak_angle: int = 0
    prism: int = 8
    fringe: int = 0
    flare: int = 17
    ghosts: int = 3
    lens_color: str = "From lights"
    camera_locked: bool = True
    light_path: str = "Wander"
    light_travel_x: int = 6
    light_travel_y: int = 5
    foreground_speed: int = 130
    middle_speed: int = 75
    background_speed: int = 35
    foreground_fade: int = 100
    middle_fade: int = 85
    background_fade: int = 45
    fade_pattern: str = "Random fades"
    fade_share: int = 70
    fade_interval: int = 22
    fade_variation: int = 80
    fade_floor: int = 15
    fade_peak: int = 150
    fade_softness: int = 75
    animation_seed: int = 19

    def validate(self):
        for key, choices in (("model", MODELS), ("layout", LAYOUTS), ("light_color", LIGHT_COLORS),
                             ("aperture", APERTURES), ("movement", MOVEMENTS), ("backdrop", BACKDROPS),
                             ("lens_color", LENS_COLORS), ("light_path", LAYER_PATHS),
                             ("fade_pattern", FADE_PATTERNS)):
            if getattr(self, key) not in choices:
                raise ValueError(f"Choose a supported {key.replace('_', ' ')}.")
        if type(self.camera_locked) is not bool:
            raise ValueError("Lock camera must be on or off.")
        for key, (low, high) in (RANGES | ANIMATION_RANGES).items():
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must be {low} to {high}.")
        return self


CAMERA_RECIPES = {
    "Living lights": BokehSettings(model=INDEPENDENT, light_color="Festival", far_lights=34),
    "Cinematic camera": BokehSettings(),
    "Tungsten rings": BokehSettings(layout="Light strings", light_color="Tungsten", count=40, brightness=107,
                                    aperture="Ring", opening=76, focus=66, obstruction=45, rim=55,
                                    backdrop="Black", far_lights=17, haze=26, streaks=49, flare=43,
                                    prism=11, streak_angle=-21, source_size=33, lens_color="Cold blue"),
    "Festival lights": BokehSettings(layout="Light clusters", light_color="Festival", count=60, brightness=108,
                                     source_size=40, size_spread=78, opening=86, focus=82, rim=52,
                                     onion_rings=27, max_size=22, backdrop="Black", far_lights=13,
                                     haze=19, flare=0, streaks=0, cat_eye=56, travel_x=6, travel_y=7),
    "Prismatic anamorphic": BokehSettings(layout="Scattered", light_color="Cool glass", count=26, brightness=99,
                                           source_size=19, opening=31, focus=46, aperture="Blades", blades=6,
                                           roundness=11, squeeze=185, cat_eye=64, streaks=91, streak_length=84,
                                           streak_angle=-31, prism=100, fringe=24, flare=62, ghosts=5,
                                           backdrop="Black", far_lights=10, haze=32, movement="Sway"),
}


def smoothstep(low, high, values):
    x = np.clip((values - low) / (high - low), 0, 1)
    return x * x * (3 - 2 * x)


STAMP_RADIUS = 34
STAMP_CENTER = 51
AXIS = (np.arange(2 * STAMP_CENTER + 1, dtype=np.float32) - STAMP_CENTER) / STAMP_RADIUS


@lru_cache(maxsize=20)
def light_points(seed, layout):
    rng = np.random.default_rng(np.random.SeedSequence((seed, 5109)))
    lights = rng.random((110, 10))
    n = len(lights)
    if layout == "Light clusters":
        centers = np.array(((.23, .27), (.77, .33), (.36, .75), (.78, .77)))
        centers += rng.uniform(-.09, .09, centers.shape)
        cluster = centers[(lights[:, 9] * len(centers)).astype(int)]
        lights[:, :2] = np.clip(cluster + rng.normal(0, (.13, .14), (n, 2)), -.03, 1.03)
    elif layout == "Light strings":
        x = lights[:, 0]
        band = (lights[:, 9] > .55) * .24
        lights[:, 1] = np.clip(.76 - .58*x + .16*np.sin(x*4.6) + band + rng.normal(0, .081, n),
                              -.03, 1.03)
    return lights


@lru_cache(maxsize=64)
def aperture_stamp(kind, blades, roundness, angle, hole, softness, rim, rings):
    x, y = AXIS[None, :], AXIS[:, None]
    r = np.hypot(x, y)
    if kind == "Blades":
        sector = math.tau / blades
        theta = np.arctan2(y, x) - math.radians(angle)
        across = np.remainder(theta + sector / 2, sector) - sector / 2
        polygon = math.cos(sector / 2) / np.cos(across)
        r = r / (polygon + (1 - polygon) * (roundness / 100))
    edge = .017 + .0032 * softness
    mask = 1 - smoothstep(1-edge, 1+edge, r)
    if kind == "Ring":
        center = 1 - smoothstep(hole / 100 - edge*.48, hole / 100 + edge*.48, r)
        mask = mask * (1 - .97 * center)
    profile = .66 + (rim / 100) * .67 * np.exp(-((r - .92) / (.066 + edge*.32))**2)
    if rings:
        profile = profile * (1 + rings/100 * .26 * np.cos(r*56 + 1.5*np.sin(r*27)) * np.minimum(r*3, 1))
    return np.float32(mask * profile)


@lru_cache(maxsize=16)
def streak_stamp(prism):
    """A narrow core with soft spill and color separation along the optical axis."""
    u, v = AXIS[None, :], AXIS[:, None]
    shape = np.exp(-(abs(u)*2.65)**1.6 - (v*.95)**2) * (1 - smoothstep(1.04, 1.47, abs(u)))
    broad = np.exp(-(abs(u)*2.0)**2 - (v*.62)**2)
    spectrum = np.array(((.20, .04, .58), (.07, .31, 1.), (.04, .92, .97), (.22, 1., .29),
                         (1., .89, .12), (1., .36, .06), (.88, .08, .17)), dtype=np.float32)
    palette = np.column_stack([
        np.interp(AXIS, np.linspace(-.83, .83, len(spectrum)), spectrum[:, channel])
        for channel in range(3)
    ]).astype(np.float32)
    rainbow = np.float32(prism / 100)
    color = (1 - rainbow) + rainbow * palette
    return np.float32((shape + .21*broad)[:, :, None] * color[None, :, :])


@lru_cache(maxsize=32)
def fringe_stamp(kind, blades, roundness, angle, hole, softness, rim, rings, fringe):
    grey = aperture_stamp(kind, blades, roundness, angle, hole, softness, rim, rings)
    size = grey.shape[::-1]
    shift = fringe * .046
    red = cv2.warpAffine(grey, np.float32(((1, 0, shift), (0, 1, 0))), size)
    blue = cv2.warpAffine(grey, np.float32(((1, 0, -shift), (0, 1, 0))), size)
    return cv2.merge((red, grey, blue))


def light_pulse(index, selector, offset, seed, settings, seconds):
    if not settings.pulse_amount or selector >= settings.pulse_share / 100:
        return 0.
    tick = seconds * settings.pulse_rate
    slot = math.floor(tick)
    # Only a seeded subset of eligible lamps fires in a slot. Pulses taper to zero within it.
    key = (seed + (index + 1) * 374761393 + slot * 668265263) & 0xffffffff
    key = ((key ^ (key >> 13)) * 1274126177) & 0xffffffff
    if (key ^ (key >> 16)) % 11 > 4:
        return 0.
    center = .35 + .31 * offset
    width = .115 + .13 * selector
    peak = max(0., 1 - abs(tick - slot - center) / width)
    return settings.pulse_amount / 100 * peak * peak * (3 - 2 * peak)


def move_light(settings, t, dx, dy, depth, phase, *, independent=False):
    movement = settings.movement
    if movement == "Still" or not settings.speed or independent and settings.camera_locked:
        return 0., 0., 1.
    varying = .55 + phase * .45
    weight = 1 - settings.parallax / 100 * depth * .84
    wave = t * settings.speed
    if movement == "Dolly":
        dolly = math.sin(wave) * weight
        return dx * dolly, dy * dolly, 1 + .14 * dolly
    if movement == "Sway":
        cx, cy = math.sin(wave), .40 * math.sin(wave*2 + .3)
    elif movement == "Handheld":
        cx = .64 * math.sin(wave) + .23 * math.sin(3*wave+.9) + .13*math.sin(5*wave)
        cy = .72 * math.cos(wave+.6) + .18 * math.cos(2*wave) + .10*math.sin(4*wave)
    else:
        cx, cy = math.sin(wave), math.cos(wave)
    drift = 0. if independent else settings.wander / 100 * varying
    cx = (1 - drift) * cx + drift * math.sin(wave + phase * math.tau)
    cy = (1 - drift) * cy + drift * math.cos(wave + phase * math.tau)
    return cx * weight, cy * weight, 1.


class BokehCamera:
    def __init__(self, size):
        self.size = size
        self.width, self.height = size
        self.short = min(size)
        self.x = np.linspace(-1, 1, self.width, dtype=np.float32)[None, :]
        self.y = np.linspace(-1, 1, self.height, dtype=np.float32)[:, None]
        self.edges = np.float32(np.clip(1 - .55*(self.x**2 + self.y**2), 0, 1))

    def blit(self, image, stamp, cx, cy, matrix, color):
        extents = (STAMP_CENTER / STAMP_RADIUS) * np.abs(matrix).sum(axis=1)
        left = max(0, math.floor(cx - extents[0]))
        top = max(0, math.floor(cy - extents[1]))
        right = min(self.width, math.ceil(cx + extents[0]) + 1)
        bottom = min(self.height, math.ceil(cy + extents[1]) + 1)
        if right <= left or bottom <= top:
            return
        corners = matrix / STAMP_RADIUS
        origin = np.array((cx-left, cy-top)) - corners.sum(axis=1) * STAMP_CENTER
        transform = np.column_stack((corners, origin))
        spot = cv2.warpAffine(stamp, transform, (right-left, bottom-top), flags=cv2.INTER_LINEAR)
        if spot.ndim == 2:
            light = cv2.transform(spot, np.float32(color).reshape(3, 1))
        else:
            light = cv2.multiply(spot, (*map(float, color), 0))
        region = image[top:bottom, left:right]
        cv2.add(region, light, dst=region)

    def lens_matrix(self, radius, settings, position_x, position_y):
        nx = 2*position_x / self.width - 1
        ny = 2*position_y / self.height - 1
        squeeze = settings.squeeze / 100
        edge = min(1., math.hypot(nx, ny) / 1.28)
        # Off-axis clipping compresses the pupil in its radial direction. Keep the tangential
        # axis long, as with cat-eye highlights near the sides of a real lens.
        theta = math.atan2(ny*self.height, nx*self.width)
        c, s = math.cos(theta), math.sin(theta)
        clip = .66 * settings.cat_eye / 100 * edge**1.45
        return radius * np.array(((1-clip*c*c, -clip*c*s*squeeze),
                                   (-clip*c*s, (1-clip*s*s)*squeeze))), 1 - .50*clip

    def bulb(self, image, settings, point, color, t, seconds, seed, index, animation, progress, far=False):
        x, y, d, flux, _, phase, extent, pulse, offset, _ = point
        depth = 1.35 if far else .5 + (d - .5) * settings.depth / 100
        wave = t*settings.speed
        focus = settings.focus / 100
        if settings.movement != "Still" and (animation is None or not settings.camera_locked):
            focus += settings.breathing / 100 * math.sin(wave) * .46
        focus = min(1., max(0., focus))
        # Thin-lens inspired circle of confusion: blur grows with distance in diopters
        # from the focus plane and with the opening. A finite source gives a minimum disc.
        focal_delta = abs(1 / (.56 + 2.2*depth) - 1 / (.56 + 2.2*focus))
        defocus = max(0., focal_delta - .0025 * settings.focus_range)
        source = .004 + settings.source_size * .00026
        spread = (1 - settings.size_spread / 100) + settings.size_spread / 100 * (.35 + extent*1.46)
        radius = source * spread + (.035 + .0023 * settings.opening) * defocus
        if far:
            radius = max(.022, radius) * (1.1 + extent*.5)
        dx, dy, zoom = move_light(settings, t, x*2-1, y*2-1, depth if not far else 1., phase,
                                  independent=animation is not None)
        local_x, local_y = 0., 0.
        layer = 2 if far else min(2, int(d*3))
        if animation is not None:
            local_x, local_y = animation.drift(index, layer, progress)
        cx = (x + dx*settings.travel_x*.01 + local_x) * self.width
        cy = (y + dy*settings.travel_y*.01 + local_y) * self.height
        radius = self.short * min(settings.max_size/100, radius * zoom)
        radius = max(1.4, radius)
        matrix, visibility = self.lens_matrix(radius, settings, cx, cy)
        blur = min(100, settings.edge_softness + (46 if far else round(min(5, defocus*7)) * 3))
        kind = "Round" if far else settings.aperture
        aperture = (kind, settings.blades, settings.roundness, settings.aperture_angle,
                    settings.obstruction, blur, settings.rim, settings.onion_rings)
        stamp = fringe_stamp(*aperture, settings.fringe) if settings.fringe and not far else aperture_stamp(*aperture)
        # Defocus spreads each emitter's energy over a larger area. Bound the falloff so a
        # very bright sign can still make a large, readable disc.
        energy = (.25 + 1.40*flux**2.4) * (1.2 - .49*min(depth, 1.)) * visibility
        energy *= settings.brightness / 100 * (.23 + .77 / (1 + 9.3 * defocus**1.6))
        if far:
            energy *= .23 * settings.far_lights / 100
        else:
            energy *= 1 + .94 * light_pulse(index, pulse, offset, seed, settings, seconds)
        if animation is not None:
            energy *= animation.gain(index, layer, x, progress)
        color = np.float32(color * .9 + .10) * energy
        self.blit(image, stamp, cx, cy, matrix, color)
        return cx, cy, radius, energy, color

    def optics(self, image, settings, bulbs, points):
        if not bulbs or not (settings.streaks or settings.flare):
            return
        # Keep the identities of the main lens sources stable during a take, including while
        # individual lights pulse or pass in and out of focus.
        focus = settings.focus / 100
        ranks = sorted(range(len(bulbs)), key=lambda i: points[i, 3] / (1 + abs(points[i, 2]-focus)),
                       reverse=True)
        strongest = bulbs[ranks[0]]
        tint = LENS_COLORS[settings.lens_color]
        if tint is not None:
            tint = np.float32(tint)
        if settings.streaks:
            angle = math.radians(settings.streak_angle)
            axis = np.array(((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle))))
            stamp = streak_stamp(settings.prism)
            for index in ranks[:5]:
                cx, cy, radius, energy, color = bulbs[index]
                if energy <= 0:
                    continue
                variation = .66 + .38*points[index, 6]
                length = self.short * (.07 + .0051*settings.streak_length) * variation * min(1.25, .68+energy)
                width = max(1.35, radius * .32)
                strength = .77 * settings.streaks / 100 * min(1, energy*2.7)
                if tint is not None:
                    color = .20*color + .80*energy*tint
                if settings.prism:
                    color = .62*color + .38*energy
                self.blit(image, stamp, cx, cy, axis * (length, width), color * strength)
        if settings.flare:
            cx, cy, radius, energy, color = strongest
            if tint is not None:
                color = .28*color + .72*energy*tint
            gain = settings.flare / 100
            center_x, center_y = self.width/2, self.height/2
            reflection = aperture_stamp("Round", 7, 0, 0, 40, 78, 18, 0)
            glow = aperture_stamp("Round", 7, 0, 0, 40, 100, 0, 0)
            size = max(radius*2.2, self.short*.056)
            self.blit(image, glow, cx, cy, np.eye(2)*size, color*.19*gain)
            for i in range(settings.ghosts):
                factor = .56 - i*.37
                gx = center_x + (cx-center_x)*factor
                gy = center_y + (cy-center_y)*factor
                size = self.short * (.027 + .018*(i % 3))
                reflection_color = np.roll(color, i % 2 + 1)
                self.blit(image, reflection, gx, gy, np.eye(2)*size, reflection_color * gain*.22/(1 + .43*i))

    def render(self, settings, look, t, progress, duration, seamless, colors):
        seconds = progress * duration
        animation = LightAnimation(settings, duration, seamless) if settings.model == INDEPENDENT else None
        lights = light_points(look.seed, settings.layout)
        count = settings.count
        spread = .44 + .75 * look.scatter / 100
        points = lights.copy()
        points[:, :2] = .5 + (points[:, :2] - .5) * spread
        points[:, 6] *= .76 + .50 * look.compact / 100
        image = np.zeros((self.height, self.width, 3), dtype=np.float32)
        if settings.far_lights:
            for index in range(96, len(points)):
                self.bulb(image, settings, points[index], colors[index], t, seconds, look.seed,
                          index, animation, progress, far=True)
        bulbs = [self.bulb(image, settings, points[i], colors[i], t, seconds, look.seed, i, animation, progress)
                 for i in range(count)]
        self.optics(image, settings, bulbs, points)
        haze = settings.haze / 100
        if settings.backdrop == "Haze":
            haze = min(1., haze + .4 * settings.backdrop_strength/100)
        if haze:
            small = cv2.resize(image, (max(2, self.width//10), max(2, self.height//10)),
                               interpolation=cv2.INTER_AREA)
            small = cv2.GaussianBlur(small, (0, 0), max(1., min(small.shape[:2])*.12))
            image += cv2.resize(small, self.size, interpolation=cv2.INTER_LINEAR) * (.36 + 1.5*haze) * haze
        image = image / (1 + .60 * np.max(image, axis=2, keepdims=True))
        strength = settings.backdrop_strength / 100
        if settings.backdrop == "Black":
            ground = np.zeros_like(self.edges)
        elif settings.backdrop == "Solid":
            ground = np.full_like(self.edges, strength)
        else:
            ground = strength * (.23 + .49*self.edges + .23*(1 - self.y)*.5)
        return image, ground
