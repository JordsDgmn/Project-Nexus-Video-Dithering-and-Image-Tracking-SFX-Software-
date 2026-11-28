"""Deterministic per-light animation with independent clocks for each depth layer."""

from functools import lru_cache
import math

import numpy as np


LAYER_PATHS = ("Still", "Float", "Orbit", "Sway", "Wander")
FADE_PATTERNS = ("Off", "Random fades", "Swell", "Sparks", "Rolling wave")
DRIFT_RATES = ("foreground_speed", "middle_speed", "background_speed")
FADE_RATES = ("foreground_fade", "middle_fade", "background_fade")
ANIMATION_RANGES = {
    **dict.fromkeys((*DRIFT_RATES, *FADE_RATES), (0, 300)),
    "light_travel_x": (0, 25), "light_travel_y": (0, 25),
    "fade_share": (0, 100), "fade_interval": (5, 160), "fade_variation": (0, 100),
    "fade_floor": (0, 100), "fade_peak": (100, 200), "fade_softness": (0, 100),
    "animation_seed": (0, 999999),
}


@lru_cache(maxsize=20)
def drivers(seed):
    return np.random.default_rng(np.random.SeedSequence((seed, 6283))).random((110, 6))


def cycle_count(requested, seamless):
    if requested and seamless:
        return max(1, math.floor(requested + .5))
    return requested


def hash_event(seed, index, event):
    value = ((index+1)*374761393 + event*668265263 + seed*725357) & 0xffffffff
    value = ((value ^ (value >> 13)) * 1274126177) & 0xffffffff
    return value ^ (value >> 16)


def fade_event(seed, index, slot, repeat, variation):
    event = hash_event(seed, index, slot if repeat is None else slot % repeat)
    jitter = (event & 65535) / 65535
    level = smooth(((event >> 16) / 65535 - .12) / .76)
    # Knots can shift by up to a third of an interval without changing their order.
    return slot + (jitter - .5) * .64 * variation, level


def smooth(value):
    value = min(1., max(0., value))
    return value * value * (3 - 2 * value)


class LightAnimation:
    def __init__(self, settings, seconds, seamless):
        self.settings = settings
        self.seamless = seamless
        self.points = drivers(settings.animation_seed)
        self.drift_clocks = tuple(cycle_count(seconds * getattr(settings, rate) / 600, seamless)
                                  for rate in DRIFT_RATES)
        self.fade_clocks = tuple(seconds * getattr(settings, rate) / (settings.fade_interval * 10)
                                 for rate in FADE_RATES)

    def drift(self, index, layer, progress):
        path = self.settings.light_path
        cycles = self.drift_clocks[layer]
        if path == "Still" or not cycles:
            return 0., 0.
        phase, twist, reach = self.points[index, :3]
        a = math.tau * (progress*cycles + phase)
        b = math.tau * twist
        if path == "Orbit":
            dx, dy = math.cos(a), math.sin(a) * (.55 + .45*twist)
        elif path == "Sway":
            dx, dy = math.sin(a), .33*math.sin(2*a + b)
        elif path == "Wander":
            dx = .61*math.sin(a) + .28*math.sin(2*a+b) + .11*math.cos(3*a)
            dy = .58*math.cos(a+b) + .29*math.sin(3*a) + .13*math.cos(2*a+b)
        else:
            dx, dy = .75*math.sin(a+b), math.cos(a)
        reach = .47 + .53*reach
        return dx * reach * self.settings.light_travel_x / 100, dy * reach * self.settings.light_travel_y / 100

    def gain(self, index, layer, position_x, progress):
        config = self.settings
        pattern = config.fade_pattern
        rate = self.fade_clocks[layer]
        if pattern == "Off" or not rate:
            return 1.
        _, _, _, selector, phase, cadence = self.points[index]
        if selector >= config.fade_share / 100:
            return 1.
        variation = config.fade_variation / 100
        drift = variation * (cadence - .5)
        if pattern == "Rolling wave":
            clock = cycle_count(rate, self.seamless)
            offset = 1.65 * position_x + variation * (phase - .5) * .46
        else:
            clock = cycle_count(rate * 2 ** (2 * drift), self.seamless)
            offset = phase
        if pattern == "Random fades" and self.seamless:
            # Two distinct knots are required for brightness to vary over a wrapped timeline.
            clock = max(2, clock)
        moment = clock * progress + offset
        softness = config.fade_softness / 100
        if pattern in ("Swell", "Rolling wave"):
            blend = .5 + .5 * math.cos(math.tau * moment)
            blend = blend ** (1 + (1-softness)*2.5)
        elif pattern == "Sparks":
            slot = math.floor(moment)
            repeat = slot % int(clock) if self.seamless else slot
            key = hash_event(config.animation_seed, index, repeat)
            offset = ((key >> 16) / 65535 - .5) * variation * .27
            width = .08 + softness * .24
            blend = smooth(1 - abs(moment - slot - .50 - offset) / width) if (key & 3) else 0.
        else:
            slot = math.floor(moment)
            repeat = int(clock) if self.seamless else None
            current = fade_event(config.animation_seed, index, slot, repeat, variation)
            if moment < current[0]:
                left = fade_event(config.animation_seed, index, slot-1, repeat, variation)
                right = current
            else:
                left = current
                right = fade_event(config.animation_seed, index, slot+1, repeat, variation)
            fraction = (moment - left[0]) / (right[0] - left[0])
            ramp = .11 + .89 * softness
            blend = left[1] + (right[1] - left[1]) * smooth((fraction - (1-ramp)*.50) / ramp)
        return (config.fade_floor + (config.fade_peak-config.fade_floor) * blend) / 100
