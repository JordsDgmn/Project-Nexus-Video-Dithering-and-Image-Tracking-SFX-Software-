"""Regression checks for the optional live style and surface stacks."""

from dataclasses import asdict, replace
import unittest

import cv2
import numpy as np

from entropy_engine import ExportSpec, Look, Simulator
from entropy_runtime import decode_preset, preset_document
from entropy_style import FORMS, Style, pulse_exposure
from entropy_texture import Texture


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator((240, 144))
        self.look = Look()
        self.reference = self.sim.frame(.23, self.look)

    def test_form_selectors_generate_distinct_warps(self):
        frames = set()
        for form in FORMS:
            with self.subTest(form=form):
                look = replace(self.look, style=Style(form=form, bend=71))
                image = self.sim.frame(.23, look)
                self.assertGreater(cv2.absdiff(image, self.reference).mean(), .5)
                frames.add(image.tobytes())
        self.assertEqual(len(frames), len(FORMS))

    def test_layers_work_independently_and_can_be_bypassed(self):
        for controls in (
            dict(stretch_x=54), dict(stretch_y=-49), dict(turbulence=70),
            dict(specks=70), dict(glimmer=70), dict(glitter=70), dict(flare=70),
        ):
            with self.subTest(controls=controls):
                style = Style(**controls)
                active = self.sim.frame(.23, replace(self.look, style=style))
                self.assertGreater(cv2.absdiff(active, self.reference).max(), 6)
                bypassed = self.sim.frame(.23, replace(self.look, style=replace(style, enabled=False)))
                np.testing.assert_array_equal(bypassed, self.reference)
        for controls in (dict(paper=80), dict(scratches=80), dict(scanlines=80)):
            with self.subTest(controls=controls):
                base = replace(self.look, textures=Texture(**controls))
                self.assertGreater(cv2.absdiff(self.sim.frame(.23, base), self.reference).max(), 6)

    def test_combined_stack_closes_and_restores_from_preset(self):
        style = Style(form="Facets", bend=63, turbulence=48, seed=80792, specks=38, glimmer=54,
                      glitter=60, flare=82, flare_angle=-42, ghosts=7, strobe=39,
                      pulse_rate=2, pulse_width=20, pulse_shape="Shutter")
        look = replace(self.look, style=style, textures=Texture(paper=35, scratches=56, scanlines=22))
        spec = ExportSpec(seconds=19)
        self.assertEqual(decode_preset(preset_document(look, spec)), (look, spec))
        self.assertFalse(np.array_equal(self.sim.frame(0, look, 19), self.sim.frame(.18, look, 19)))
        np.testing.assert_array_equal(self.sim.frame(0, look, 19), self.sim.frame(1, look, 19))
        # Scrubbing must produce the same seeded result regardless of earlier frames.
        shuffled = self.sim.frame(.71, look, 19)
        self.sim.frame(.93, look, 19)
        np.testing.assert_array_equal(self.sim.frame(.71, look, 19), shuffled)
        previous = preset_document(self.look, spec)
        del previous["look"]["style"]
        for key in set(asdict(Texture())) - {
            "grain", "grain_size", "colored_grain", "distort", "distort_scale",
            "ripple", "ripple_count", "tatter", "edge_width", "roughness", "halftone",
            "cell_size", "angle", "print_style", "chromatic", "posterize", "levels", "vignette", "enabled",
        }:
            del previous["look"]["textures"][key]
        self.assertEqual(decode_preset(previous), (self.look, spec))

    def test_exposure_uses_elapsed_seconds_even_with_frozen_motion(self):
        style = Style(strobe=65, pulse_rate=2)
        look = replace(self.look, cycles=0, style=style)
        self.assertTrue(np.all(pulse_exposure(self.reference, style, .25) >= self.reference))
        at_rest = self.sim.frame(0, look, 6)
        peak = self.sim.frame(.25 / 6, look, 6)
        self.assertGreater(cv2.absdiff(at_rest, peak).mean(), 10)
        np.testing.assert_array_equal(peak, self.sim.frame(.25 / 1800, look, 1800))
        np.testing.assert_array_equal(peak, self.sim.frame(17.25 / 1800, look, 1800))
